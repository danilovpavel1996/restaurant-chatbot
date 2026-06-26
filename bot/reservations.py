"""Reservation CRUD — all reads/writes go through reservations.json."""

import json
import os
import re
from datetime import datetime

RESERVATIONS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "reservations.json"
)


def _load() -> dict:
    if not os.path.exists(RESERVATIONS_FILE):
        _save({"reservations": [], "waitlist": []})
    with open(RESERVATIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(RESERVATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _next_id(reservations: list) -> str:
    max_num = 0
    for res in reservations:
        m = re.match(r"RES-(\d+)$", res.get("id", ""))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"RES-{max_num + 1:03d}"


def create_reservation(data: dict) -> str:
    """Persist a new reservation and return its generated ID."""
    storage = _load()
    res_id = _next_id(storage["reservations"])
    record = {
        "id": res_id,
        "status": "confirmed",
        "created_at": datetime.now().isoformat(),
        **data,
    }
    storage["reservations"].append(record)
    _save(storage)
    return res_id


def find_by_phone(phone: str) -> list[dict]:
    """Return all reservations whose phone matches (last 8 digits compared)."""
    storage = _load()
    needle = re.sub(r"\D", "", phone)
    suffix = needle[-8:] if len(needle) >= 8 else needle
    results = []
    for res in storage["reservations"]:
        haystack = re.sub(r"\D", "", res.get("phone", ""))
        if haystack.endswith(suffix):
            results.append(res)
    return results


def find_by_id(res_id: str) -> dict | None:
    storage = _load()
    for res in storage["reservations"]:
        if res["id"] == res_id:
            return res
    return None


def cancel_reservation(res_id: str) -> bool:
    """Mark a reservation as cancelled. Returns True if found."""
    storage = _load()
    for res in storage["reservations"]:
        if res["id"] == res_id:
            res["status"] = "cancelled"
            _save(storage)
            return True
    return False


def update_reservation(res_id: str, updates: dict) -> bool:
    """Apply a partial update to a reservation. Returns True if found."""
    storage = _load()
    for res in storage["reservations"]:
        if res["id"] == res_id:
            res.update(updates)
            _save(storage)
            return True
    return False
