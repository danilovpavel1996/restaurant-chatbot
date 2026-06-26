"""Table capacity management — availability checks and slot filtering."""

import json
import os
from typing import Optional

TABLES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tables_config.json")
RESERVATIONS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reservations.json")


def load_tables() -> list[dict]:
    with open(TABLES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["tables"]


def load_reservations() -> list[dict]:
    if not os.path.exists(RESERVATIONS_FILE):
        return []
    with open(RESERVATIONS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [r for r in data.get("reservations", []) if r.get("status") != "cancelled"]


def find_available_table(
    date: str,
    time: str,
    party_size: int,
    preferred_location: Optional[str] = None,
) -> Optional[dict]:
    """
    Return the smallest suitable table free at date+time, or None if fully booked.
    Prefers preferred_location when set (indoor/terrace).
    """
    tables = load_tables()
    reservations = load_reservations()

    booked_ids = {
        r["table_id"]
        for r in reservations
        if r.get("date") == date and r.get("time") == time and r.get("table_id")
    }

    suitable = [
        t for t in tables
        if t["capacity"] >= party_size and t["id"] not in booked_ids
    ]
    if not suitable:
        return None

    def sort_key(t: dict) -> tuple:
        location_miss = 0 if (preferred_location and t["location"] == preferred_location) else 1
        return (location_miss, t["capacity"])

    suitable.sort(key=sort_key)
    return suitable[0]


def _time_to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def get_available_slots(
    date: str,
    party_size: int,
    preferred_location: Optional[str] = None,
) -> list[str]:
    """Return time slots where at least one suitable table is free."""
    from .utils import load_config
    config = load_config()
    all_slots: list[str] = config.get("reservations", {}).get("time_slots", [])

    return [
        slot for slot in all_slots
        if find_available_table(date, slot, party_size, preferred_location)
    ]


def find_nearest_available_slot(
    date: str,
    requested_time: str,
    party_size: int,
    preferred_location: Optional[str] = None,
) -> Optional[str]:
    """Return the available slot closest in time to requested_time, or None."""
    available = get_available_slots(date, party_size, preferred_location)
    if not available:
        return None
    requested_mins = _time_to_minutes(requested_time)
    return min(available, key=lambda s: abs(_time_to_minutes(s) - requested_mins))
