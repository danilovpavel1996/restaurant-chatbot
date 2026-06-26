"""Google Sheets integration — append reservations to a spreadsheet."""

import json
import logging
import os

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
        ]
        logger.info(f"Appending to Sheets: {row}")
        sheet.append_row(row)
        logger.info("Reservation %s saved to Google Sheets", reservation.get("id"))
    except Exception as exc:
        logger.error("Failed to save to Google Sheets: %s", exc)
