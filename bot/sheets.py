"""Google Sheets integration — append reservations to a spreadsheet."""

import json
import logging
import os
import time
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SPREADSHEET_ID = "1Pb5e69wjKV4ybzhyUanki0fk0A_-lH4WJyUqXcYhK20"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_client() -> gspread.Client | None:
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        logger.warning("GOOGLE_CREDENTIALS_JSON not set, skipping Sheets")
        return None
    try:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as exc:
        logger.error("Failed to initialize Google Sheets client: %s", exc)
        return None


_TABLES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tables_config.json")

_OCCUPANCY_SLOTS = [
    "10:00", "11:00", "12:00", "13:00", "14:00", "15:00",
    "16:00", "17:00", "18:00", "19:00", "20:00", "21:00", "22:00", "23:00",
]


def _load_tables_config() -> list[dict]:
    with open(_TABLES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["tables"]


def get_occupancy() -> dict:
    """
    Read the Occupancy tab and return a nested dict:
    { "DD.MM.YYYY": { "T01": { "10:00": "FREE", "11:00": "Paul (RES-001)", ... }, ... } }
    Returns {} on any error or if the sheet is not yet initialised.
    """
    try:
        client = _get_client()
        if not client:
            return {}
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        occ_sheet = spreadsheet.worksheet("Occupancy")
        all_values = occ_sheet.get_all_values()
        if not all_values or all_values[0][0] != "Date":
            return {}

        header = all_values[0]          # ['Date','Table','Capacity','Location','10:00',...]
        slot_start_idx = 4

        occupancy: dict = {}
        for row in all_values[1:]:
            if len(row) < slot_start_idx:
                continue
            date_val = row[0]
            table_id = row[1]
            if not date_val or not table_id:
                continue
            if date_val not in occupancy:
                occupancy[date_val] = {}
            occupancy[date_val][table_id] = {}
            for i, slot in enumerate(header[slot_start_idx:], start=slot_start_idx):
                value = row[i] if i < len(row) else "FREE"
                occupancy[date_val][table_id][slot] = value if value else "FREE"

        return occupancy
    except Exception as exc:
        logger.error("Failed to read occupancy: %s", exc)
        return {}


def append_reservation(reservation: dict) -> None:
    try:
        client = _get_client()
        if not client:
            return
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        row = [
            reservation.get("id", ""),
            reservation.get("name", ""),
            reservation.get("date", ""),
            reservation.get("time", ""),
            reservation.get("party_size", ""),
            reservation.get("phone", ""),
            reservation.get("seating_preference", reservation.get("seating", "")),
            reservation.get("hookah") or "None",
            reservation.get("special_requests") or "None",
            reservation.get("created_at", ""),
            reservation.get("table_id", ""),
        ]
        logger.info(f"Appending to Sheets: {row}")
        sheet.append_row(row)
        logger.info("Reservation %s saved to Google Sheets", reservation.get("id"))
        update_occupancy_sheet(reservation)
    except Exception as exc:
        logger.error("Failed to save to Google Sheets: %s", exc)


def _init_occupancy_sheet(occ_sheet, slots: list[str], tables: list[dict]) -> list[list]:
    """Build the 30-day × tables grid and write it in one batch. Returns the written rows."""
    header = ["Date", "Table", "Capacity", "Location"] + slots
    rows = [header]
    today = datetime.now().date()
    for day_offset in range(30):
        date_str = (today + timedelta(days=day_offset)).strftime("%d.%m.%Y")
        for table in tables:
            rows.append(
                [date_str, table["id"], table["capacity"], table["location"]]
                + ["FREE"] * len(slots)
            )
    occ_sheet.clear()
    occ_sheet.update("A1", rows)
    return rows


def update_occupancy_sheet(reservation: dict) -> None:
    """Mark the reserved slot in the Occupancy tab with customer name + ID."""
    try:
        client = _get_client()
        if not client:
            return
        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        try:
            occ_sheet = spreadsheet.worksheet("Occupancy")
        except gspread.exceptions.WorksheetNotFound:
            occ_sheet = spreadsheet.add_worksheet(title="Occupancy", rows=500, cols=30)

        all_values = occ_sheet.get_all_values()

        # Always check the header; initialize if missing or malformed
        if not all_values or not all_values[0] or all_values[0][0] != "Date":
            tables = _load_tables_config()
            all_values = _init_occupancy_sheet(occ_sheet, _OCCUPANCY_SLOTS, tables)

        # Normalise reservation date to DD.MM.YYYY (grid always uses this format)
        res_date = reservation.get("date", "")
        try:
            res_date = datetime.strptime(res_date, "%Y-%m-%d").strftime("%d.%m.%Y")
        except ValueError:
            pass  # already DD.MM.YYYY

        table_id  = reservation.get("table_id", "")
        time_slot = reservation.get("time", "")
        cell_val  = f"{reservation.get('name', '')} ({reservation.get('id', '')})"

        header_row = all_values[0]
        try:
            time_col_idx = header_row.index(time_slot)
        except ValueError:
            logger.warning("Time slot %s not found in Occupancy header", time_slot)
            return

        for row_idx, row in enumerate(all_values[1:], start=2):
            if len(row) > 1 and row[0] == res_date and row[1] == table_id:
                occ_sheet.update_cell(row_idx, time_col_idx + 1, cell_val)
                logger.info("Occupancy updated: %s %s %s → %s", res_date, table_id, time_slot, cell_val)
                return

        logger.warning("Occupancy row not found for %s + %s", res_date, table_id)
    except Exception as exc:
        logger.error("Failed to update Occupancy sheet: %s", exc)


def init_tables_sheet() -> None:
    """Write the Tables tab with the current table config. Called once at startup."""
    client = _get_client()
    if not client:
        return
    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
    except Exception as exc:
        logger.error("Failed to open spreadsheet: %s", exc)
        return

    try:
        t_sheet = spreadsheet.worksheet("Tables")
    except gspread.exceptions.WorksheetNotFound:
        t_sheet = spreadsheet.add_worksheet(title="Tables", rows=20, cols=5)

    tables = _load_tables_config()
    rows = [["Table ID", "Capacity", "Location", "Notes"]]
    for t in tables:
        rows.append([t["id"], t["capacity"], t["location"], t.get("notes", "")])

    for attempt in range(3):
        try:
            t_sheet.clear()
            t_sheet.update("A1", rows)
            logger.info("Tables sheet initialized (%d tables)", len(tables))
            break
        except Exception as exc:
            if attempt < 2:
                logger.warning("Tables sheet write failed (attempt %d): %s", attempt + 1, exc)
                time.sleep(2)
            else:
                logger.error("Failed to init Tables sheet after 3 attempts: %s", exc)
