"""
client.py - Student Client for Result Portal
============================================
College Computer Networks Lab Project:
"Preventing Server Overload Using Adaptive Sliding Window Protocol"

This client:
1. Connects to the server over a TCP socket.
2. Encapsulates a result query in a custom binary frame.
3. If queued, listens to real-time queue position telemetry ("Position X of Y").
4. Once served, verifies the frame CRC-32 checksum to ensure transmission integrity.
5. Employs Hamming(7,4) Code (FEC) and ARQ Retransmission to recover from transmission errors.
6. Can run standalone for single student demo, or be imported by test_runner.py.
"""

import socket
import time
import json
import sys
import argparse
from datetime import datetime

import protocol

# Default Connection Settings
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 65433
DEFAULT_TIMEOUT = 10.0

# Terminal formatting
COLOR_RESET = "\033[0m"
COLOR_CYAN = "\033[96m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_MAGENTA = "\033[95m"
COLOR_BOLD = "\033[1m"


def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


# The version-aware client keeps the same public call signature for existing demos.
from version_network import request_result


def display_result_card(result_data: dict, latency: float):
    """Prints a clean ASCII report card for the student."""
    if not result_data:
        return

    print("\n" + "╔" + "═" * 56 + "╗")
    print(f"║ {COLOR_BOLD}EXAMINATION RESULT PORTAL - OFFICIAL MARKSHEET{COLOR_RESET}      ║")
    print("╠" + "═" * 56 + "╣")
    print(f"║ Roll Number : {result_data.get('roll_number', 'N/A'):<40} ║")
    print(f"║ Student Name: {result_data.get('name', 'N/A'):<40} ║")
    print(f"║ Branch      : {result_data.get('branch', 'N/A'):<40} ║")
    print(f"║ Semester    : {result_data.get('semester', 'N/A'):<40} ║")
    print("╟" + "─" * 56 + "╢")
    print("║ SUBJECT MARKS:                                         ║")

    scores = result_data.get("scores", {})
    for subj, mark in scores.items():
        print(f"║   • {subj:<28} : {mark:>3}/100            ║")

    status = result_data.get("status", "N/A")
    gpa = result_data.get("gpa", 0.0)
    status_colored = f"{COLOR_GREEN}PASS{COLOR_RESET}" if status == "PASS" else f"{COLOR_RED}FAIL{COLOR_RESET}"

    print("╟" + "─" * 56 + "╢")
    print(f"║ Cumulative GPA : {gpa:<4.2f}                                  ║")
    print(f"║ Final Result   : {status_colored:<49} ║")
    print(f"║ Total Latency  : {latency * 1000:<6.1f} ms                                ║")
    print("╚" + "═" * 56 + "╝\n")


# ============================================================================
# STANDALONE CLI EXECUTION
# ============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query College Result Portal")
    parser.add_argument("roll_number", nargs="?", default="24BAD025",
                        help="Student Roll Number to query (e.g., 24BAD025)")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server IP address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server TCP port")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Request timeout in seconds")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print(f"{COLOR_BOLD}STUDENT RESULT CLIENT{COLOR_RESET}")
    print(f"Querying Roll Number: {COLOR_CYAN}{args.roll_number}{COLOR_RESET}")
    print("=" * 60)

    result = request_result(
        roll_number=args.roll_number,
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        verbose=True
    )

    if result["success"] and result["result_data"]:
        display_result_card(result["result_data"], result["latency"])
    else:
        print(f"\n{COLOR_RED}❌ Request Failed: {result['status_message']}{COLOR_RESET}\n")
