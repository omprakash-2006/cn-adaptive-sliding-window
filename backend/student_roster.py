"""Registration inputs and sample roster are independent of admission logic."""
import json
from pathlib import Path

FIRST_ID = "24BAD001"
LAST_ID = "24BAD130"


def normalize_roll(value):
    return "".join(value.split()).upper() if isinstance(value, str) else ""


def load_students():
    with (Path(__file__).parent / "student_data.json").open() as source:
        records = json.load(source)
    expected = {f"24BAD{i:03d}" for i in range(1, 131)}
    if not isinstance(records, dict) or set(records) != expected:
        raise ValueError("The sample roster must contain 24BAD001 through 24BAD130")
    for roll, record in records.items():
        scores = record.get("scores", {})
        if (record.get("roll_number") != roll or not scores
                or any(type(mark) is not int or not 0 <= mark <= 100 for mark in scores.values())):
            raise ValueError(f"Invalid sample record: {roll}")
    return records
