"""One freshness gate for cached, TCP and fallback result paths."""
import copy
import time
from datetime import datetime, timezone
from publication import EXAM_ID, VerificationUnavailable


def guard_result(roll, candidate, store):
    with store.lock:
        try:
            current = store.snapshot(roll)
            if current is None:
                return {"success": False, "status_message": "RECORD_NOT_FOUND", "result_data": None}
            if candidate and candidate.get("success") and store.is_current(candidate.get("result_data")):
                result = copy.deepcopy(candidate)
                result.setdefault("delivery_source", "tcp_verified")
            else:
                if candidate and candidate.get("success"):
                    store.note("CACHE_REJECTED", roll=roll,
                               received_version=(candidate.get("result_data") or {}).get("result_version"),
                               required_version=current["result_version"])
                store.note("SAFE_FALLBACK", roll=roll, version=current["result_version"])
                result = {"success": True, "result_data": current, "roll_number": roll,
                          "status_message": "CURRENT_PUBLISHED_SNAPSHOT", "crc_verified": False,
                          "delivery_source": "published_snapshot"}
            result["version_verified"] = True
            result["release_version"] = current["result_version"]
            result["verified_at"] = datetime.now(timezone.utc).isoformat()
            return result
        except VerificationUnavailable:
            store.note("UNVERIFIED_BLOCKED", roll=roll)
            return {"success": False, "status_message": "VERIFICATION_UNAVAILABLE", "result_data": None,
                    "version_verified": False}


def resolve_result(roll, store, cache, fetch, force=False):
    key = (EXAM_ID, roll)
    with store.lock:
        try:
            store.snapshot(roll)  # Never trust a cache when the authority is unavailable.
            entry = cache.get(key)
            if not force and entry and time.monotonic() - entry[1] < 60:
                guarded = guard_result(roll, entry[0], store)
                if guarded["success"]:
                    guarded["delivery_source"] = "verified_cache" if store.is_current(entry[0].get("result_data")) else "published_snapshot"
                    cache[key] = (copy.deepcopy(guarded), time.monotonic())
                return guarded
        except VerificationUnavailable:
            return guard_result(roll, None, store)
    try:
        candidate = fetch()
    except Exception:
        candidate = None
    guarded = guard_result(roll, candidate, store)
    with store.lock:
        if guarded["success"]:
            cache[key] = (copy.deepcopy(guarded), time.monotonic())
    return guarded


def unavailable_page():
    return '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Result temporarily unavailable</title><style>
    body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;box-sizing:border-box;
    font-family:Arial,sans-serif;background:#eef4fb;color:#23344a}main{background:white;max-width:450px;
    padding:35px;border-radius:8px;border-top:5px solid #007bff;box-shadow:0 10px 30px #19345414}
    h1{font-size:23px;color:blue}p{line-height:1.8;font-size:14px}a{display:inline-block;padding:10px 18px;
    color:white;background:#007bff;border-radius:4px;text-decoration:none}</style></head><body><main>
    <h1>Your result is temporarily unavailable.</h1>
    <p>Please try again shortly. Your latest marksheet will be shown once it can be confirmed.</p>
    <a href="/">Return to result search</a></main></body></html>'''
