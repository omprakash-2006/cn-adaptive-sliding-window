"""Run 50 simultaneous version-aware students against the local project server."""
import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import client


def run_50_students_demo(target_roll="24BAD035", host="127.0.0.1", port=65433):
    rolls = [f"24BAD{i:03d}" for i in range(1, 51)]
    if target_roll not in rolls:
        rolls[-1] = target_roll
    barrier = threading.Barrier(50)
    def worker(roll):
        barrier.wait(timeout=5)
        def queue_update(position, total, status):
            if roll == target_roll:
                print(f"{roll}: {status} | queue position {position} of {total}", flush=True)
        return client.request_result(roll, host=host, port=port, timeout=15,
                                     verbose=False, queue_callback=queue_update)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(worker, rolls))
    successes = sum(r["success"] for r in results)
    verified = sum(r["version_verified"] for r in results)
    print(f"Completed: {successes}/50 successful results, {verified}/50 version-verified, "
          f"elapsed {time.monotonic()-started:.2f}s")
    target = next(r for r in results if r["roll_number"] == target_roll)
    if target["success"]:
        client.display_result_card(target["result_data"], target["latency"])
    else:
        print("Tracked result unavailable:", target["status_message"])
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roll", default="24BAD035")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=65433)
    args = parser.parse_args()
    run_50_students_demo(args.roll, args.host, args.port)
