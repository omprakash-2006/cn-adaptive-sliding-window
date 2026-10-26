"""
server.py - Adaptive Sliding Window TCP Server
================================================
College Computer Networks Lab Project:
"Preventing Server Overload Using Adaptive Sliding Window Protocol"

This server simulates a College Result Portal.
It supports two operational modes:
1. ADAPTIVE WINDOW MODE (Flow-controlled):
   - Limits active concurrent database queries to WINDOW_SIZE (default: 10).
   - If load exceeds WINDOW_SIZE, clients are placed into a fair FIFO queue.
   - Waiting clients receive live queue updates ("Position X of Y").
   - ZERO requests are dropped or timed out.
2. BASELINE MODE (Unprotected):
   - Naive server with no rate or flow control.
   - Attempts to process all incoming requests simultaneously.
   - When requests exceed server capacity limit, the server suffers from
     thread contention and socket drops, causing timeouts and failures.
"""

import socket
import math
import threading
import time
import json
import random
import sys
import argparse
from datetime import datetime

import protocol
from publication import PublicationStore
from version_network import parse_request, serve_result, send_error

# ============================================================================
# CONFIGURABLE CONSTANTS (Easily adjust for your lab demo)
# ============================================================================
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 65433
WINDOW_SIZE = 10                # Maximum simultaneous active requests in window
ERROR_SIMULATION_RATE = 0.05    # 5% probability of simulating transmission error
PROCESSING_DELAY = 0.20         # Realistic database query latency (200ms)
BASELINE_CAPACITY_LIMIT = 12    # In Baseline mode, concurrent load beyond this causes failure

from request_evidence import RequestEvidence
REQUEST_EVIDENCE = RequestEvidence()

GLOBAL_CONTROLLER = None
CURRENT_PROCESSING_DELAY = PROCESSING_DELAY

# ANSI Terminal Colors for viva demonstration
COLOR_RESET = "\033[0m"
COLOR_CYAN = "\033[96m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_MAGENTA = "\033[95m"
COLOR_BOLD = "\033[1m"


def estimate_wait_seconds(position, window_size, processing_delay):
    """Approximate batch wait for the simulator's concurrent processing window."""
    return round(math.ceil(max(0, position) / max(1, window_size)) * processing_delay, 2)


def timestamp() -> str:
    """Returns formatted current timestamp for logging."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log_event(category: str, message: str, color: str = COLOR_RESET):
    """Prints a thread-safe, timestamped, colored log message."""
    print(f"{COLOR_CYAN}[{timestamp()}]{COLOR_RESET} {color}[{category.upper():<12}]{COLOR_RESET} {message}", flush=True)


# ============================================================================
# IN-MEMORY STUDENT RESULTS DATABASE (100+ SAMPLE ENTRIES)
# ============================================================================
from student_roster import load_students
STUDENT_DATABASE = load_students()

PUBLICATIONS = PublicationStore(STUDENT_DATABASE)

# ============================================================================
# ADAPTIVE SLIDING WINDOW CONTROLLER
# ============================================================================
class AdaptiveSlidingWindowController:
    """
    Manages the active execution window and FIFO waiting queue.
    Ensures that at most WINDOW_SIZE requests are actively being processed,
    while queueing and updating remaining requests in strict FIFO order.
    """
    def __init__(self, window_size: int):
        self.window_size = window_size
        self.active_count = 0
        self.peak_active_count = 0
        # FIFO Queue holds: list of dicts:
        # {"id": req_id, "event": ready_event, "sock": client_sock, "arrival": timestamp}
        self.queue = []
        self.lock = threading.Lock()
        
        # Background scheduler daemon to promote queued requests in FIFO order
        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(target=self._fifo_scheduler_loop, daemon=True)
        self._scheduler_thread.start()

    def _fifo_scheduler_loop(self):
        """Continuously monitors the FIFO queue and promotes requests into active window."""
        while self._scheduler_running:
            time.sleep(0.04)
            with self.lock:
                self._try_promote_next_locked()

    def _cancel_locked(self, entry):
        entry["cancelled"] = True
        entry["event"].set()

    def _try_promote_next_locked(self):
        """Emit admission before waking the handler; failed clients use no work slot."""
        while self.queue and self.active_count < self.window_size:
            promoted = self.queue.pop(0)
            self.active_count += 1
            self.peak_active_count = max(self.peak_active_count, self.active_count)
            if not self._send_queue_update(promoted["sock"], 0, len(self.queue), "ACTIVE_PROCESSING"):
                self.active_count -= 1
                self._cancel_locked(promoted)
                continue
            promoted["event"].set()
            self._broadcast_queue_updates_locked()

    def _broadcast_queue_updates_locked(self):
        index = 0
        while index < len(self.queue):
            entry = self.queue[index]
            if not self._send_queue_update(entry["sock"], index + 1, len(self.queue), "QUEUED"):
                self.queue.pop(index)
                self._cancel_locked(entry)
            else:
                index += 1

    def acquire_slot(self, request_id, client_sock):
        ready_event = threading.Event()
        with self.lock:
            if self.active_count < self.window_size and not self.queue:
                self.active_count += 1
                self.peak_active_count = max(self.peak_active_count, self.active_count)
                if not self._send_queue_update(client_sock, 0, 0, "ACTIVE_PROCESSING"):
                    self.active_count -= 1
                    raise ConnectionError("Client disconnected before admission")
                return 0
            entry = {"id": request_id, "event": ready_event, "sock": client_sock,
                     "arrival": time.monotonic(), "cancelled": False}
            self.queue.append(entry)
            initial_position = len(self.queue)
            self._broadcast_queue_updates_locked()
        while not ready_event.wait(timeout=.15):
            with self.lock:
                for index, item in enumerate(self.queue):
                    if item is entry:
                        if not self._send_queue_update(client_sock, index + 1, len(self.queue), "QUEUED"):
                            self.queue.pop(index)
                            self._cancel_locked(entry)
                            self._broadcast_queue_updates_locked()
                        break
        if entry["cancelled"]:
            raise ConnectionError("Waiting student disconnected")
        return initial_position

    def release_slot(self, request_id: str):
        """
        Called when an active request completes.
        Decrements active count and promotes next waiting request from FIFO queue.
        """
        with self.lock:
            self.active_count = max(0, self.active_count - 1)
            self._try_promote_next_locked()

    def remove_disconnected(self, request_id):
        with self.lock:
            kept = []
            for entry in self.queue:
                if entry["id"] == request_id:
                    self._cancel_locked(entry)
                else:
                    kept.append(entry)
            self.queue = kept
            self._broadcast_queue_updates_locked()

    def _send_queue_update(self, client_sock: socket.socket, position: int, total_queued: int, status: str = "QUEUED"):
        """Sends a framed queue update message to the waiting client."""
        try:
            if position == 0:
                est_sec = 0.0
            else:
                est_sec = estimate_wait_seconds(position, self.window_size, CURRENT_PROCESSING_DELAY)

            update_data = {
                "position": position,
                "total_queued": total_queued,
                "status": status,
                "estimated_wait": est_sec,
                "active_window": self.active_count,
                "window_size": self.window_size
            }
            frame = protocol.create_frame(0, protocol.TYPE_QUEUE_UPDATE, json.dumps(update_data))
            previous_timeout = client_sock.gettimeout()
            try:
                client_sock.settimeout(.3)
                client_sock.sendall(frame)
                return True
            finally:
                client_sock.settimeout(previous_timeout)
        except (OSError, TimeoutError):
            return False


# ============================================================================
# CLIENT REQUEST HANDLER
# ============================================================================
def handle_client_adaptive(client_sock, client_addr, controller):
    """Version negotiation/retry stays inside one admitted FIFO request."""
    req_id = f"{client_addr[0]}:{client_addr[1]}"
    acquired = False
    query_id = roll = None
    try:
        client_sock.settimeout(10)
        frame = protocol.receive_frame(client_sock)
        if not frame:
            return
        if frame[1] != protocol.TYPE_REQUEST or not frame[5]:
            send_error(client_sock, "Invalid request frame", "PROTOCOL_ERROR")
            return
        roll, query_id, aware = parse_request(frame[2])
        REQUEST_EVIDENCE.record(query_id, roll, 'TCP_RECEIVED', client_addr)
        controller.acquire_slot(req_id, client_sock)
        acquired = True
        REQUEST_EVIDENCE.record(query_id, roll, 'TCP_ADMITTED')
        time.sleep(CURRENT_PROCESSING_DELAY)
        serve_result(client_sock, roll, query_id, aware, PUBLICATIONS, ERROR_SIMULATION_RATE)
    except Exception as exc:
        log_event("ERROR", f"Request {req_id}: {exc}", COLOR_RED)
    finally:
        if query_id is not None:
            REQUEST_EVIDENCE.record(query_id, roll, 'TCP_CLOSED')
        if acquired:
            controller.release_slot(req_id)
        else:
            controller.remove_disconnected(req_id)
        client_sock.close()


def handle_client_baseline(client_sock: socket.socket, client_addr: tuple, active_counter: list, counter_lock: threading.Lock):
    """
    Handles a single client connection in BASELINE (unprotected) mode.
    Simulates real-world server crash/timeout when concurrent threads exceed capacity.
    """
    req_id = f"{client_addr[0]}:{client_addr[1]}"
    with counter_lock:
        active_counter[0] += 1
        current_active = active_counter[0]

    try:
        log_event("BASELINE", f"Request from {req_id}. Current concurrent load: {current_active}", COLOR_CYAN)

        # Baseline Overload Simulation:
        # If active threads exceed BASELINE_CAPACITY_LIMIT, server experiences severe degradation:
        # Thread contention, socket reset/drop, or timeout.
        if current_active > BASELINE_CAPACITY_LIMIT:
            overload_factor = (current_active - BASELINE_CAPACITY_LIMIT) / BASELINE_CAPACITY_LIMIT
            failure_chance = min(0.90, 0.40 + overload_factor * 0.50)

            if random.random() < failure_chance:
                log_event("OVERLOAD", f"Server overloaded ({current_active} active)! Dropping request {req_id} (Connection Reset).", COLOR_RED)
                time.sleep(random.uniform(0.05, 0.2))
                # Forcibly close socket to simulate server drop / crash
                client_sock.close()
                return

        # Receive query
        frame_data = protocol.receive_frame(client_sock)
        if not frame_data:
            return

        if frame_data[1] != protocol.TYPE_REQUEST or not frame_data[5]:
            send_error(client_sock, "Invalid request frame", "PROTOCOL_ERROR")
            return
        seq_no, _, payload_bytes, _, _, _ = frame_data
        roll_number, query_id, version_aware = parse_request(payload_bytes)

        # Under high load, processing delay spikes non-linearly
        dynamic_delay = PROCESSING_DELAY * (1.0 + (current_active / BASELINE_CAPACITY_LIMIT) * 1.5)
        time.sleep(dynamic_delay)

        serve_result(client_sock, roll_number, query_id, version_aware, PUBLICATIONS, 0)

    except Exception as e:
        log_event("CRASH", f"Server failed while handling {req_id}: {e}", COLOR_RED)
    finally:
        with counter_lock:
            active_counter[0] -= 1
        try:
            client_sock.close()
        except Exception:
            pass


# ============================================================================
# MAIN SERVER LOOP
# ============================================================================
def start_server(mode: str = 'adaptive', port: int = SERVER_PORT, window_size: int = WINDOW_SIZE):
    """Starts the TCP multi-threaded server in either Adaptive or Baseline mode."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_sock.bind((SERVER_HOST, port))
        server_sock.listen(256)
    except OSError as e:
        print(f"{COLOR_RED}Error binding to port {port}: {e}{COLOR_RESET}")
        print("Tip: Check if another server instance is already running on this port.")
        sys.exit(1)

    print("\n" + "=" * 70)
    print(f"{COLOR_BOLD}COLLEGE RESULT PORTAL - NETWORKING DEMO SERVER{COLOR_RESET}")
    print(f"Host: {SERVER_HOST} | Port: {port}")
    print(f"Operational Mode: {COLOR_BOLD}{mode.upper()}{COLOR_RESET}")
    if mode == 'adaptive':
        print(f"Sliding Window Size: {window_size} concurrent active requests")
        print(f"Queue Strategy: Fair First-In-First-Out (FIFO) with live client telemetry")
        print(f"Error Simulation Rate: {int(ERROR_SIMULATION_RATE * 100)}% (CRC-32 + Hamming/ARQ)")
    else:
        print(f"Flow Control: {COLOR_RED}DISABLED (Unprotected Naive Server){COLOR_RESET}")
        print(f"Safe Server Capacity Limit: {BASELINE_CAPACITY_LIMIT} concurrent requests")
        print(f"Behavior under load: Uncontrolled thread spawning -> Contention & Dropped connections")
    print("=" * 70 + "\n")

    global GLOBAL_CONTROLLER
    controller = AdaptiveSlidingWindowController(window_size)
    GLOBAL_CONTROLLER = controller
    baseline_active = [0]
    baseline_lock = threading.Lock()

    try:
        while True:
            client_sock, client_addr = server_sock.accept()
            if mode == 'adaptive':
                t = threading.Thread(
                    target=handle_client_adaptive,
                    args=(client_sock, client_addr, controller),
                    daemon=True
                )
            else:
                t = threading.Thread(
                    target=handle_client_baseline,
                    args=(client_sock, client_addr, baseline_active, baseline_lock),
                    daemon=True
                )
            t.start()
    except KeyboardInterrupt:
        print(f"\n{COLOR_YELLOW}[SERVER SHUTDOWN] Server stopped by user.{COLOR_RESET}")
    finally:
        server_sock.close()


def get_live_metrics():
    """Returns current active window count, window size, queue length, and processing latency."""
    global GLOBAL_CONTROLLER, CURRENT_PROCESSING_DELAY
    active = 0
    q_len = 0
    w_size = WINDOW_SIZE
    if GLOBAL_CONTROLLER:
        with GLOBAL_CONTROLLER.lock:
            active = GLOBAL_CONTROLLER.active_count
            q_len = len(GLOBAL_CONTROLLER.queue)
            w_size = GLOBAL_CONTROLLER.window_size
    return {
        "active_window": active,
        "window_size": w_size,
        "queue_length": q_len,
        "processing_delay": CURRENT_PROCESSING_DELAY
    }


def set_demo_mode(mode_name: str):
    """Adjusts window size and delay for demonstrations."""
    global GLOBAL_CONTROLLER, CURRENT_PROCESSING_DELAY
    if mode_name == 'slowmo':
        CURRENT_PROCESSING_DELAY = 1.20
        if GLOBAL_CONTROLLER:
            with GLOBAL_CONTROLLER.lock:
                GLOBAL_CONTROLLER.window_size = 3
    else:
        CURRENT_PROCESSING_DELAY = 0.20
        if GLOBAL_CONTROLLER:
            with GLOBAL_CONTROLLER.lock:
                GLOBAL_CONTROLLER.window_size = 10
    return get_live_metrics()



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="College Result Portal Server with Adaptive Sliding Window")
    parser.add_argument("--mode", choices=["adaptive", "baseline"], default="adaptive",
                        help="Server mode: 'adaptive' (flow-controlled) or 'baseline' (unprotected)")
    parser.add_argument("--port", type=int, default=SERVER_PORT, help="Server TCP port")
    parser.add_argument("--window", type=int, default=WINDOW_SIZE, help="Sliding window size (active requests limit)")
    args = parser.parse_args()

    start_server(mode=args.mode, port=args.port, window_size=args.window)
