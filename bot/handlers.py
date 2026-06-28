"""All Telegram handlers: /start, message routing, reservation state machine, callbacks."""

import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

import dateparser

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .ai import get_ai_response
from .capacity import (
    find_available_table_from_occupancy,
    find_nearest_available_from_occupancy,
    get_available_slots_by_location,
    get_available_slots_from_occupancy,
)
from .sheets import append_reservation
from .reservations import (
    cancel_reservation,
    create_reservation,
    find_by_id,
    find_by_phone,
    update_reservation,
)
from .utils import (
    format_menu_category,
    format_single_reservation,
    get_hookah_options,
    load_config,
    MENU_CATEGORIES,
)

logger = logging.getLogger(__name__)
config = load_config()

# ── Constants ─────────────────────────────────────────────────────────────────

TIME_SLOTS: list[str] = config["reservations"]["time_slots"]
MAX_PARTY: int = config["reservations"]["max_party_size"]
BOOKING_WINDOW: int = config["reservations"]["booking_window_days"]
PHONE_CONTACT: str = config["contact"]["phone"]
MANAGER_CHAT_ID: str | None = os.getenv("MANAGER_CHAT_ID")

# Monday=0 … Sunday=6 (matches date.weekday())
_WEEKDAYS = {
    "ro": ["Luni", "Marți", "Miercuri", "Joi", "Vineri", "Sâmbătă", "Duminică"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "ru": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"],
}

# Genitive form for Russian ("3 июля"), nominative for RO/EN
_MONTHS = {
    "ro": ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
           "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"],
    "en": ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
    "ru": ["января", "февраля", "марта", "апреля", "мая", "июня",
           "июля", "августа", "сентября", "октября", "ноября", "декабря"],
}

MENU_TRIGGERS = {"menu", "meniu", "меню", "card", "food", "eat", "mâncare", "dishes", "prices", "prețuri"}
RESERVATION_TRIGGERS = {
    "rezervare", "rezerv", "rezervați", "rezerva", "book", "booking",
    "table", "masa", "masă", "reservation", "бронирование", "бронировать",
    "стол", "забронировать", "бронь",
}
HOOKAH_KEYWORDS = {"narghilea", "hookah", "narghile", "narghi", "кальян", "kalyan"}

# ── Per-user in-memory state ───────────────────────────────────────────────────
# {user_id: {state, data, language, language_locked, history, hookah_mentioned}}
_states: dict = {}


def _get_state(user_id: int) -> dict:
    if user_id not in _states:
        _states[user_id] = {
            "state": "idle",
            "data": {},
            "language": "ro",
            "language_set": False,   # True only after explicit lang button press
            "history": [],
            "hookah_mentioned": False,
        }
    return _states[user_id]


def _reset_reservation(state_data: dict) -> None:
    state_data["state"] = "idle"
    state_data["data"] = {}
    state_data["hookah_mentioned"] = False


# ── Localised message strings ──────────────────────────────────────────────────

MESSAGES: dict = {
    "ro": {
        "welcome": (
            "Bun venit la Komodo Lounge Floreasca! 🦎\n\n"
            "Sunt asistentul virtual al restaurantului nostru. Vă pot ajuta cu:\n"
            "🍽 Meniu și prețuri\n"
            "📅 Rezervări de mese\n"
            "🕐 Program și locație\n"
            "🔥 Narghilele\n\n"
            "Alegeți o opțiune sau scrieți întrebarea dumneavoastră:"
        ),
        "start_reservation": "Să facem o rezervare! 📅\n\nCum vă numiți?",
        "ask_name": "Cum vă numiți?",
        "ask_date": "Ce dată doriți?",
        "date_confirm_ask": "Am înțeles: *{date_str}*. Este corect? (da / nu)",
        "date_confirm_retry": "Vă rog introduceți din nou data.",
        "err_date_unparseable": "Nu am înțeles data. Când doriți să veniți?",
        "ask_time": (
            "Ce oră preferați?\nSlot-uri disponibile: {slots}\n\n"
            "⚠️ Bucătăria: 12:00–23:00 | Micul dejun: 10:00–14:00 | Sushi: 12:00–22:30"
        ),
        "ask_party_size": "Câte persoane vor fi la masă? (maxim {max})",
        "ask_phone": "Care este numărul dumneavoastră de telefon?",
        "ask_seating": "Preferați locul *interior* sau *terasă*?",
        "ask_hookah": (
            "Doriți să includeți și o narghilea? 🔥\n\n"
            "Alegeți tipul *(18+ ani)*:\n\n"
            "🕐 Happy Hour Lun–Vin 12:00–18:00: a 2-a narghilea 50% off (293 MDL)"
        ),
        "ask_special_requests": (
            "Aveți cereri speciale?\n"
            "(ex: aranjament ziua de naștere, scaun copil, colț liniștit etc.)\n"
            "Sau scrieți *'nu'* dacă nu aveți."
        ),
        "confirm_prompt": "\n\nConfirmați această rezervare?",
        "confirmed": (
            "✅ Rezervare confirmată!\n\n"
            "ID: {res_id}\n\n{summary}\n\n"
            "Vă așteptăm cu drag! 🐉\n"
            "Pentru modificări contactați-ne la 📞 {phone}"
        ),
        "cancelled_by_user": "Rezervarea a fost anulată. Scrieți oricând dacă doriți să faceți una nouă.",
        "err_invalid_date": "Format invalid. Vă rugăm folosiți ZZ.LL.AAAA (ex: {example}).",
        "err_past_date": "Data introdusă este în trecut. Alegeți o dată viitoare.",
        "err_date_far": "Rezervările se fac cu maxim 30 de zile înainte. Alegeți o dată mai apropiată.",
        "err_invalid_time": "Ora nu este disponibilă. Slot-uri valide: {slots}",
        "time_suggest": "Cel mai apropiat slot disponibil este {time}. Este OK? (da / nu)",
        "err_party_large": "Grupul maxim este de {max} persoane. Introduceți un număr valid.",
        "err_party_invalid": "Introduceți un număr valid de persoane (1–{max}).",
        "err_party_ask_again": "Câți oaspeți vor fi? (maximum {max})",
        "note_sushi": "\n⚠️ Notă: Sushi-ul se comandă doar până la 22:30.",
        "note_kitchen": "\n⚠️ Notă: Bucătăria se închide la 23:00 (după aceea doar băuturi).",
        "hookah_age": "\n⚠️ Serviciul de narghilea este disponibil pentru persoane de 18+ ani.",
        "ask_phone_lookup": "Introduceți numărul de telefon pentru a căuta rezervările:",
        "no_reservations": "Nu am găsit rezervări pentru numărul {phone}.",
        "found_reservations": "Rezervările pentru {phone}:\n\n{list}",
        "ask_cancel_confirm": "Doriți să anulați această rezervare?\n\n{summary}",
        "cancel_success": "❌ Rezervarea *{res_id}* a fost anulată cu succes.",
        "already_cancelled": "Această rezervare este deja anulată.",
        "select_modify_field": "Ce doriți să modificați?",
        "ask_new_date": "Introduceți noua dată (ZZ.LL.AAAA, ex: {example}):",
        "ask_new_time": "Introduceți noua oră. Slot-uri disponibile: {slots}",
        "ask_new_party": "Introduceți noul număr de persoane (1–{max}):",
        "ask_new_special": "Introduceți noile cereri speciale (sau 'nu' pentru niciunul):",
        "modify_success": "✅ Rezervarea *{res_id}* a fost actualizată.",
        "res_not_found": "Rezervarea nu a fost găsită.",
        "err_general": "Îmi pare rău, am întâmpinat o eroare. Contactați-ne la 📞 +40731555558",
    },
    "en": {
        "welcome": (
            "Welcome to Komodo Lounge Floreasca! 🦎\n\n"
            "I'm your virtual assistant. I can help you with:\n"
            "🍽 Menu and prices\n"
            "📅 Table reservations\n"
            "🕐 Opening hours and location\n"
            "🔥 Hookah (Narghilea)\n\n"
            "Choose an option or type your question:"
        ),
        "start_reservation": "Let's make a reservation! 📅\n\nWhat is your name?",
        "ask_name": "What is your name?",
        "ask_date": "What date would you like?",
        "date_confirm_ask": "Got it: *{date_str}*. Is that correct? (yes / no)",
        "date_confirm_retry": "Please enter the date again.",
        "err_date_unparseable": "I didn't quite catch the date. When would you like to come?",
        "ask_time": (
            "What time would you prefer?\nAvailable slots: {slots}\n\n"
            "⚠️ Kitchen: 12:00–23:00 | Breakfast: 10:00–14:00 | Sushi: 12:00–22:30"
        ),
        "ask_party_size": "How many guests? (maximum {max})",
        "ask_phone": "What is your phone number?",
        "ask_seating": "Do you prefer *indoor* or *terrace* seating?",
        "ask_hookah": (
            "Would you like to include a hookah? 🔥\n\n"
            "Choose a type *(18+ only)*:\n\n"
            "🕐 Happy Hour Mon–Fri 12:00–18:00: second hookah 50% off (293 MDL)"
        ),
        "ask_special_requests": (
            "Any special requests?\n"
            "(e.g. birthday setup, high chair, quiet corner, etc.)\n"
            "Or type *'none'* if you have none."
        ),
        "confirm_prompt": "\n\nDo you confirm this reservation?",
        "confirmed": (
            "✅ Reservation confirmed!\n\n"
            "ID: {res_id}\n\n{summary}\n\n"
            "We look forward to welcoming you! 🐉\n"
            "For changes please call us at 📞 {phone}"
        ),
        "cancelled_by_user": "Reservation flow cancelled. Feel free to start a new one anytime.",
        "err_invalid_date": "Invalid format. Please use DD.MM.YYYY (e.g. {example}).",
        "err_past_date": "That date is in the past. Please choose a future date.",
        "err_date_far": "Reservations can be made up to 30 days in advance. Please choose a closer date.",
        "err_invalid_time": "That time slot is not available. Valid slots: {slots}",
        "time_suggest": "The closest available slot is {time}. Is that OK? (yes / no)",
        "err_party_large": "Maximum group size is {max}. Please enter a valid number.",
        "err_party_invalid": "Please enter a valid number of guests (1–{max}).",
        "err_party_ask_again": "How many guests will be joining? (up to {max})",
        "note_sushi": "\n⚠️ Note: Sushi orders must be placed before 22:30.",
        "note_kitchen": "\n⚠️ Note: Kitchen closes at 23:00 (drinks only after that).",
        "hookah_age": "\n⚠️ Hookah service is available for guests aged 18+ only.",
        "ask_phone_lookup": "Please enter your phone number so I can find your reservations:",
        "no_reservations": "No reservations found for phone number {phone}.",
        "found_reservations": "Reservations for {phone}:\n\n{list}",
        "ask_cancel_confirm": "Would you like to cancel this reservation?\n\n{summary}",
        "cancel_success": "❌ Reservation *{res_id}* has been successfully cancelled.",
        "already_cancelled": "This reservation is already cancelled.",
        "select_modify_field": "What would you like to modify?",
        "ask_new_date": "Enter the new date (DD.MM.YYYY, e.g. {example}):",
        "ask_new_time": "Enter the new time. Available slots: {slots}",
        "ask_new_party": "Enter the new number of guests (1–{max}):",
        "ask_new_special": "Enter new special requests (or 'none'):",
        "modify_success": "✅ Reservation *{res_id}* has been updated.",
        "res_not_found": "Reservation not found.",
        "err_general": "I'm sorry, I encountered an error. Please contact us at 📞 +40731555558",
    },
    "ru": {
        "welcome": (
            "Добро пожаловать в Komodo Lounge Floreasca! 🦎\n\n"
            "Я ваш виртуальный помощник. Я могу помочь вам с:\n"
            "🍽 Меню и цены\n"
            "📅 Бронирование столиков\n"
            "🕐 Часы работы и адрес\n"
            "🔥 Кальян\n\n"
            "Выберите опцию или напишите ваш вопрос:"
        ),
        "start_reservation": "Оформляем бронирование! 📅\n\nКак вас зовут?",
        "ask_name": "Как вас зовут?",
        "ask_date": "На какую дату?",
        "date_confirm_ask": "Понял: *{date_str}*. Верно? (да / нет)",
        "date_confirm_retry": "Пожалуйста, введите дату снова.",
        "err_date_unparseable": "Не понял дату. Когда вы хотите прийти?",
        "ask_time": (
            "Какое время предпочитаете?\nДоступные слоты: {slots}\n\n"
            "⚠️ Кухня: 12:00–23:00 | Завтрак: 10:00–14:00 | Суши: 12:00–22:30"
        ),
        "ask_party_size": "Сколько гостей? (максимум {max})",
        "ask_phone": "Ваш номер телефона?",
        "ask_seating": "Предпочитаете место *внутри* или *на террасе*?",
        "ask_hookah": (
            "Хотите заказать кальян? 🔥\n\n"
            "Выберите тип *(18+ лет)*:\n\n"
            "🕐 Happy Hour Пн–Пт 12:00–18:00: второй кальян 50% скидка (293 MDL)"
        ),
        "ask_special_requests": (
            "Есть особые пожелания?\n"
            "(напр. украшение ко дню рождения, детский стул, тихий столик и т.д.)\n"
            "Или напишите *'нет'*, если нет."
        ),
        "confirm_prompt": "\n\nПодтверждаете бронирование?",
        "confirmed": (
            "✅ Бронирование подтверждено!\n\n"
            "ID: {res_id}\n\n{summary}\n\n"
            "Будем рады вас видеть! 🐉\n"
            "Для изменений звоните: 📞 {phone}"
        ),
        "cancelled_by_user": "Бронирование отменено. Начните новое в любое время.",
        "err_invalid_date": "Неверный формат. Используйте ДД.ММ.ГГГГ (напр. {example}).",
        "err_past_date": "Введённая дата уже прошла. Выберите будущую дату.",
        "err_date_far": "Бронирование доступно за 30 дней. Выберите более близкую дату.",
        "err_invalid_time": "Этот слот недоступен. Доступные слоты: {slots}",
        "time_suggest": "Ближайший доступный слот — {time}. Подходит? (да / нет)",
        "err_party_large": "Максимальный размер группы — {max} человек.",
        "err_party_invalid": "Введите корректное число гостей (1–{max}).",
        "err_party_ask_again": "Сколько гостей будет? (максимум {max})",
        "note_sushi": "\n⚠️ Примечание: Суши принимаются до 22:30.",
        "note_kitchen": "\n⚠️ Примечание: Кухня закрывается в 23:00 (после только напитки).",
        "hookah_age": "\n⚠️ Кальян доступен только для гостей 18+ лет.",
        "ask_phone_lookup": "Введите номер телефона для поиска бронирований:",
        "no_reservations": "Бронирования для номера {phone} не найдены.",
        "found_reservations": "Бронирования для {phone}:\n\n{list}",
        "ask_cancel_confirm": "Хотите отменить это бронирование?\n\n{summary}",
        "cancel_success": "❌ Бронирование *{res_id}* успешно отменено.",
        "already_cancelled": "Это бронирование уже отменено.",
        "select_modify_field": "Что вы хотите изменить?",
        "ask_new_date": "Введите новую дату (ДД.ММ.ГГГГ, напр. {example}):",
        "ask_new_time": "Введите новое время. Доступные слоты: {slots}",
        "ask_new_party": "Введите новое количество гостей (1–{max}):",
        "ask_new_special": "Введите новые особые пожелания (или 'нет'):",
        "modify_success": "✅ Бронирование *{res_id}* обновлено.",
        "res_not_found": "Бронирование не найдено.",
        "err_general": "Извините, произошла ошибка. Свяжитесь с нами: 📞 +40731555558",
    },
}


def _msg(lang: str, key: str, **kwargs) -> str:
    """Return a localised message, falling back to Romanian."""
    template = MESSAGES.get(lang, MESSAGES["ro"]).get(key, MESSAGES["ro"].get(key, ""))
    return template.format(**kwargs) if kwargs else template


def _example_date() -> str:
    return (date.today() + timedelta(days=1)).strftime("%d.%m.%Y")


def _slots_str() -> str:
    return ", ".join(TIME_SLOTS)


# ── Button labels (single language per user) ───────────────────────────────────

BUTTON_LABELS: dict = {
    "yes":        {"ro": "✅ Da",            "en": "✅ Yes",          "ru": "✅ Да"},
    "no":         {"ro": "❌ Nu",            "en": "❌ No",           "ru": "❌ Нет"},
    "indoor":     {"ro": "🏠 Interior",      "en": "🏠 Indoor",       "ru": "🏠 Внутри"},
    "terrace":    {"ro": "🌿 Terasă",        "en": "🌿 Terrace",      "ru": "🌿 Терраса"},
    "skip_hookah":{"ro": "⏭ Fără narghilea","en": "⏭ Skip hookah",  "ru": "⏭ Без кальяна"},
    "menu":       {"ro": "🍽 Meniu",         "en": "🍽 Menu",         "ru": "🍽 Меню"},
    "reservation":{"ro": "📅 Rezervare",     "en": "📅 Reservation",  "ru": "📅 Бронирование"},
    "hours":      {"ro": "🕐 Program",       "en": "🕐 Hours",        "ru": "🕐 Часы"},
    "location":   {"ro": "📍 Locație",       "en": "📍 Location",     "ru": "📍 Адрес"},
    "hookah":     {"ro": "🔥 Narghilea",     "en": "🔥 Hookah",       "ru": "🔥 Кальян"},
    "team":       {"ro": "👤 Echipă",        "en": "👤 Speak to team","ru": "👤 Команда"},
}


def get_button_text(key: str, lang: str) -> str:
    return BUTTON_LABELS.get(key, {}).get(lang) or BUTTON_LABELS[key]["en"]


# ── Party size extraction ──────────────────────────────────────────────────────

_WRITTEN_NUMBERS: dict[str, int] = {
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    # Romanian
    "un": 1, "una": 1, "doi": 2, "două": 2, "doua": 2,
    "trei": 3, "patru": 4, "cinci": 5, "șase": 6, "sase": 6,
    "șapte": 7, "sapte": 7, "opt": 8, "nouă": 9, "noua": 9, "zece": 10,
    # Russian
    "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
}


def _extract_party_size(text: str, lang: str) -> Optional[int]:
    """
    Extract a guest count from free text via three layers:
    1. Regex — any digit sequence ("2 people", "just 2")
    2. Written-number word map (all 3 languages)
    3. OpenAI fallback for genuinely ambiguous phrasing
    Returns None only if all layers fail.
    """
    # Layer 1 — digit
    m = re.search(r"\b(\d+)\b", text)
    if m:
        return int(m.group(1))

    # Layer 2 — written word
    lower = text.lower()
    for word, num in _WRITTEN_NUMBERS.items():
        if re.search(rf"\b{re.escape(word)}\b", lower):
            return num

    # Layer 3 — OpenAI
    import os
    from openai import OpenAI
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": (
                f"How many people are mentioned in this text? "
                f"Reply with ONLY a number, nothing else. "
                f"If unclear, reply 'NONE'. Text: '{text}'"
            )}],
            max_tokens=5,
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        if raw.upper() != "NONE":
            return int(raw)
    except Exception as exc:
        logger.warning("OpenAI party size fallback failed: %s", exc)
    return None


# ── Validation helpers ─────────────────────────────────────────────────────────

def _validate_date(text: str) -> tuple[bool, str, Optional[date]]:
    """Strict DD.MM.YYYY parser — kept for the /modify command."""
    try:
        parsed = datetime.strptime(text.strip(), "%d.%m.%Y").date()
    except ValueError:
        return False, "err_invalid_date", None
    today = date.today()
    if parsed < today:
        return False, "err_past_date", None
    if parsed > today + timedelta(days=BOOKING_WINDOW):
        return False, "err_date_far", None
    return True, "", parsed


# ── Date parsing helpers ───────────────────────────────────────────────────────

# Filler words that users add but which break dateparser ("next Monday please")
_FILLER_RE = re.compile(
    r"\b(please|va rog|vă rog|пожалуйста|maybe|perhaps|possibly|"
    r"how about|what about|ce zici de|poate|poate)\b",
    re.IGNORECASE | re.UNICODE,
)

# Relative prefix/suffix words: "next monday" → "monday", "luni viitoare" → "luni"
_STRIP_PREFIX_RE = re.compile(
    r"^(next|this|в следующий|в эту|в этот|следующий|следующую|эту|pe)\s+",
    re.IGNORECASE | re.UNICODE,
)
_STRIP_SUFFIX_RE = re.compile(
    r"\s+(viitoare?|asta|aceasta|viitor)$",
    re.IGNORECASE | re.UNICODE,
)

# dateparser parses most Romanian weekday names but silently fails on "luni" (Monday).
# This map covers the full week so stripping "viitoare" always resolves correctly.
_RO_WEEKDAY_MAP = {
    "luni": 0, "marți": 1, "marti": 1, "miercuri": 2, "joi": 3,
    "vineri": 4, "sâmbătă": 5, "sambata": 5, "sambătă": 5,
    "duminică": 6, "duminica": 6,
}

_DATEPARSER_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "RELATIVE_BASE": datetime.now(),
    "RETURN_AS_TIMEZONE_AWARE": False,
    "DATE_ORDER": "DMY",
    "PREFER_DAY_OF_MONTH": "first",
}

_LANG_CODES = {"ro": ["ro", "en"], "en": ["en"], "ru": ["ru", "en"]}


def _next_weekday(idx: int) -> date:
    """Return the next occurrence of weekday idx (0 = Monday) from today."""
    today = date.today()
    days_ahead = idx - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def _pin_year(result: date) -> date:
    """Force current year; advance to next year if the date has already passed."""
    today = date.today()
    try:
        pinned = result.replace(year=today.year)
    except ValueError:
        pinned = result.replace(year=today.year, day=28)  # Feb 29 in non-leap year
    if pinned < today:
        try:
            pinned = pinned.replace(year=today.year + 1)
        except ValueError:
            pinned = pinned.replace(year=today.year + 1, day=28)
    return pinned


def _parse_date_openai(text: str) -> Optional[date]:
    """
    Last-resort synchronous OpenAI call to extract a date from free text.
    Uses the sync client to keep _parse_date_smart a plain function.
    Returns a pinned date or None.
    """
    import os
    from openai import OpenAI
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        today = date.today().isoformat()
        prompt = (
            f"Extract the date from this text. Today is {today}. "
            f"Reply with ONLY a date in format YYYY-MM-DD, nothing else. "
            f"If you cannot find a date, reply with 'NONE'. Text: '{text}'"
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        if raw.upper() == "NONE":
            return None
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
        return _pin_year(parsed)
    except Exception as exc:
        logger.warning("OpenAI date fallback failed: %s", exc)
        return None


def _try_dateparser(text: str, lang: str) -> Optional[date]:
    """Run dateparser on a single string. Returns a pinned date or None."""
    # Romanian weekday fallback — dateparser silently fails on "luni"
    if lang == "ro" and text.lower() in _RO_WEEKDAY_MAP:
        return _next_weekday(_RO_WEEKDAY_MAP[text.lower()])
    parsed_dt = dateparser.parse(
        text,
        languages=_LANG_CODES.get(lang, ["ro", "en"]),
        settings=_DATEPARSER_SETTINGS,
    )
    return _pin_year(parsed_dt.date()) if parsed_dt else None


def _parse_date_smart(text: str, lang: str) -> Optional[date]:
    """
    Parse natural-language date input through three layers:
    1. dateparser on the cleaned/stripped text variants
    2. OpenAI GPT-4o-mini as a last-resort extractor
    Returns None only if all layers fail.
    """
    text = text.strip()

    # Layer 1a — strip filler words, then relative modifiers, build attempt list
    cleaned = _FILLER_RE.sub("", text).strip().rstrip(".,!?")
    cleaned = _STRIP_SUFFIX_RE.sub("", _STRIP_PREFIX_RE.sub("", cleaned)).strip()

    seen: set[str] = set()
    attempts: list[str] = []
    for candidate in [cleaned, text]:  # cleaned first; original as fallback
        if candidate and candidate not in seen:
            seen.add(candidate)
            attempts.append(candidate)

    for attempt in attempts:
        result = _try_dateparser(attempt, lang)
        if result is not None:
            return result

    # Layer 2 — OpenAI fallback for genuinely ambiguous free-text
    return _parse_date_openai(text)


def _check_date_range(d: date) -> str:
    """Return an error message key if the date is out of the booking window, else ''."""
    today = date.today()
    if d < today:
        return "err_past_date"
    if d > today + timedelta(days=BOOKING_WINDOW):
        return "err_date_far"
    return ""


def _date_display(d: date, lang: str) -> str:
    """Format a date as 'Weekday, day month' in the given language."""
    weekday = _WEEKDAYS[lang][d.weekday()]
    month = _MONTHS[lang][d.month - 1]
    if lang == "en":
        return f"{weekday}, {month} {d.day}"
    return f"{weekday}, {d.day} {month}"  # RO and RU both use "Weekday, day month"


def _validate_time(text: str) -> tuple[bool, str]:
    """Returns (ok, normalised_time_or_empty). Strict HH:MM, used by /modify."""
    text = text.strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if m:
        normalised = f"{int(m.group(1)):02d}:{m.group(2)}"
        if normalised in TIME_SLOTS:
            return True, normalised
    return False, ""


def _time_to_minutes(t: str) -> int:
    h, mn = t.split(":")
    return int(h) * 60 + int(mn)


def _closest_slot(time_str: str) -> str:
    target = _time_to_minutes(time_str)
    return min(TIME_SLOTS, key=lambda s: abs(_time_to_minutes(s) - target))


def _parse_time_natural(text: str) -> Optional[str]:
    """
    Parse natural-language time input into HH:MM.
    Returns None if completely unparseable.
    """
    text = text.strip().lower()

    # Strip locale-specific prefixes
    text = re.sub(
        r"^(în jurul orei|în jur de|în jurul|ora|around|about|около|в|at|la|pe la|pe)\s+",
        "", text, flags=re.IGNORECASE | re.UNICODE,
    ).strip()
    # Strip locale-specific suffixes
    text = re.sub(
        r"\s+(часов|часа|ч\.?|ore|o'clock)$", "", text, flags=re.IGNORECASE,
    ).strip()

    # "half past N"
    m = re.match(r"^half\s+past\s+(\d{1,2})$", text)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:30"

    # "N am" / "N:MM am" / "N pm" / "N:MM pm"
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?$", text)
    if m:
        h, mn, period = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if period == "p" and h != 12:
            h += 12
        elif period == "a" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return f"{h:02d}:{mn:02d}"
        return None

    # "HH:MM"
    m = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return f"{h:02d}:{mn:02d}"
        return None

    # Bare number or "Nh" — treat as HH:00
    m = re.match(r"^(\d{1,2})h?$", text)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"
        return None

    return None


# ── Inline keyboard builders ───────────────────────────────────────────────────

def _lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        InlineKeyboardButton("🇷🇴 Română",  callback_data="lang_ro"),
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
    ]])


def _main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    keys = ["menu", "reservation", "hours", "location", "hookah", "team"]
    cbs  = ["menu_meniu", "menu_rezervare", "menu_program",
            "menu_locatie", "menu_narghilea", "menu_echipa"]
    btns = [InlineKeyboardButton(get_button_text(k, lang), callback_data=cb)
            for k, cb in zip(keys, cbs)]
    return InlineKeyboardMarkup([btns[0:2], btns[2:4], btns[4:6]])


def _menu_category_keyboard(lang: str) -> InlineKeyboardMarkup:
    prompt = {"ro": "Ce doriți să explorați? 🍽",
              "en": "What would you like to explore? 🍽",
              "ru": "Что хотите посмотреть? 🍽"}.get(lang, "What would you like to explore? 🍽")
    buttons = []
    for key, emoji, labels in MENU_CATEGORIES:
        label = labels.get(lang, labels["en"])
        buttons.append(InlineKeyboardButton(f"{emoji} {label}", callback_data=f"menu_cat_{key}"))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return prompt, InlineKeyboardMarkup(rows)


def _menu_nav_keyboard(lang: str) -> InlineKeyboardMarkup:
    back  = {"ro": "🔙 Înapoi la meniu", "en": "🔙 Back to menu",     "ru": "🔙 Назад к меню"}.get(lang)
    res   = {"ro": "📅 Rezervă o masă",  "en": "📅 Reserve a table",  "ru": "📅 Забронировать стол"}.get(lang)
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(back, callback_data="menu_back"),
        InlineKeyboardButton(res,  callback_data="start_reservation"),
    ]])


def _seating_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(get_button_text("indoor",   lang), callback_data="seating_indoor"),
        InlineKeyboardButton(get_button_text("terrace",  lang), callback_data="seating_terrace"),
    ]])


def _slots_keyboard(slots: list[str]) -> InlineKeyboardMarkup:
    rows: list[list] = []
    row: list = []
    for slot in slots:
        row.append(InlineKeyboardButton(slot, callback_data=f"slot_{slot}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _hookah_keyboard(lang: str) -> InlineKeyboardMarkup:
    options = get_hookah_options(lang, config)
    currency = config["hookah"]["currency"]
    buttons = [
        [InlineKeyboardButton(f"{o['name']} — {o['price']} {currency}", callback_data=f"hookah_{o['id']}")]
        for o in options
    ]
    buttons.append([InlineKeyboardButton(get_button_text("skip_hookah", lang), callback_data="hookah_skip")])
    return InlineKeyboardMarkup(buttons)


def _confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(get_button_text("yes", lang), callback_data="confirm_yes"),
        InlineKeyboardButton(get_button_text("no",  lang), callback_data="confirm_no"),
    ]])


def _cancel_confirm_keyboard(res_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(get_button_text("yes", lang), callback_data=f"cancel_yes_{res_id}"),
        InlineKeyboardButton(get_button_text("no",  lang), callback_data="cancel_no"),
    ]])


def _modify_field_keyboard(lang: str) -> InlineKeyboardMarkup:
    labels = {
        "ro": ("📅 Dată", "⏰ Oră", "👥 Persoane", "📝 Cereri speciale"),
        "en": ("📅 Date", "⏰ Time", "👥 Guests",   "📝 Special requests"),
        "ru": ("📅 Дата", "⏰ Время", "👥 Гостей",  "📝 Особые пожелания"),
    }.get(lang, ("📅 Dată", "⏰ Oră", "👥 Persoane", "📝 Cereri speciale"))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(labels[0], callback_data="modify_field_date"),
         InlineKeyboardButton(labels[1], callback_data="modify_field_time")],
        [InlineKeyboardButton(labels[2], callback_data="modify_field_party_size"),
         InlineKeyboardButton(labels[3], callback_data="modify_field_special_requests")],
    ])


# ── Summary formatter ──────────────────────────────────────────────────────────

def _format_summary(data: dict, lang: str) -> str:
    seating = data.get("seating_preference", "")
    seating_text = {
        "indoor":  {"ro": "Interior", "en": "Indoor",  "ru": "Внутри"},
        "terrace": {"ro": "Terasă",   "en": "Terrace", "ru": "Терраса"},
    }.get(seating, {}).get(lang, seating)

    hookah_line = ""
    if data.get("hookah"):
        label = {"ro": "Narghilea", "en": "Hookah", "ru": "Кальян"}[lang]
        hookah_line = f"\n• {label}: {data['hookah']}"

    special = data.get("special_requests") or {"ro": "Fără", "en": "None", "ru": "Нет"}[lang]

    table_line = ""
    if data.get("table_id"):
        tid = data["table_id"]
        cap = data.get("table_capacity", "")
        loc = data.get("table_location", "")
        table_line = {
            "en": f"\n• Table: {tid} (seats {cap}, {loc})",
            "ro": f"\n• Masă: {tid} ({cap} locuri, {loc})",
            "ru": f"\n• Стол: {tid} ({cap} места, {loc})",
        }.get(lang, f"\n• Table: {tid}")

    if lang == "en":
        return (
            f"📋 Reservation summary:\n"
            f"• Name: {data.get('name', '')}\n"
            f"• Date: {data.get('date', '')}\n"
            f"• Time: {data.get('time', '')}\n"
            f"• Guests: {data.get('party_size', '')}\n"
            f"• Phone: {data.get('phone', '')}\n"
            f"• Seating: {seating_text}{hookah_line}{table_line}\n"
            f"• Special requests: {special}"
        )
    elif lang == "ru":
        return (
            f"📋 Сводка бронирования:\n"
            f"• Имя: {data.get('name', '')}\n"
            f"• Дата: {data.get('date', '')}\n"
            f"• Время: {data.get('time', '')}\n"
            f"• Гостей: {data.get('party_size', '')}\n"
            f"• Телефон: {data.get('phone', '')}\n"
            f"• Место: {seating_text}{hookah_line}{table_line}\n"
            f"• Особые пожелания: {special}"
        )
    else:
        return (
            f"📋 Sumar rezervare:\n"
            f"• Nume: {data.get('name', '')}\n"
            f"• Data: {data.get('date', '')}\n"
            f"• Ora: {data.get('time', '')}\n"
            f"• Persoane: {data.get('party_size', '')}\n"
            f"• Telefon: {data.get('phone', '')}\n"
            f"• Loc: {seating_text}{hookah_line}{table_line}\n"
            f"• Cereri speciale: {special}"
        )


# ── Shared reservation flow helpers ───────────────────────────────────────────

async def _after_seating(target, state_data: dict, seating: str) -> None:
    """Advance state after seating is chosen. Hookah only for terrace; indoor skips to phone."""
    lang = state_data["language"]
    state_data["data"]["seating_preference"] = seating
    if seating == "terrace":
        state_data["state"] = "awaiting_hookah"
        hookah_msg = _msg(lang, "ask_hookah") + _msg(lang, "hookah_age")
        await target.reply_text(hookah_msg, reply_markup=_hookah_keyboard(lang))
    else:
        state_data["state"] = "awaiting_phone"
        await target.reply_text(_msg(lang, "ask_phone"))


async def _after_hookah(target, state_data: dict, hookah_name: Optional[str]) -> None:
    """Advance state after hookah choice; hookah_name is None when skipped."""
    lang = state_data["language"]
    state_data["data"]["hookah"] = hookah_name
    state_data["state"] = "awaiting_phone"
    await target.reply_text(_msg(lang, "ask_phone"))


async def _notify_manager(context: ContextTypes.DEFAULT_TYPE, reservation: dict) -> None:
    if not MANAGER_CHAT_ID:
        return
    msg = (
        f"🔔 New Reservation — {reservation['id']}\n\n"
        f"👤 Name: {reservation['name']}\n"
        f"📅 Date: {reservation['date']}\n"
        f"🕐 Time: {reservation['time']}\n"
        f"👥 Guests: {reservation['party_size']}\n"
        f"📞 Phone: {reservation['phone']}\n"
        f"🪑 Seating: {reservation['seating_preference']}\n"
        f"🪑 Table: {reservation.get('table_id', 'TBD')}\n"
        f"🔥 Hookah: {reservation.get('hookah') or 'None'}\n"
        f"📝 Special requests: {reservation.get('special_requests') or 'None'}\n"
        f"🕒 Booked at: {reservation['created_at']}"
    )
    try:
        await context.bot.send_message(
            chat_id=MANAGER_CHAT_ID,
            text=msg,
        )
    except Exception as exc:
        logger.error("Failed to notify manager: %s", exc)


async def _do_confirm(target, context: ContextTypes.DEFAULT_TYPE, state_data: dict) -> None:
    """Create reservation and send confirmation."""
    lang = state_data["language"]
    data = dict(state_data["data"])

    # Assign table before saving so it ends up in the JSON record in one write
    seating_pref = data.get("seating_preference", "")
    location = "terrace" if "terrace" in seating_pref else "indoor"
    table = find_available_table_from_occupancy(data["date"], data["time"], data["party_size"], location)
    if table:
        data["table_id"]       = table["id"]
        data["table_capacity"] = table["capacity"]
        data["table_location"] = table["location"]
    else:
        data["table_id"] = "TBD"

    try:
        res_id = create_reservation(data)
    except Exception as exc:
        logger.error("Failed to save reservation: %s", exc)
        await target.reply_text(_msg(lang, "err_general"))
        return

    reservation = find_by_id(res_id)
    _reset_reservation(state_data)
    summary = _format_summary(data, lang)
    text = _msg(lang, "confirmed", res_id=res_id, summary=summary, phone=PHONE_CONTACT)
    await target.reply_text(text)
    if reservation:
        await _notify_manager(context, reservation)
        append_reservation(reservation)


def _nearby_slots(available: list[str], requested_time: str, n_each: int = 2) -> list[str]:
    """Return up to n_each slots before + exact match (if present) + n_each slots after, capped at 4."""
    def _mins(t: str) -> int:
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    req = _mins(requested_time)
    before = [s for s in available if _mins(s) < req][-n_each:]
    exact  = [s for s in available if s == requested_time]
    after  = [s for s in available if _mins(s) > req][:n_each]
    return (before + exact + after)[:4]


def _picker_header(lang: str, requested_time: str, indoor_ok: bool, terrace_ok: bool) -> str:
    """Build the context-aware message shown above the availability picker."""
    if not indoor_ok and not terrace_ok:
        return {
            "ro": f"Ne pare rău, atât interiorul cât și terasa sunt ocupate la {requested_time}. Iată cele mai apropiate opțiuni:",
            "en": f"Sorry, both indoor and terrace are fully booked at {requested_time}. Here are the nearest available slots:",
            "ru": f"К сожалению, и зал, и терраса заняты в {requested_time}. Вот ближайшие доступные варианты:",
        }.get(lang, f"Sorry, both locations are fully booked at {requested_time}. Here are the nearest available slots:")
    if not indoor_ok:
        loc = {"ro": "interiorul", "en": "the indoor area", "ru": "зал"}.get(lang, "the indoor area")
        return {
            "ro": f"Ne pare rău, {loc} este complet ocupat la {requested_time}. Iată cele mai apropiate opțiuni disponibile — alegeți ora și locul preferat:",
            "en": f"Sorry, {loc} is fully booked at {requested_time}. Here are the nearest available slots — pick your preferred time and seating:",
            "ru": f"К сожалению, {loc} полностью занят в {requested_time}. Вот ближайшие доступные варианты — выберите удобное время и место:",
        }.get(lang)
    # not terrace_ok
    loc = {"ro": "terasa", "en": "the terrace", "ru": "терраса"}.get(lang, "the terrace")
    return {
        "ro": f"Ne pare rău, {loc} este complet ocupată la {requested_time}. Iată cele mai apropiate opțiuni disponibile — alegeți ora și locul preferat:",
        "en": f"Sorry, {loc} is fully booked at {requested_time}. Here are the nearest available slots — pick your preferred time and seating:",
        "ru": f"К сожалению, {loc} полностью занята в {requested_time}. Вот ближайшие доступные варианты — выберите удобное время и место:",
    }.get(lang)


def _build_availability_picker(
    date: str,
    party_size: int,
    requested_time: str,
    lang: str,
    indoor_ok: bool = False,
    terrace_ok: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Build the two-column availability picker for when at least one location is fully
    booked at the requested time.  Returns (message_text, keyboard).
    indoor_ok / terrace_ok describe the *requested* time's availability and are used
    only for the header message; the keyboard is always built from live occupancy data.
    """
    indoor_slots  = get_available_slots_from_occupancy(date, party_size, "indoor")
    terrace_slots = get_available_slots_from_occupancy(date, party_size, "terrace")

    indoor_picks  = _nearby_slots(indoor_slots,  requested_time)
    terrace_picks = _nearby_slots(terrace_slots, requested_time)

    # Column header row (non-clickable labels)
    col_indoor  = {"ro": "🏠 Interior", "en": "🏠 Indoor",  "ru": "🏠 Зал"}.get(lang,     "🏠 Indoor")
    col_terrace = {"ro": "🌿 Terasă",   "en": "🌿 Terrace", "ru": "🌿 Терраса"}.get(lang, "🌿 Terrace")
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(col_indoor,  callback_data="noop"),
        InlineKeyboardButton(col_terrace, callback_data="noop"),
    ]]

    # Slot rows: up to 4, always two columns, "—" fills an empty cell
    max_len = max(len(indoor_picks), len(terrace_picks), 1)
    for i in range(min(max_len, 4)):
        i_time = indoor_picks[i]  if i < len(indoor_picks)  else None
        t_time = terrace_picks[i] if i < len(terrace_picks) else None
        rows.append([
            InlineKeyboardButton(i_time if i_time else "—",
                                 callback_data=f"pick_indoor_{i_time}" if i_time else "noop"),
            InlineKeyboardButton(t_time if t_time else "—",
                                 callback_data=f"pick_terrace_{t_time}" if t_time else "noop"),
        ])

    header = _picker_header(lang, requested_time, indoor_ok, terrace_ok)
    return header, InlineKeyboardMarkup(rows)


async def _show_seating_prompt(
    target, state_data: dict, indoor_ok: bool = True, terrace_ok: bool = True
) -> None:
    """Show [Indoor] [Terrace] buttons. If one location is unavailable at the chosen time,
    prepend a warning note — but always show both buttons so the user can still pick either."""
    lang = state_data["language"]
    chosen_time = state_data["data"].get("time", "")

    if not terrace_ok:
        note = {
            "ro": f"⚠️ Notă: terasa este complet ocupată la {chosen_time}.",
            "en": f"⚠️ Note: the terrace is fully booked at {chosen_time}.",
            "ru": f"⚠️ Примечание: терраса полностью занята в {chosen_time}.",
        }.get(lang)
    elif not indoor_ok:
        note = {
            "ro": f"⚠️ Notă: interiorul este complet ocupat la {chosen_time}.",
            "en": f"⚠️ Note: the indoor area is fully booked at {chosen_time}.",
            "ru": f"⚠️ Примечание: зал полностью занят в {chosen_time}.",
        }.get(lang)
    else:
        note = None

    ask_seating = {
        "ro": "Preferați locul interior sau terasă?",
        "en": "Do you prefer indoor or terrace seating?",
        "ru": "Предпочитаете место внутри или на террасе?",
    }.get(lang, "Do you prefer indoor or terrace seating?")

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(get_button_text("indoor",  lang), callback_data="seating_indoor"),
        InlineKeyboardButton(get_button_text("terrace", lang), callback_data="seating_terrace"),
    ]])
    full_text = f"{note}\n{ask_seating}" if note else ask_seating
    state_data["state"] = "awaiting_seating"
    await target.reply_text(full_text, reply_markup=keyboard)


# ── Reservation state machine ──────────────────────────────────────────────────

async def _handle_reservation_text(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, state_data: dict, text: str
) -> None:
    msg = update.message
    lang = state_data["language"]
    state = state_data["state"]
    data = state_data["data"]
    text = text.strip()

    # Track hookah mentions throughout the flow
    if any(kw in text.lower() for kw in HOOKAH_KEYWORDS):
        state_data["hookah_mentioned"] = True

    if state == "awaiting_name":
        if len(text) < 2:
            await msg.reply_text(_msg(lang, "ask_name"))
            return
        data["name"] = text
        state_data["state"] = "awaiting_date"
        await msg.reply_text(_msg(lang, "ask_date", example=_example_date()))

    elif state == "awaiting_date":
        parsed = _parse_date_smart(text, lang)
        if parsed is None:
            await msg.reply_text(_msg(lang, "err_date_unparseable"))
            return
        data["_pending_date"] = parsed.isoformat()
        state_data["state"] = "awaiting_date_confirmation"
        await msg.reply_text(
            _msg(lang, "date_confirm_ask", date_str=_date_display(parsed, lang)),
            parse_mode="Markdown",
        )

    elif state == "awaiting_date_confirmation":
        lower = text.lower()
        if any(w in lower for w in ["da", "yes", "да", "d", "y", "correct", "corect", "верно", "right", "ok"]):
            pending = date.fromisoformat(data.pop("_pending_date"))
            err_key = _check_date_range(pending)
            if err_key:
                state_data["state"] = "awaiting_date"
                await msg.reply_text(_msg(lang, err_key) + "\n" + _msg(lang, "date_confirm_retry"))
            else:
                data["date"] = pending.strftime("%d.%m.%Y")
                state_data["state"] = "awaiting_party_size"
                await msg.reply_text(_msg(lang, "ask_party_size", max=MAX_PARTY))
        elif any(w in lower for w in ["nu", "no", "нет", "n", "wrong", "greșit", "неверно"]):
            data.pop("_pending_date", None)
            state_data["state"] = "awaiting_date"
            await msg.reply_text(_msg(lang, "date_confirm_retry"))
        else:
            # Unrecognised reply — re-show the confirmation
            date_str = _date_display(date.fromisoformat(data["_pending_date"]), lang)
            await msg.reply_text(
                _msg(lang, "date_confirm_ask", date_str=date_str),
                parse_mode="Markdown",
            )

    elif state == "awaiting_time":
        slots_by_loc    = data.get("slots_by_location", {})
        available_slots = slots_by_loc.get("any") or TIME_SLOTS
        ask_time_text   = {
            "ro": "Ce oră preferați?",
            "en": "What time would you prefer?",
            "ru": "Какое время вы предпочитаете?",
        }.get(lang, "What time would you prefer?")

        normalised = _parse_time_natural(text)
        if normalised is None:
            await msg.reply_text(ask_time_text, reply_markup=_slots_keyboard(available_slots))
            return

        if normalised in available_slots:
            indoor_ok  = normalised in slots_by_loc.get("indoor",  [])
            terrace_ok = normalised in slots_by_loc.get("terrace", [])
            data["time"] = normalised
            notes = ""
            if normalised >= "22:30":
                notes += _msg(lang, "note_sushi")
            if normalised >= "23:00":
                notes += _msg(lang, "note_kitchen")
            if notes:
                await msg.reply_text(notes.strip())
            await _show_seating_prompt(msg, state_data, indoor_ok=indoor_ok, terrace_ok=terrace_ok)
        else:
            # Time typed but not in any free slot — both locations unavailable at that time
            picker_text, picker_kb = _build_availability_picker(
                data.get("date", ""), data.get("party_size", 1), normalised or "12:00", lang,
                indoor_ok=False, terrace_ok=False,
            )
            # Check if there are any slots at all
            any_slots = slots_by_loc.get("any") or []
            if not any_slots:
                no_slots_msg = {
                    "ro": "Ne pare rău, nu mai sunt locuri disponibile în acea zi.",
                    "en": "Sorry, no more slots available that day for your party size.",
                    "ru": "К сожалению, свободных столиков на этот день больше нет.",
                }.get(lang, "Sorry, no slots available.")
                await msg.reply_text(no_slots_msg)
                state_data["state"] = "awaiting_date"
                data.pop("date", None)
                data.pop("slots_by_location", None)
                return
            state_data["state"] = "awaiting_time_confirmation"
            await msg.reply_text(picker_text, reply_markup=picker_kb)

    elif state == "awaiting_time_confirmation":
        # User should interact via buttons; any text sends them back to the time keyboard
        slots_by_loc    = data.get("slots_by_location", {})
        available_slots = slots_by_loc.get("any") or TIME_SLOTS
        ask_time_text   = {
            "ro": "Vă rugăm să selectați un slot disponibil:",
            "en": "Please select an available time slot:",
            "ru": "Пожалуйста, выберите доступный слот:",
        }.get(lang, "Please select an available time slot:")
        state_data["state"] = "awaiting_time"
        await msg.reply_text(ask_time_text, reply_markup=_slots_keyboard(available_slots))

    elif state == "awaiting_party_size":
        size = _extract_party_size(text, lang)
        if size is None:
            await msg.reply_text(_msg(lang, "err_party_ask_again", max=MAX_PARTY))
            return
        if size < 1 or size > MAX_PARTY:
            await msg.reply_text(_msg(lang, "err_party_large", max=MAX_PARTY))
            return
        data["party_size"] = size

        slots_by_loc = get_available_slots_by_location(data.get("date", ""), size)
        if not slots_by_loc.get("any"):
            no_tables_msg = {
                "ro": f"Ne pare rău, nu mai avem mese disponibile pentru {size} persoane în acea zi. Vă rugăm să alegeți altă dată.",
                "en": f"Sorry, we have no available tables for {size} guests on that date. Please choose a different date.",
                "ru": f"К сожалению, на эту дату нет свободных столиков для {size} гостей. Пожалуйста, выберите другую дату.",
            }.get(lang, f"Sorry, no tables available for {size} guests on that date.")
            await msg.reply_text(no_tables_msg)
            state_data["state"] = "awaiting_date"
            data.pop("date", None)
            data.pop("party_size", None)
            return

        data["slots_by_location"] = slots_by_loc
        state_data["state"] = "awaiting_time"
        ask_time_text = {
            "ro": "Ce oră preferați?",
            "en": "What time would you prefer?",
            "ru": "Какое время вы предпочитаете?",
        }.get(lang, "What time would you prefer?")
        await msg.reply_text(ask_time_text, reply_markup=_slots_keyboard(slots_by_loc["any"]))

    elif state == "awaiting_phone":
        digits = re.sub(r"\D", "", text)
        if len(digits) < 6:
            phone_err = {
                "ro": "Vă rugăm introduceți un număr de telefon valid.",
                "en": "Please enter a valid phone number.",
                "ru": "Пожалуйста, введите корректный номер телефона.",
            }.get(lang, "Please enter a valid phone number.")
            await msg.reply_text(phone_err)
            return
        data["phone"] = text
        state_data["state"] = "awaiting_special_requests"
        await msg.reply_text(_msg(lang, "ask_special_requests"), parse_mode="Markdown")

    elif state == "awaiting_seating":
        lower = text.lower()
        if any(w in lower for w in ["interior", "indoor", "внутри", "зал", "внут"]):
            chosen_loc = "indoor"
        elif any(w in lower for w in ["terasa", "terasă", "terrace", "терраса", "улица", "откры"]):
            chosen_loc = "terrace"
        else:
            await _show_seating_prompt(msg, state_data)
            return

        slots_by_loc = data.get("slots_by_location", {})
        chosen_time  = data.get("time", "")
        loc_ok = not slots_by_loc or chosen_time in slots_by_loc.get(chosen_loc, [])
        if loc_ok:
            await _after_seating(msg, state_data, chosen_loc)
        else:
            picker_text, picker_kb = _build_availability_picker(
                data.get("date", ""), data.get("party_size", 1), chosen_time, lang,
                indoor_ok=(chosen_loc != "indoor"),
                terrace_ok=(chosen_loc != "terrace"),
            )
            state_data["state"] = "awaiting_time_confirmation"
            await msg.reply_text(picker_text, reply_markup=picker_kb)

    elif state == "awaiting_hookah":
        lower = text.lower()
        if any(w in lower for w in ["skip", "fara", "fără", "nu", "no", "нет", "без", "пропустить"]):
            await _after_hookah(msg, state_data, None)
        elif any(w in lower for w in ["clasic", "classic", "класс"]):
            await _after_hookah(msg, state_data, "Narghilea Clasică — 585 MDL")
        elif "cocktail" in lower:
            await _after_hookah(msg, state_data, "Cocktail Vase — 975 MDL")
        elif any(w in lower for w in ["premium", "fruit", "фрукт"]):
            await _after_hookah(msg, state_data, "Premium (fruit bowl) — 1365 MDL")
        else:
            await msg.reply_text(_msg(lang, "ask_hookah"), parse_mode="Markdown",
                                 reply_markup=_hookah_keyboard(lang))

    elif state == "awaiting_special_requests":
        if text.lower().strip() in {"nu", "no", "нет", "none", "nope", "-", "n/a", "fără", "без", "nu am", "no am"}:
            data["special_requests"] = ""
        else:
            data["special_requests"] = text
        state_data["state"] = "awaiting_confirmation"
        summary = _format_summary(data, lang)
        await msg.reply_text(
            summary + _msg(lang, "confirm_prompt"),
            reply_markup=_confirm_keyboard(lang),
        )

    elif state == "awaiting_confirmation":
        lower = text.lower()
        if any(w in lower for w in ["da", "yes", "да", "ok", "y", "d", "confirm"]):
            await _do_confirm(msg, ctx, state_data)
        elif any(w in lower for w in ["nu", "no", "нет", "n", "cancel", "anulare"]):
            _reset_reservation(state_data)
            await msg.reply_text(_msg(lang, "cancelled_by_user"))
        else:
            summary = _format_summary(data, lang)
            await msg.reply_text(
                summary + _msg(lang, "confirm_prompt"),
                reply_markup=_confirm_keyboard(lang),
            )


# ── /myreservation, /cancel, /modify sub-flows (text phase) ───────────────────

async def _handle_mr_phone(update: Update, _ctx, state_data: dict, text: str) -> None:
    lang = state_data["language"]
    phone = text.strip()
    results = find_by_phone(phone)
    state_data["state"] = "idle"
    if not results:
        await update.message.reply_text(_msg(lang, "no_reservations", phone=phone))
        return
    formatted = "\n\n".join(format_single_reservation(r, lang) for r in results)
    await update.message.reply_text(
        _msg(lang, "found_reservations", phone=phone, list=formatted), parse_mode="Markdown"
    )


async def _handle_cancel_phone(update: Update, _ctx, state_data: dict, text: str) -> None:
    lang = state_data["language"]
    phone = text.strip()
    results = [r for r in find_by_phone(phone) if r.get("status") != "cancelled"]
    state_data["state"] = "idle"
    if not results:
        await update.message.reply_text(_msg(lang, "no_reservations", phone=phone))
        return
    for res in results:
        summary = format_single_reservation(res, lang)
        await update.message.reply_text(
            _msg(lang, "ask_cancel_confirm", summary=summary),
            parse_mode="Markdown",
            reply_markup=_cancel_confirm_keyboard(res["id"], lang),
        )


async def _handle_modify_phone(update: Update, _ctx, state_data: dict, text: str) -> None:
    lang = state_data["language"]
    phone = text.strip()
    results = [r for r in find_by_phone(phone) if r.get("status") != "cancelled"]
    if not results:
        state_data["state"] = "idle"
        await update.message.reply_text(_msg(lang, "no_reservations", phone=phone))
        return
    # Take the first active reservation (most demos have one per phone)
    res = results[0]
    state_data["data"]["modify_res_id"] = res["id"]
    state_data["state"] = "modify_awaiting_field"
    summary = format_single_reservation(res, lang)
    await update.message.reply_text(
        summary + "\n\n" + _msg(lang, "select_modify_field"),
        parse_mode="Markdown",
        reply_markup=_modify_field_keyboard(lang),
    )


async def _handle_modify_value(update: Update, _ctx, state_data: dict, text: str) -> None:
    lang = state_data["language"]
    field = state_data["data"].get("modify_field")
    res_id = state_data["data"].get("modify_res_id")
    text = text.strip()

    if field == "date":
        ok, err_key, parsed = _validate_date(text)
        if not ok:
            await update.message.reply_text(_msg(lang, err_key, example=_example_date()))
            return
        update_reservation(res_id, {"date": parsed.strftime("%d.%m.%Y")})

    elif field == "time":
        ok, normalised = _validate_time(text)
        if not ok:
            await update.message.reply_text(_msg(lang, "err_invalid_time", slots=_slots_str()))
            return
        update_reservation(res_id, {"time": normalised})

    elif field == "party_size":
        try:
            size = int(text)
        except ValueError:
            await update.message.reply_text(_msg(lang, "err_party_invalid", max=MAX_PARTY))
            return
        if size < 1 or size > MAX_PARTY:
            await update.message.reply_text(_msg(lang, "err_party_large", max=MAX_PARTY))
            return
        update_reservation(res_id, {"party_size": size})

    elif field == "special_requests":
        special = "" if text.lower() in {"nu", "no", "нет", "none", "-"} else text
        update_reservation(res_id, {"special_requests": special})

    state_data["state"] = "idle"
    state_data["data"] = {}
    await update.message.reply_text(_msg(lang, "modify_success", res_id=res_id), parse_mode="Markdown")


# ── AI free-form mode ──────────────────────────────────────────────────────────

async def _handle_ai(update: Update, _ctx, state_data: dict, text: str) -> None:
    lang = state_data["language"]
    history = state_data["history"]
    try:
        reply = await get_ai_response(text, config, lang, history)
    except Exception as exc:
        logger.error("AI handler error: %s", exc)
        reply = _msg(lang, "err_general")

    # Maintain rolling conversation history
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    if len(history) > 20:
        state_data["history"] = history[-20:]

    # effective_message works for both plain messages and callback query contexts
    await update.effective_message.reply_text(reply)


# ── Public command handlers ────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    state_data = _get_state(user_id)
    # Reset any in-progress flow and clear language so selection is shown fresh
    _reset_reservation(state_data)
    state_data["state"] = "idle"
    state_data["language_set"] = False
    await update.message.reply_text(
        "Please select your language / Selectați limba / Пожалуйста, выберите язык:",
        reply_markup=_lang_keyboard(),
    )


async def myreservation_command(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    state_data = _get_state(user_id)
    lang = state_data["language"]
    state_data["state"] = "mr_awaiting_phone"
    await update.message.reply_text(_msg(lang, "ask_phone_lookup"))


async def cancel_command(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    state_data = _get_state(user_id)
    lang = state_data["language"]
    state_data["state"] = "cancel_awaiting_phone"
    await update.message.reply_text(_msg(lang, "ask_phone_lookup"))


async def modify_command(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    state_data = _get_state(user_id)
    lang = state_data["language"]
    state_data["state"] = "modify_awaiting_phone"
    await update.message.reply_text(_msg(lang, "ask_phone_lookup"))


# ── Main message router ────────────────────────────────────────────────────────

_RESERVATION_STATES = {
    "awaiting_name", "awaiting_date", "awaiting_date_confirmation",
    "awaiting_time", "awaiting_time_confirmation",
    "awaiting_party_size", "awaiting_seating",
    "awaiting_hookah", "awaiting_phone",
    "awaiting_special_requests", "awaiting_confirmation",
}


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text or ""
    state_data = _get_state(user_id)

    # Language must be explicitly chosen; if not yet set, prompt for selection
    if not state_data.get("language_set"):
        await update.message.reply_text(
            "Please select your language / Selectați limba / Пожалуйста, выберите язык:",
            reply_markup=_lang_keyboard(),
        )
        return

    state = state_data["state"]

    if state in _RESERVATION_STATES:
        await _handle_reservation_text(update, context, state_data, text)

    elif state == "mr_awaiting_phone":
        await _handle_mr_phone(update, context, state_data, text)

    elif state == "cancel_awaiting_phone":
        await _handle_cancel_phone(update, context, state_data, text)

    elif state == "modify_awaiting_phone":
        await _handle_modify_phone(update, context, state_data, text)

    elif state == "modify_awaiting_value":
        await _handle_modify_value(update, context, state_data, text)

    else:  # idle — check triggers or hand off to AI
        lower = text.lower()

        # Mark hookah mention for future reservation context
        if any(kw in lower for kw in HOOKAH_KEYWORDS):
            state_data["hookah_mentioned"] = True

        if any(t in lower for t in RESERVATION_TRIGGERS):
            state_data["state"] = "awaiting_name"
            lang = state_data["language"]
            await update.message.reply_text(_msg(lang, "start_reservation"))
        elif any(t in lower.split() for t in MENU_TRIGGERS):
            lang = state_data["language"]
            prompt, kb = _menu_category_keyboard(lang)
            await update.message.reply_text(prompt, reply_markup=kb)
        else:
            await _handle_ai(update, context, state_data, text)


# ── Callback query handler ─────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    # noop buttons (column headers, empty cells, fully-booked placeholders) — answer silently
    if query.data == "noop" or query.data.startswith("noop_"):
        await query.answer()
        return

    await query.answer()  # dismiss the loading spinner

    user_id = update.effective_user.id
    state_data = _get_state(user_id)
    lang = state_data["language"]
    data = query.data
    msg = query.message  # the original message containing the keyboard

    # ── Language selection ────────────────────────────────────────────────────
    if data in ("lang_en", "lang_ro", "lang_ru"):
        lang = data[len("lang_"):]
        state_data["language"] = lang
        state_data["language_set"] = True
        # Show which language was picked and remove the keyboard
        selected_label = {"en": "🇬🇧 English", "ro": "🇷🇴 Română", "ru": "🇷🇺 Русский"}[lang]
        await query.edit_message_text(
            f"Please select your language / Selectați limba / Пожалуйста, выберите язык:\n\n"
            f"✅ {selected_label}"
        )
        # Send welcome + main menu in the chosen language
        await msg.reply_text(
            _msg(lang, "welcome"),
            reply_markup=_main_menu_keyboard(lang),
        )
        return

    # ── /start menu buttons ───────────────────────────────────────────────────
    if data == "menu_rezervare":
        state_data["state"] = "awaiting_name"
        await msg.reply_text(_msg(lang, "start_reservation"))

    elif data == "menu_echipa":
        handoff = config["human_handoff"]
        reply = {
            "ro": handoff["response_ro"],
            "en": handoff["response_en"],
            "ru": handoff["response_ru"],
        }.get(lang, handoff["response_ro"])
        await msg.reply_text(reply)

    elif data == "menu_meniu":
        prompt, kb = _menu_category_keyboard(lang)
        await msg.reply_text(prompt, reply_markup=kb)

    elif data in ("menu_program", "menu_locatie", "menu_narghilea"):
        questions = {
            "menu_program":   {"ro": "Care este programul restaurantului?",
                               "en": "What are the opening hours?",
                               "ru": "Каковы часы работы ресторана?"},
            "menu_locatie":   {"ro": "Unde este localizat restaurantul și cum ajung acolo?",
                               "en": "Where is the restaurant located and how do I get there?",
                               "ru": "Где находится ресторан и как до него добраться?"},
            "menu_narghilea": {"ro": "Ce tipuri de narghilele aveți și care sunt prețurile?",
                               "en": "What hookah types do you offer and what are the prices?",
                               "ru": "Какие виды кальяна у вас есть и каковы цены?"},
        }
        question = questions[data].get(lang, questions[data]["ro"])
        await _handle_ai(update, context, state_data, question)

    # ── Menu category detail ──────────────────────────────────────────
    elif data.startswith("menu_cat_"):
        category_key = data[len("menu_cat_"):]
        pages = format_menu_category(category_key, lang, config)
        nav_kb = _menu_nav_keyboard(lang)
        for page in pages[:-1]:
            await msg.reply_text(page)
        await msg.reply_text(pages[-1], reply_markup=nav_kb)

    elif data == "menu_back":
        prompt, kb = _menu_category_keyboard(lang)
        await msg.reply_text(prompt, reply_markup=kb)

    elif data == "start_reservation":
        state_data["state"] = "awaiting_name"
        await msg.reply_text(_msg(lang, "start_reservation"))

    # ── Time slot button ──────────────────────────────────────────────────────
    elif data.startswith("slot_"):
        if state_data["state"] == "awaiting_time":
            chosen_time  = data[len("slot_"):]
            slots_by_loc = state_data["data"].get("slots_by_location", {})
            indoor_ok    = not slots_by_loc or chosen_time in slots_by_loc.get("indoor",  [])
            terrace_ok   = not slots_by_loc or chosen_time in slots_by_loc.get("terrace", [])
            state_data["data"]["time"] = chosen_time
            notes = ""
            if chosen_time >= "22:30":
                notes += _msg(lang, "note_sushi")
            if chosen_time >= "23:00":
                notes += _msg(lang, "note_kitchen")
            if notes:
                await msg.reply_text(notes.strip())
            await _show_seating_prompt(msg, state_data, indoor_ok=indoor_ok, terrace_ok=terrace_ok)

    # ── Availability picker selection (time + seating in one tap) ─────────────
    elif data.startswith("pick_"):
        if state_data["state"] == "awaiting_time_confirmation":
            rest     = data[len("pick_"):]             # "indoor_14:00" or "terrace_16:00"
            location, chosen_time = rest.split("_", 1)
            state_data["data"]["time"] = chosen_time
            notes = ""
            if chosen_time >= "22:30":
                notes += _msg(lang, "note_sushi")
            if chosen_time >= "23:00":
                notes += _msg(lang, "note_kitchen")
            if notes:
                await msg.reply_text(notes.strip())
            await _after_seating(msg, state_data, location)

    # ── Seating selection ─────────────────────────────────────────────────────
    elif data in ("seating_indoor", "seating_terrace"):
        if state_data["state"] == "awaiting_seating":
            chosen_loc   = data.split("_", 1)[1]
            slots_by_loc = state_data["data"].get("slots_by_location", {})
            chosen_time  = state_data["data"].get("time", "")
            loc_ok = not slots_by_loc or chosen_time in slots_by_loc.get(chosen_loc, [])
            if loc_ok:
                await _after_seating(msg, state_data, chosen_loc)
            else:
                picker_text, picker_kb = _build_availability_picker(
                    state_data["data"].get("date", ""),
                    state_data["data"].get("party_size", 1),
                    chosen_time,
                    lang,
                    indoor_ok=(chosen_loc != "indoor"),
                    terrace_ok=(chosen_loc != "terrace"),
                )
                state_data["state"] = "awaiting_time_confirmation"
                await msg.reply_text(picker_text, reply_markup=picker_kb)

    # ── Hookah selection ──────────────────────────────────────────────────────
    elif data.startswith("hookah_"):
        if state_data["state"] == "awaiting_hookah":
            hookah_id = data[len("hookah_"):]
            if hookah_id == "skip":
                await _after_hookah(msg, state_data, None)
            else:
                options = get_hookah_options(lang, config)
                chosen = next((o for o in options if o["id"] == hookah_id), None)
                currency = config["hookah"]["currency"]
                hookah_name = f"{chosen['name']} — {chosen['price']} {currency}" if chosen else hookah_id
                await _after_hookah(msg, state_data, hookah_name)

    # ── Reservation confirmation ──────────────────────────────────────────────
    elif data == "confirm_yes":
        if state_data["state"] == "awaiting_confirmation":
            await _do_confirm(msg, context, state_data)

    elif data == "confirm_no":
        if state_data["state"] == "awaiting_confirmation":
            _reset_reservation(state_data)
            await msg.reply_text(_msg(lang, "cancelled_by_user"))

    # ── /cancel confirmation ──────────────────────────────────────────────────
    elif data.startswith("cancel_yes_"):
        res_id = data[len("cancel_yes_"):]
        res = find_by_id(res_id)
        if res and res.get("status") == "cancelled":
            await msg.reply_text(_msg(lang, "already_cancelled"))
        elif cancel_reservation(res_id):
            await msg.reply_text(_msg(lang, "cancel_success", res_id=res_id), parse_mode="Markdown")
        else:
            await msg.reply_text(_msg(lang, "res_not_found"))

    elif data == "cancel_no":
        await msg.reply_text({"ro": "Anulare păstrată.", "en": "Cancellation aborted.", "ru": "Отмена прервана."}[lang])

    # ── /modify field selection ───────────────────────────────────────────────
    elif data.startswith("modify_field_"):
        if state_data["state"] == "modify_awaiting_field":
            field = data[len("modify_field_"):]
            state_data["data"]["modify_field"] = field
            state_data["state"] = "modify_awaiting_value"

            if field == "date":
                await msg.reply_text(_msg(lang, "ask_new_date", example=_example_date()))
            elif field == "time":
                await msg.reply_text(_msg(lang, "ask_new_time", slots=_slots_str()))
            elif field == "party_size":
                await msg.reply_text(_msg(lang, "ask_new_party", max=MAX_PARTY))
            elif field == "special_requests":
                await msg.reply_text(_msg(lang, "ask_new_special"))
