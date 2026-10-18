"""Atomic, versioned publications for the local examination demonstration.

SHA-256 detects an inconsistent snapshot; it is not an authentication signature.
The lock defines the publication/verification ordering in this single process.
"""
import copy
import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

EXAM_ID = "MAY-2026"


class VerificationUnavailable(RuntimeError):
    pass


def digest(record):
    payload = {k: v for k, v in record.items() if k != "content_hash"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def valid_snapshot(record):
    return (isinstance(record, dict) and record.get("exam_id") == EXAM_ID
            and isinstance(record.get("result_version"), int)
            and record["result_version"] > 0 and record.get("content_hash") == digest(record))


class PublicationStore:
    def __init__(self, records, path=None):
        self.lock = threading.RLock()
        self.registered_rolls = frozenset(records)
        self.available = True
        self.events = []
        self.stale_once = {}
        self.fail_once = set()
        self.counters = {"stale_nacks": 0, "crc_nacks": 0, "version_acks": 0,
                         "cache_rejections": 0, "safe_fallbacks": 0,
                         "unverified_blocked": 0, "publications": 0}
        path = path or os.environ.get("CN_PUBLICATION_DB") or os.path.join(
            os.path.dirname(__file__), "publications.sqlite3")
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS revisions (exam TEXT, roll TEXT, "
                        "version INTEGER, payload TEXT NOT NULL, PRIMARY KEY(exam, roll, version))")
        for roll, data in records.items():
            exists = self.db.execute("SELECT 1 FROM revisions WHERE exam=? AND roll=? LIMIT 1",
                                     (EXAM_ID, roll)).fetchone()
            if not exists:
                self._insert(roll, data, 1)
        self.db.commit()

    def _insert(self, roll, data, version):
        record = copy.deepcopy(data)
        record.update(roll_number=roll, exam_id=EXAM_ID, result_version=version,
                      published_at=datetime.now(timezone.utc).isoformat())
        record.pop("content_hash", None)
        record["content_hash"] = digest(record)
        self.db.execute("INSERT INTO revisions VALUES (?,?,?,?)",
                        (EXAM_ID, roll, version, json.dumps(record)))
        return record

    def _require_available(self):
        if not self.available:
            raise VerificationUnavailable("Published version cannot currently be verified")

    def snapshot(self, roll, version=None):
        with self.lock:
            self._require_available()
            if roll not in self.registered_rolls:
                return None
            try:
                if version is None:
                    row = self.db.execute("SELECT payload FROM revisions WHERE exam=? AND roll=? "
                                          "ORDER BY version DESC LIMIT 1", (EXAM_ID, roll)).fetchone()
                else:
                    row = self.db.execute("SELECT payload FROM revisions WHERE exam=? AND roll=? AND version=?",
                                          (EXAM_ID, roll, version)).fetchone()
            except sqlite3.Error as exc:
                raise VerificationUnavailable("Publication storage is unavailable") from exc
            if not row:
                return None
            try:
                record = json.loads(row[0])
            except (TypeError, ValueError) as exc:
                raise VerificationUnavailable("Publication snapshot is unreadable") from exc
            if not valid_snapshot(record):
                raise VerificationUnavailable("Publication snapshot failed integrity validation")
            return record

    def is_current(self, record):
        with self.lock:
            self._require_available()
            if not valid_snapshot(record):
                return False
            current = self.snapshot(record.get("roll_number"))
            return bool(current and current["result_version"] == record["result_version"]
                        and current["content_hash"] == record["content_hash"])

    def publish_mark(self, roll, subject, mark):
        if type(mark) is not int or not 0 <= mark <= 100:
            raise ValueError("Marks must be an integer from 0 to 100")
        with self.lock:
            current = self.snapshot(roll)
            if not current or subject not in current["scores"]:
                raise ValueError("Unknown sample student or subject")
            current["scores"][subject] = mark
            current["status"] = "PASS" if all(m >= 40 for m in current["scores"].values()) else "FAIL"
            # Sample grading matches the grade-point rules used by the marksheet.
            credits = {"Computer Networks": 4, "Operating Systems": 4,
                       "Database Systems": 3, "Software Engineering": 3}
            points = lambda m: 10 if m >= 85 else 9 if m >= 75 else 8 if m >= 65 else 7 if m >= 55 else 6 if m >= 40 else 0
            current["gpa"] = round(sum(points(m) * credits.get(s, 3) for s, m in current["scores"].items()) /
                                   sum(credits.get(s, 3) for s in current["scores"]), 2)
            with self.db:
                record = self._insert(roll, current, current["result_version"] + 1)
            self.note("PUBLICATION", roll=roll, version=record["result_version"], mark=mark)
            return record

    def note(self, kind, **fields):
        with self.lock:
            event = {"time": datetime.now(timezone.utc).isoformat(), "event": kind, **fields}
            self.events.append(event)
            self.events = self.events[-100:]
            key = {"PUBLICATION": "publications", "STALE_NACK": "stale_nacks",
                   "CRC_NACK": "crc_nacks", "VERSION_ACK": "version_acks",
                   "CACHE_REJECTED": "cache_rejections", "SAFE_FALLBACK": "safe_fallbacks",
                   "UNVERIFIED_BLOCKED": "unverified_blocked"}.get(kind)
            if key:
                self.counters[key] += 1

    def arm_stale_reply(self, roll):
        with self.lock:
            current = self.snapshot(roll)
            if not current or current["result_version"] < 2:
                raise ValueError("Publish a correction before arming an old reply")
            self.stale_once[roll] = current["result_version"] - 1

    def take_stale_reply(self, roll):
        with self.lock:
            version = self.stale_once.pop(roll, None)
            return self.snapshot(roll, version) if version else None

    def take_failure(self, roll):
        with self.lock:
            if roll not in self.fail_once:
                return False
            self.fail_once.remove(roll)
            return True
