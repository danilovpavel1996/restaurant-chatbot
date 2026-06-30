"""Table capacity management — availability checks using Google Sheets Occupancy data."""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Europe/Bucharest")

TABLES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tables_config.json")
RESERVATIONS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reservations.json")


def load_tables() -> list[dict]:
    with open(TABLES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["tables"]


def load_reservations() -> list[dict]:
    """Kept for any local fallback logic; primary availability uses Occupancy sheet."""
    if not os.path.exists(RESERVATIONS_FILE):
        return []
    with open(RESERVATIONS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [r for r in data.get("reservations", []) if r.get("status") != "cancelled"]


def _time_to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _filter_past_and_too_soon_slots(date_str: str, slots: list[str]) -> list[str]:
    """If date_str is today (Bucharest time), drop slots in the past or < 1 hour away."""
    try:
        date_obj = datetime.strptime(date_str, "%d.%m.%Y").date()
    except ValueError:
        logger.warning("_filter: could not parse date_str=%r — skipping filter", date_str)
        return slots

    now = datetime.now(tz=_TZ)
    if date_obj != now.date():
        return slots

    min_allowed = now + timedelta(hours=1)
    logger.info(
        "Filtering today slots | now=%s min_allowed=%s slots_in=%s",
        now.strftime("%H:%M"), min_allowed.strftime("%H:%M"), slots,
    )

    result = []
    for slot in slots:
        h, m = map(int, slot.split(":"))
        slot_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if slot_dt >= min_allowed:
            result.append(slot)
        else:
            logger.info("Filtered out %s (< 1 h away)", slot)
    return result


def _all_slots() -> list[str]:
    from .utils import load_config
    config = load_config()
    return config.get("reservations", {}).get("time_slots", [])


def get_available_slots_from_occupancy(
    date: str,
    party_size: int,
    preferred_location: Optional[str] = None,
) -> list[str]:
    """
    Return slots where at least one table with capacity >= party_size shows 'FREE'
    in the Occupancy sheet. If preferred_location is set, only considers tables at
    that location.
    """
    from .sheets import get_occupancy

    tables = load_tables()
    occupancy = get_occupancy()
    date_occ = occupancy.get(date, {})
    all_slots = _all_slots()

    available = []
    for slot in all_slots:
        for table in tables:
            if table["capacity"] < party_size:
                continue
            if preferred_location and table["location"] != preferred_location:
                continue
            cell = date_occ.get(table["id"], {}).get(slot, "FREE")
            if cell.strip().upper() == "FREE":
                available.append(slot)
                break

    filtered = _filter_past_and_too_soon_slots(date, available)
    logger.info(
        "get_available_slots | date=%s party=%s loc=%s → %s",
        date, party_size, preferred_location or "any", filtered,
    )
    return filtered


def find_available_table_from_occupancy(
    date: str,
    time: str,
    party_size: int,
    preferred_location: Optional[str] = None,
) -> Optional[dict]:
    """
    Find the best available table using Occupancy sheet data.
    Prefers location match, then smallest fitting capacity.
    Returns None if nothing is free.
    """
    from .sheets import get_occupancy

    tables = load_tables()
    occupancy = get_occupancy()
    date_occ = occupancy.get(date, {})

    suitable = []
    for table in tables:
        if table["capacity"] < party_size:
            continue
        cell = date_occ.get(table["id"], {}).get(time, "FREE")
        if cell.strip().upper() == "FREE":
            suitable.append(table)

    if not suitable:
        return None

    def sort_key(t: dict) -> tuple:
        location_miss = 0 if (preferred_location and t["location"] == preferred_location) else 1
        return (location_miss, t["capacity"])

    suitable.sort(key=sort_key)
    return suitable[0]


def get_available_slots_by_location(date: str, party_size: int) -> dict:
    """
    Return available slots split by location:
    { 'indoor': [...], 'terrace': [...], 'any': [...] }
    """
    indoor_slots  = get_available_slots_from_occupancy(date, party_size, "indoor")
    terrace_slots = get_available_slots_from_occupancy(date, party_size, "terrace")
    any_slots     = sorted(set(indoor_slots + terrace_slots), key=_time_to_minutes)
    return {"indoor": indoor_slots, "terrace": terrace_slots, "any": any_slots}


def find_nearest_available_from_occupancy(
    date: str,
    requested_time: str,
    party_size: int,
    preferred_location: Optional[str] = None,
) -> dict:
    """
    Find nearest FREE slot for both indoor and terrace around requested_time.
    Returns: { 'indoor': 'HH:MM' or None, 'terrace': 'HH:MM' or None }
    """
    requested_mins = _time_to_minutes(requested_time)

    indoor_slots  = get_available_slots_from_occupancy(date, party_size, "indoor")
    terrace_slots = get_available_slots_from_occupancy(date, party_size, "terrace")

    nearest_indoor  = min(indoor_slots,  key=lambda s: abs(_time_to_minutes(s) - requested_mins)) if indoor_slots  else None
    nearest_terrace = min(terrace_slots, key=lambda s: abs(_time_to_minutes(s) - requested_mins)) if terrace_slots else None

    return {"indoor": nearest_indoor, "terrace": nearest_terrace}
