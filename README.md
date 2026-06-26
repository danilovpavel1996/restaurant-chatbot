# Komodo Lounge Floreasca — Telegram Chatbot

A multilingual (Romanian / English / Russian) Telegram chatbot for restaurant reservations and AI-powered Q&A, built with **python-telegram-bot v20** and **OpenAI GPT-4o-mini**.

---

## Features

- **Guided reservation flow** — step-by-step state machine that collects name, date, time, party size, phone, seating preference, hookah choice, and special requests
- **AI free-form chat** — GPT-4o-mini answers menu questions, recommends dishes, explains opening hours, hookah pricing, etc.
- **Auto language detection** — detects Romanian, English, or Russian from the first message and responds in that language throughout
- **Human handoff** — routes complaints / manager requests to the phone number in the config
- **Reservation management** — `/myreservation`, `/cancel`, `/modify` commands backed by `reservations.json`

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your real values:

```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
OPENAI_API_KEY=your_openai_api_key_here
```

- Get a Telegram bot token from [@BotFather](https://t.me/BotFather)
- Get an OpenAI API key from [platform.openai.com](https://platform.openai.com)

### 3. Run

```bash
python main.py
```

The bot will start polling Telegram for updates. Open your bot in Telegram and send `/start`.

---

## Project structure

```
restaurant_chatbot/
├── restaurant_config.json   # All restaurant data (menu, hours, hookah, policies)
├── reservations.json        # Live reservation storage (JSON flat-file)
├── .env                     # Secrets — never commit this
├── .env.example             # Template for secrets
├── requirements.txt
├── main.py                  # Entry point
└── bot/
    ├── __init__.py
    ├── handlers.py          # Telegram handlers + reservation state machine
    ├── ai.py                # OpenAI system prompt + chat completion
    ├── reservations.py      # CRUD for reservations.json
    └── utils.py             # Config loading, language detection, formatters
```

---

## Bot commands

| Command | Description |
|---|---|
| `/start` | Welcome message with quick-action menu |
| `/myreservation` | Look up your reservations by phone number |
| `/cancel` | Cancel an active reservation |
| `/modify` | Modify date, time, guests, or special requests |

---

## Customising for a new client

All restaurant-specific data lives in `restaurant_config.json`. To white-label this bot for a different venue:

1. **Update `restaurant_config.json`** — replace name, address, phone, hours, menu items, hookah options, and `human_handoff` messages.
2. **Adjust time slots** — edit `reservations.time_slots` to match the new venue's booking windows.
3. **Update `max_party_size`** and `booking_window_days` in the same section.
4. **Re-run** `python main.py` — no code changes needed.

The AI system prompt is automatically built from `restaurant_config.json` at startup (see `bot/utils.py → config_to_text_summary`), so the model will immediately know the new menu and policies.

---

## Architecture notes

- **State machine** — per-user conversation state is held in memory (`bot/handlers.py → _states`). On bot restart states reset to idle; active reservations are preserved in `reservations.json`.
- **Language detection** — uses Cyrillic character ratio for Russian, Romanian diacritics / keywords for Romanian, and defaults to Romanian if unsure. Language is locked after the first real message.
- **AI context window** — the last 10 message turns are included in each OpenAI request to keep costs low while maintaining conversational memory.
- **No database** — `reservations.json` is sufficient for a demo or small venue. Replace `bot/reservations.py` with a database adapter for production.
