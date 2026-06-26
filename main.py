"""Entry point — load .env, configure logging, register handlers, start polling."""

import logging
import os

from dotenv import load_dotenv
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Check your .env file.")

    from bot.handlers import (
        cancel_command,
        handle_callback,
        handle_message,
        modify_command,
        myreservation_command,
        start_command,
    )

    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start",          start_command))
    app.add_handler(CommandHandler("myreservation",  myreservation_command))
    app.add_handler(CommandHandler("cancel",         cancel_command))
    app.add_handler(CommandHandler("modify",         modify_command))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    # All text messages (non-command)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    from bot.sheets import init_tables_sheet
    init_tables_sheet()

    logger.info("Komodo Lounge bot is starting — polling for updates…")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
