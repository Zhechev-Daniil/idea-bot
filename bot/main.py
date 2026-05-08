"""
main.py — Точка входа Telegram бота.

Запуск:
  python main.py

Переменные окружения задаются в .env (см. .env.example)
"""

import os
import logging
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

from handlers import (
    cmd_start,
    handle_text,
    handle_voice,
    handle_video_note,
    handle_document,
    handle_context_choice,
)

# ──────────────────────────────────────────────
# Логирование
# ──────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Загрузка .env
# ──────────────────────────────────────────────
load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не задан в .env!")


# ──────────────────────────────────────────────
# Обработчик ошибок
# ──────────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "⚠️ Что-то пошло не так. Попробуй ещё раз или пришли другой контент."
        )


# ──────────────────────────────────────────────
# Запуск
# ──────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('help', cmd_start))

    # Кнопки выбора контекста
    app.add_handler(CallbackQueryHandler(handle_context_choice, pattern='^ctx_'))

    # Сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_video_note))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Ошибки
    app.add_error_handler(error_handler)

    logger.info("Бот запущен. Ожидаю сообщения...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
