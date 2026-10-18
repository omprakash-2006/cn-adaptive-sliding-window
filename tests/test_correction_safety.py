"""Deterministic protocol/publication tests against loopback TCP and HTTP servers."""
import concurrent.futures
import copy
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
TEMP = tempfile.TemporaryDirectory(prefix="cn-publication-test-")
os.environ["CN_PUBLICATION_DB"] = str(Path(TEMP.name) / "publications.sqlite3")
import protocol
import server
import client
import web_portal
import correction_lab
from publication import EXAM_ID, PublicationStore, VerificationUnavailable, valid_snapshot
from portal_safety import guard_result


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class CorrectionSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.log_event = lambda *args, **kwargs: None
        cls.tcp_port = free_port()
        cls.http = web_portal.ThreadingHTTPServer(("127.0.0.1", 0), web_portal.PortalHTTPHandler)
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"
        web_portal.TCP_SERVER_PORT = cls.tcp_port
        web_portal.DEMO_ENABLED = True
        server.ERROR_SIMULATION_RATE = 0
        threading.Thread(target=server.start_server,
                         kwargs={"port": cls.tcp_port, "window_size": 3}, daemon=True).start()
        deadline = time.monotonic() + 3
        while server.GLOBAL_CONTROLLER is None and time.monotonic() < deadline:
            time.sleep(.01)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()

    def setUp(self):
        deadline = time.monotonic() + 3
        while (server.GLOBAL_CONTROLLER.active_count or server.GLOBAL_CONTROLLER.queue) and time.monotonic() < deadline:
            time.sleep(.005)
        server.GLOBAL_CONTROLLER.window_size = 3
        server.GLOBAL_CONTROLLER.peak_active_count = 0
        with server.PUBLICATIONS.lock:
            server.PUBLICATIONS.available = True
            server.PUBLICATIONS.stale_once.clear()
            server.PUBLICATIONS.fail_once.clear()
            web_portal.CACHED_RESULTS.clear()
        server.CURRENT_PROCESSING_DELAY = .025
        server.ERROR_SIMULATION_RATE = 0

    def fetch(self, path):
        try:
            with urlopen(self.base + path, timeout=8) as response:
                return response.status, response.read().decode()
        except HTTPError as exc:
            return exc.code, exc.read().decode()

    def request(self, roll="24BAD025", **kwargs):
        return client.request_result(roll, port=self.tcp_port, verbose=False, timeout=5, **kwargs)

    def publish(self, mark):
        return server.PUBLICATIONS.publish_mark("24BAD025", "Computer Networks", mark)

    def test_all_sample_grades_match_marksheet_rules(self):
        credits = {"Computer Networks": 4, "Operating Systems": 4, "Database Systems": 3, "Software Engineering": 3}
        def points(mark):
            return next(point for threshold, point in [(85,10),(75,9),(65,8),(55,7),(40,6),(0,0)] if mark >= threshold)
        for roll, record in server.STUDENT_DATABASE.items():
            scores = record["scores"]
            self.assertEqual(set(scores), set(credits), roll)
            self.assertEqual(record["status"], "PASS" if min(scores.values()) >= 40 else "FAIL", roll)
            self.assertEqual(record["gpa"], round(sum(points(m)*credits[k] for k,m in scores.items())/14, 2), roll)

    def test_browser_queue_sessions_deliver_matching_results(self):
        server.CURRENT_PROCESSING_DELAY = .08
        rolls = [f"24BAD{i:03d}" for i in range(1, 26)]
        def start(roll):
            code, body = self.fetch("/api/query_start?roll=" + roll)
            self.assertEqual(code, 200)
            return roll, json.loads(body)["session_id"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as pool:
            pending = dict(pool.map(start, rolls))
        deadline = time.monotonic() + 8
        observed_queue = False
        while pending and time.monotonic() < deadline:
            for roll, sid in list(pending.items()):
                code, body = self.fetch("/api/query_poll?session_id=" + sid)
                update = json.loads(body)
                self.assertEqual(code, 200)
                observed_queue |= update["position"] > 0
                if update["done"]:
                    result = update["result"]
                    self.assertTrue(result["success"] and result["version_verified"])
                    self.assertEqual(result["result_data"]["roll_number"], roll)
                    pending.pop(roll)
            time.sleep(.02)
        self.assertFalse(pending)
        self.assertTrue(observed_queue)
        self.assertLessEqual(server.GLOBAL_CONTROLLER.peak_active_count, 3)

    def test_cached_result_must_belong_to_requested_student(self):
        other = self.request("24BAD026")
        self.assertTrue(other["success"])
        with server.PUBLICATIONS.lock:
            web_portal.CACHED_RESULTS[(EXAM_ID, "24BAD025")] = (other, time.monotonic())
        code, body = self.fetch("/api/query?roll=24BAD025")
        result = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual(result["result_data"]["roll_number"], "24BAD025")
        self.assertEqual(result["delivery_source"], "published_snapshot")
        self.assertFalse(result["crc_verified"])

    def test_publication_survives_reopen_and_history_is_immutable(self):
        path = str(Path(TEMP.name) / "persistence.sqlite3")
        first = PublicationStore(server.STUDENT_DATABASE, path)
        old = first.snapshot("24BAD025")
        revised = first.publish_mark("24BAD025", "Computer Networks", 43)
        first.db.close()
        second = PublicationStore(server.STUDENT_DATABASE, path)
        self.assertEqual(second.snapshot("24BAD025"), revised)
        self.assertEqual(second.snapshot("24BAD025", old["result_version"]), old)
        self.assertTrue(valid_snapshot(revised))
        second.db.close()

    def test_versioned_tcp_and_fec_crc_recovery(self):
        result = self.request()
        self.assertTrue(result["success"])
        self.assertTrue(result["version_verified"])
        self.assertTrue(result["crc_verified"])
        self.assertTrue(valid_snapshot(result["result_data"]))
        server.ERROR_SIMULATION_RATE = 1
        with patch("version_network.random.random", side_effect=[0, .01]):
            crc = self.request()
        self.assertTrue(crc["success"])
        self.assertEqual(crc["crc_retries"], 1)
        with patch("version_network.random.random", side_effect=[0, .99]):
            fec = self.request()
        self.assertTrue(fec["success"])
        self.assertTrue(fec["error_corrected"])

    def test_crc_valid_stale_reply_retries_without_a_second_admission(self):
        self.publish(38)
        latest = self.publish(43)
        server.PUBLICATIONS.arm_stale_reply("24BAD025")
        controller = server.GLOBAL_CONTROLLER
        with patch.object(controller, "acquire_slot", wraps=controller.acquire_slot) as admission:
            result = self.request()
        self.assertTrue(result["success"])
        self.assertEqual(result["stale_retries"], 1)
        self.assertEqual(admission.call_count, 1)
        self.assertEqual(result["result_data"]["scores"]["Computer Networks"], 43)
        self.assertEqual(result["release_version"], latest["result_version"])
        events = server.PUBLICATIONS.events
        nack = [e for e in events if e["event"] == "STALE_NACK" and e["request_id"] == result["request_id"]]
        self.assertTrue(nack and nack[-1]["retained_slot"])

    def test_correction_between_result_and_ack_is_rechecked(self):
        old = self.publish(38)
        query_id = "controlled-publication-race"
        with socket.create_connection(("127.0.0.1", self.tcp_port), timeout=4) as sock:
            sock.sendall(protocol.create_frame(1, protocol.TYPE_REQUEST, json.dumps(
                {"roll_number": "24BAD025", "exam_id": EXAM_ID, "request_id": query_id})))
            def next_non_queue():
                while True:
                    frame = protocol.receive_frame(sock)
                    self.assertIsNotNone(frame)
                    self.assertTrue(frame[5])
                    if frame[1] != protocol.TYPE_QUEUE_UPDATE:
                        return frame
            manifest = next_non_queue()
            result = next_non_queue()
            self.assertEqual(manifest[1], protocol.TYPE_RELEASE_INFO)
            latest = self.publish(43)
            sock.sendall(protocol.create_frame(result[0], protocol.TYPE_VERSION_CHECK, json.dumps(
                {"request_id": query_id, "result_version": old["result_version"], "content_hash": old["content_hash"]})))
            updated_manifest = next_non_queue()
            updated = next_non_queue()
            self.assertEqual(json.loads(updated[2])["result_version"], latest["result_version"])
            sock.sendall(protocol.create_frame(updated[0], protocol.TYPE_VERSION_CHECK, json.dumps(
                {"request_id": query_id, "result_version": latest["result_version"], "content_hash": latest["content_hash"]})))
            ack = next_non_queue()
            self.assertEqual(ack[1], protocol.TYPE_VERSION_ACK)
            self.assertEqual(json.loads(ack[2]), json.loads(updated_manifest[2]))

    def test_old_cache_is_rejected_after_correction(self):
        old = self.publish(38)
        web_portal.CACHED_RESULTS[(EXAM_ID, "24BAD025")] = (
            {"success": True, "result_data": old}, time.monotonic())
        latest = self.publish(43)
        status, body = self.fetch("/api/query?roll=24BAD025")
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["result_data"]["scores"]["Computer Networks"], 43)
        self.assertEqual(result["release_version"], latest["result_version"])
        self.assertEqual(result["delivery_source"], "published_snapshot")
        status, html = self.fetch("/result?roll=24BAD025")
        self.assertEqual(status, 200)
        self.assertNotIn("Published result version", html)
        self.assertNotIn("SHA-256", html)
        self.assertIn("Marks / 100", html)
        self.assertIn("43</td>", html)

    def test_inconsistent_same_version_snapshot_is_not_accepted(self):
        current = server.PUBLICATIONS.snapshot("24BAD025")
        poisoned = copy.deepcopy(current)
        poisoned["scores"]["Computer Networks"] = 1
        result = guard_result("24BAD025", {"success": True, "result_data": poisoned}, server.PUBLICATIONS)
        self.assertEqual(result["result_data"], current)
        self.assertNotEqual(result["result_data"]["scores"]["Computer Networks"], 1)

    def test_failed_tcp_uses_only_current_published_snapshot(self):
        self.publish(38)
        latest = self.publish(43)
        server.PUBLICATIONS.fail_once.add("24BAD025")
        status, body = self.fetch("/api/query?roll=24BAD025&force=1")
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["release_version"], latest["result_version"])
        self.assertEqual(result["delivery_source"], "published_snapshot")
        self.assertFalse(result["crc_verified"])

    def test_authority_outage_blocks_even_a_previously_valid_cache(self):
        current = server.PUBLICATIONS.snapshot("24BAD025")
        web_portal.CACHED_RESULTS[(EXAM_ID, "24BAD025")] = (
            {"success": True, "result_data": current}, time.monotonic())
        server.PUBLICATIONS.available = False
        status, body = self.fetch("/api/query?roll=24BAD025")
        self.assertEqual(status, 503)
        self.assertIsNone(json.loads(body)["result_data"])
        self.assertFalse(self.request()["success"])
        status, html = self.fetch("/result?roll=24BAD025")
        self.assertEqual(status, 503)
        self.assertIn("temporarily unavailable", html)
        self.assertNotIn("Computer Networks", html)

    def test_queued_request_uses_correction_and_load_stays_bounded(self):
        self.publish(38)
        server.CURRENT_PROCESSING_DELAY = .12
        queued = threading.Event()
        blockers_active = threading.Event()
        active_rolls = set()
        active_lock = threading.Lock()
        def observe_active(roll, position):
            if position == 0:
                with active_lock:
                    active_rolls.add(roll)
                    if len(active_rolls) == 3:
                        blockers_active.set()
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
            blockers = [pool.submit(self.request, f"24BAD{1+i:03d}",
                        queue_callback=lambda p, t, s, r=f"24BAD{1+i:03d}": observe_active(r, p)) for i in range(3)]
            self.assertTrue(blockers_active.wait(2), "The three blocking requests were not admitted")
            target = pool.submit(self.request, "24BAD025", queue_callback=lambda p, t, s: queued.set() if p > 0 else None)
            self.assertTrue(queued.wait(2), "Target did not enter FIFO")
            latest = self.publish(43)
            futures = [pool.submit(self.request, f"24BAD{10+i:03d}") for i in range(46)]
            result = target.result(timeout=5)
            results = [f.result(timeout=5) for f in blockers + futures] + [result]
        self.assertEqual(len(results), 50)
        self.assertTrue(all(r["success"] and r["version_verified"] for r in results))
        self.assertTrue(result["queued"])
        self.assertEqual(result["release_version"], latest["result_version"])
        self.assertEqual(result["result_data"]["scores"]["Computer Networks"], 43)
        with server.GLOBAL_CONTROLLER.lock:
            self.assertLessEqual(server.GLOBAL_CONTROLLER.active_count, 3)
            self.assertEqual(server.GLOBAL_CONTROLLER.peak_active_count, 3)
            self.assertEqual(len(server.GLOBAL_CONTROLLER.queue), 0)

    def test_student_page_has_no_protocol_or_lab_details(self):
        status, html = self.fetch("/")
        self.assertEqual(status, 200)
        self.assertNotIn('id="labControls"', html)
        self.assertNotIn('href="/demo"', html)
        self.assertNotIn("CRC-32", html)
        web_portal.DEMO_ENABLED = False
        try:
            self.assertEqual(self.fetch("/demo")[0], 403)
            self.assertEqual(self.fetch("/students")[0], 404)
            self.assertEqual(self.fetch("/api/simulate_burst?count=50")[0], 403)
        finally:
            web_portal.DEMO_ENABLED = True

    def test_unknown_roll_and_local_demo_authorization(self):
        status, body = self.fetch("/api/query?roll=24BAD999")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["status_message"], "RECORD_NOT_FOUND")
        for token, origin in [("wrong", self.base), (correction_lab.DEMO_TOKEN, "https://other.example")]:
            request = Request(self.base + "/api/demo/action", data=b'{"action":"prepare"}', method="POST",
                              headers={"Content-Type": "application/json", "X-Demo-Token": token, "Origin": origin})
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=3)
            self.assertEqual(caught.exception.code, 403)

    def test_baseline_handler_accepts_the_version_aware_client(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(3)
            port = listener.getsockname()[1]
            def worker():
                connection, address = listener.accept()
                server.handle_client_baseline(connection, address, [0], threading.Lock())
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            result = client.request_result("24BAD025", port=port, verbose=False, timeout=3)
            thread.join(3)
        self.assertTrue(result["success"] and result["version_verified"])
        self.assertFalse(thread.is_alive())

    def test_all_130_registrations_in_a_simultaneous_tcp_burst(self):
        rolls = list(server.STUDENT_DATABASE)
        self.assertEqual(rolls, [f"24BAD{i:03d}" for i in range(1, 131)])
        server.GLOBAL_CONTROLLER.window_size = 10
        server.CURRENT_PROCESSING_DELAY = .035
        barrier = threading.Barrier(130)
        positions = {roll: [] for roll in rolls}
        def worker(roll):
            barrier.wait(timeout=5)
            return self.request(roll, queue_callback=lambda p, t, s: positions[roll].append(p))
        with concurrent.futures.ThreadPoolExecutor(max_workers=130) as pool:
            results = list(pool.map(worker, rolls))
        failed = [(r["roll_number"], r["status_message"]) for r in results if not r["success"]]
        self.assertEqual(failed, [])
        self.assertEqual(len({r["request_id"] for r in results}), 130)
        self.assertLessEqual(server.GLOBAL_CONTROLLER.peak_active_count, 10)
        for roll, result in zip(rolls, results):
            self.assertEqual(result["result_data"]["roll_number"], roll)
            self.assertTrue(result["version_verified"] and valid_snapshot(result["result_data"]))
            positive = [p for p in positions[roll] if p > 0]
            self.assertEqual(positive, sorted(positive, reverse=True), f"Queue position moved backwards for {roll}")

    def test_all_130_students_through_parallel_http_requests(self):
        server.GLOBAL_CONTROLLER.window_size = 10
        server.CURRENT_PROCESSING_DELAY = .025
        def worker(roll):
            status, body = self.fetch("/api/query?roll=" + roll)
            return roll, status, json.loads(body)
        with concurrent.futures.ThreadPoolExecutor(max_workers=45) as pool:
            results = list(pool.map(worker, server.STUDENT_DATABASE))
        for roll, status, result in results:
            self.assertEqual(status, 200, roll)
            self.assertEqual(result["result_data"]["roll_number"], roll)
            self.assertTrue(result["version_verified"])

    def test_registration_boundaries_normalization_and_repeated_requests(self):
        self.assertTrue(self.request("24BAD001")["success"])
        self.assertTrue(self.request("24BAD130")["success"])
        for roll in ["24BAD000", "24BAD131", "23BAD001", "24BAD01", "ROLL-1025"]:
            self.assertFalse(self.request(roll)["success"], roll)
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
            results = list(pool.map(lambda _: self.request("24 bad 025"), range(30)))
        self.assertTrue(all(r["success"] and r["result_data"]["roll_number"] == "24BAD025" for r in results))
        self.assertEqual(len({r["request_id"] for r in results}), 30)

    def test_invalid_crc_request_is_rejected_before_admission(self):
        with socket.create_connection(("127.0.0.1", self.tcp_port), timeout=3) as sock:
            sock.sendall(protocol.create_frame(1, protocol.TYPE_REQUEST, "24BAD025", override_checksum=0))
            reply = protocol.receive_frame(sock)
        self.assertEqual(reply[1], protocol.TYPE_PROTOCOL_ERROR)
        self.assertEqual(json.loads(reply[2])["status"], "PROTOCOL_ERROR")
        self.assertEqual(server.GLOBAL_CONTROLLER.peak_active_count, 0)

    def test_disconnected_waiter_is_removed_before_admission(self):
        server.CURRENT_PROCESSING_DELAY = 1
        active = threading.Event()
        seen = set()
        lock = threading.Lock()
        def callback(roll, position):
            if position == 0:
                with lock:
                    seen.add(roll)
                    if len(seen) == 3:
                        active.set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            blockers = [pool.submit(self.request, f"24BAD{i:03d}",
                        queue_callback=lambda p, t, s, r=f"24BAD{i:03d}": callback(r, p)) for i in range(1, 4)]
            self.assertTrue(active.wait(2))
            with socket.create_connection(("127.0.0.1", self.tcp_port), timeout=3) as sock:
                sock.sendall(protocol.create_frame(1, protocol.TYPE_REQUEST, "24BAD010"))
                self.assertEqual(protocol.receive_frame(sock)[1], protocol.TYPE_QUEUE_UPDATE)
                sock.shutdown(socket.SHUT_RDWR)
            deadline = time.monotonic() + .7
            while server.GLOBAL_CONTROLLER.queue and time.monotonic() < deadline:
                time.sleep(.01)
            with server.GLOBAL_CONTROLLER.lock:
                self.assertEqual(len(server.GLOBAL_CONTROLLER.queue), 0, "Disconnected student retained a queue slot")
            self.assertTrue(all(f.result(timeout=3)["success"] for f in blockers))

    def test_callback_failure_does_not_discard_a_valid_result(self):
        def broken_callback(*args):
            raise RuntimeError("Test callback failure")
        result = self.request(queue_callback=broken_callback)
        self.assertTrue(result["success"] and result["version_verified"])
        self.assertEqual(result["queue_callback_error"], "Test callback failure")

    def test_completed_sessions_expire_without_removing_waiting_students(self):
        now = time.monotonic()
        with web_portal.SESSIONS_LOCK:
            web_portal.QUERY_SESSIONS.update({
                "expired-test": {"done": True, "completed_at": now - 301},
                "recent-test": {"done": True, "completed_at": now},
                "waiting-test": {"done": False, "created_at": now - 301}})
        web_portal.cleanup_completed_sessions()
        with web_portal.SESSIONS_LOCK:
            self.assertNotIn("expired-test", web_portal.QUERY_SESSIONS)
            self.assertIn("recent-test", web_portal.QUERY_SESSIONS)
            self.assertIn("waiting-test", web_portal.QUERY_SESSIONS)
            for key in ["recent-test", "waiting-test"]:
                del web_portal.QUERY_SESSIONS[key]


if __name__ == "__main__":
    unittest.main(verbosity=2)
