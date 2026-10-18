"""Application-layer version negotiation over the existing framed TCP stream."""
import json
import random
import socket
import time
import uuid

import protocol
from student_roster import normalize_roll
from publication import EXAM_ID, VerificationUnavailable, valid_snapshot

MAX_ATTEMPTS = 4


def parse_request(payload):
    text = payload.decode("utf-8").strip()
    if text.startswith("{"):
        request = json.loads(text)
        if not isinstance(request, dict) or request.get("exam_id") != EXAM_ID:
            raise ValueError("Unsupported examination")
        if not isinstance(request.get("request_id"), str) or len(request["request_id"]) > 80:
            raise ValueError("Invalid request ID")
        if not isinstance(request.get("roll_number"), str) or not request["roll_number"]:
            raise ValueError("Invalid register number")
        return normalize_roll(request["roll_number"]), request["request_id"], True
    return normalize_roll(text), "legacy", False


def send_error(sock, message, status="VERIFICATION_UNAVAILABLE"):
    sock.sendall(protocol.create_frame(1, protocol.TYPE_PROTOCOL_ERROR,
                 json.dumps({"status": status, "message": message})))


def serve_result(sock, roll, request_id, version_aware, store, error_rate=0):
    """A retry retains this connection's admitted slot; it never rejoins FIFO.

    VERSION_ACK certifies currency at the locked verification decision, not after
    receipt or after some future publication. Corrections racing the ACK retry.
    """
    sock.settimeout(3)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        if store.take_failure(roll):
            store.note("TCP_FAILURE_INJECTED", roll=roll, request_id=request_id)
            return
        stale = store.take_stale_reply(roll) if version_aware else None
        for attempt in range(MAX_ATTEMPTS):
            with store.lock:
                current = store.snapshot(roll)
                if not current:
                    send_error(sock, "Register number not found", "RECORD_NOT_FOUND")
                    return
                manifest = {"exam_id": EXAM_ID, "roll_number": roll, "request_id": request_id,
                            "result_version": current["result_version"], "content_hash": current["content_hash"]}
                if version_aware:
                    sock.sendall(protocol.create_frame(attempt * 3 + 1, protocol.TYPE_RELEASE_INFO, json.dumps(manifest)))
                candidate = stale if attempt == 0 and stale else current
                envelope = dict(candidate, request_id=request_id)
                payload = json.dumps(envelope).encode()
                clean_crc = protocol.calculate_crc32(payload)
                ecc = protocol.encode_status_with_hamming(0x50 if candidate["status"] == "PASS" else 0x46)
                wire_payload = payload
                corrupted = False
                if attempt == 0 and random.random() < error_rate:
                    if random.random() < .5:
                        wire_payload = protocol.corrupt_payload(payload)
                        corrupted = True
                    else:
                        ecc = protocol.corrupt_ecc_bytes(ecc)
                seq = attempt * 3 + 2
                sock.sendall(protocol.create_frame(seq, protocol.TYPE_RESULT_DATA, wire_payload,
                                                   ecc_bytes=ecc, override_checksum=clean_crc))
            if not version_aware and not corrupted:
                return
            response = protocol.receive_frame(sock)
            if not response or not response[5]:
                return
            if response[1] == protocol.TYPE_ERROR_NACK:
                store.note("CRC_NACK", roll=roll, request_id=request_id)
                if not version_aware:
                    sock.sendall(protocol.create_frame(seq + 1, protocol.TYPE_RESULT_DATA, payload,
                                                       ecc_bytes=protocol.encode_status_with_hamming(0x50 if candidate["status"] == "PASS" else 0x46)))
                    return
                continue
            reply = json.loads(response[2])
            if reply.get("request_id") != request_id or response[0] != seq:
                send_error(sock, "Unmatched version acknowledgement", "PROTOCOL_ERROR")
                return
            if response[1] == protocol.TYPE_STALE_NACK:
                store.note("STALE_NACK", roll=roll, request_id=request_id,
                           received_version=candidate["result_version"], required_version=current["result_version"],
                           retained_slot=True)
                continue
            if response[1] == protocol.TYPE_VERSION_CHECK:
                with store.lock:
                    if (reply.get("result_version") == candidate["result_version"]
                            and reply.get("content_hash") == candidate["content_hash"]
                            and store.is_current(candidate)):
                        sock.sendall(protocol.create_frame(seq, protocol.TYPE_VERSION_ACK, json.dumps(manifest)))
                        store.note("VERSION_ACK", roll=roll, request_id=request_id,
                                   version=candidate["result_version"], retained_slot=True)
                        return
                    store.note("VERSION_CHANGED_DURING_DELIVERY", roll=roll, request_id=request_id)
                continue
            send_error(sock, "Unexpected acknowledgement", "PROTOCOL_ERROR")
            return
        send_error(sock, "Publication is changing; please retry", "PUBLICATION_BUSY")
    except VerificationUnavailable as exc:
        store.note("UNVERIFIED_BLOCKED", roll=roll, request_id=request_id)
        send_error(sock, str(exc))


def request_result(roll_number="24BAD025", host="127.0.0.1", port=65433,
                   timeout=10, verbose=True, queue_callback=None):
    roll_number = normalize_roll(roll_number)
    started = time.monotonic()
    request_id = uuid.uuid4().hex
    stats = {"success": False, "latency": 0, "roll_number": roll_number, "queued": False,
             "max_queue_pos": 0, "error_detected": False, "error_corrected": False,
             "status_message": "INITIALIZING", "result_data": None, "request_id": request_id,
             "version_verified": False, "crc_verified": False, "stale_retries": 0, "crc_retries": 0}
    manifest = None
    pending = None
    pending_seq = None
    sock = None
    try:
        for attempt in range(4):
            try:
                sock = socket.create_connection((host, port), timeout)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(.03 * (attempt + 1))
        request = {"exam_id": EXAM_ID, "roll_number": roll_number, "request_id": request_id}
        sock.sendall(protocol.create_frame(1, protocol.TYPE_REQUEST, json.dumps(request)))
        while True:
            frame = protocol.receive_frame(sock)
            if not frame:
                stats["status_message"] = "CONNECTION_RESET"
                break
            seq, kind, payload, checksum, ecc, valid = frame
            if not valid:
                if kind != protocol.TYPE_RESULT_DATA:
                    stats["status_message"] = "CONTROL_FRAME_CRC_FAILED"
                    break
                stats["error_detected"] = True
                stats["crc_retries"] += 1
                if stats["crc_retries"] >= MAX_ATTEMPTS:
                    stats["status_message"] = "ARQ_RETRANSMISSION_FAILED"
                    break
                sock.sendall(protocol.create_frame(seq, protocol.TYPE_ERROR_NACK, b"CRC_FAILED"))
                continue
            info = json.loads(payload)
            if not isinstance(info, dict):
                stats["status_message"] = "INVALID_FRAME_PAYLOAD"
                break
            if kind == protocol.TYPE_QUEUE_UPDATE:
                pos, total = info.get("position", 0), info.get("total_queued", 0)
                stats["queued"] |= pos > 0
                stats["max_queue_pos"] = max(stats["max_queue_pos"], pos)
                if queue_callback:
                    try:
                        queue_callback(pos, total, info.get("status", "QUEUED"))
                    except Exception as exc:
                        stats["queue_callback_error"] = str(exc)[:200]
            elif kind == protocol.TYPE_RELEASE_INFO:
                if info.get("request_id") != request_id or info.get("exam_id") != EXAM_ID or info.get("roll_number") != roll_number:
                    stats["status_message"] = "UNMATCHED_RELEASE_INFO"
                    break
                manifest = info
                pending = None
            elif kind == protocol.TYPE_RESULT_DATA:
                _, corrected, _ = protocol.decode_status_with_hamming(ecc)
                stats["error_detected"] |= corrected
                stats["error_corrected"] |= corrected
                candidate = {k: v for k, v in info.items() if k != "request_id"}
                if (not manifest or info.get("request_id") != request_id
                        or info.get("roll_number") != roll_number or not valid_snapshot(candidate)
                        or candidate.get("result_version") != manifest["result_version"]
                        or candidate.get("content_hash") != manifest["content_hash"]):
                    stats["stale_retries"] += 1
                    if stats["stale_retries"] >= MAX_ATTEMPTS:
                        stats["status_message"] = "VERSION_RETRY_LIMIT"
                        break
                    sock.sendall(protocol.create_frame(seq, protocol.TYPE_STALE_NACK,
                        json.dumps({"request_id": request_id, "reason": "STALE_OR_INCONSISTENT_RESULT"})))
                    continue
                pending, pending_seq = candidate, seq
                sock.sendall(protocol.create_frame(seq, protocol.TYPE_VERSION_CHECK,
                    json.dumps({"request_id": request_id, "result_version": candidate["result_version"],
                                "content_hash": candidate["content_hash"]})))
            elif kind == protocol.TYPE_VERSION_ACK:
                if (not pending or seq != pending_seq or info != manifest):
                    stats["status_message"] = "UNMATCHED_VERSION_ACK"
                    break
                stats.update(success=True, result_data=pending, version_verified=True, crc_verified=True,
                             release_version=pending["result_version"],
                             status_message="RECOVERED_STALE_VERSION" if stats["stale_retries"] else
                             "RECOVERED_VIA_ARQ" if stats["crc_retries"] else "SUCCESS")
                stats["error_corrected"] |= stats["crc_retries"] > 0
                break
            elif kind == protocol.TYPE_PROTOCOL_ERROR:
                stats["status_message"] = info.get("status", "PROTOCOL_ERROR")
                break
    except (OSError, ValueError, TypeError, KeyError) as exc:
        stats["status_message"] = "CONNECTION_OR_PROTOCOL_ERROR: " + str(exc)
    finally:
        if sock:
            sock.close()
        stats["latency"] = time.monotonic() - started
    if verbose:
        print(f"[{request_id[:8]}] {roll_number}: {stats['status_message']} "
              f"version={stats.get('release_version', 'unverified')} latency={stats['latency']:.3f}s")
    return stats
