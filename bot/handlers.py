"""
handlers.py — Обработчики сообщений Telegram бота.

Поток обработки:
  1. Пользователь присылает URL / файл / голосовое
  2. Определяем тип контента
  3. Извлекаем текст через processor.py
  4. Генерируем гипотезу через claude_client.py
  5. Сохраняем в Supabase
  6. Отправляем подтверждение пользователю
"""

import os
import logging
import tempfile
from datetime import date, timedelta

from telegram import Update, Message
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from processor import process_content, detect_source_type
from claude_client import content_to_hypothesis
from db import save_hypothesis

logger = logging.getLogger(__name__)

ALLOWED_USER_ID = int(os.getenv('ALLOWED_USER_ID', '0'))
HYPOTHESIS_CONTEXT = os.getenv('HYPOTHESIS_CONTEXT', 'both')


# ──────────────────────────────────────────────
# Проверка доступа
# ──────────────────────────────────────────────

def is_allowed(update: Update) -> bool:
    """Бот отвечает только владельцу."""
    if not ALLOWED_USER_ID:
        return True  # Если не задан — разрешаем всем (для теста)
    return update.effective_user.id == ALLOWED_USER_ID


# ──────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "👋 Привет! Я превращаю контент в гипотезы для твоего стартапа и личного бренда.\n\n"
        "Пришли мне:\n"
        "• 🔗 Ссылку на YouTube, статью, Reels, TikTok\n"
        "• 🎙 Голосовое сообщение\n"
        "• 📄 PDF или DOCX документ\n"
        "• 🎬 Видеофайл\n\n"
        "Я проанализирую и сформирую проверяемую гипотезу с метриками."
    )


# ──────────────────────────────────────────────
# Обработка текстовых сообщений (URL)
# ──────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    text = update.message.text.strip()

    # Определяем тип
    source_type = detect_source_type(text)
    if source_type not in ('youtube', 'article'):
        await update.message.reply_text(
            "Пришли ссылку на YouTube, статью или другой URL, и я сформирую гипотезу."
        )
        return

    await _process_and_respond(update, source_type=source_type, source_url=text)


# ──────────────────────────────────────────────
# Обработка голосовых сообщений
# ──────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    if not os.getenv('OPENAI_API_KEY'):
        await update.message.reply_text(
            "⚠️ Транскрипция голосовых недоступна — добавь OPENAI_API_KEY в .env"
        )
        return

    await update.message.reply_chat_action(ChatAction.TYPING)

    file = await update.message.voice.get_file()
    with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        file_path = tmp.name

    await _process_and_respond(
        update, source_type='voice',
        source_url='voice_message',
        file_path=file_path
    )


# ──────────────────────────────────────────────
# Обработка видеосообщений (кружочки)
# ──────────────────────────────────────────────

async def handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    if not os.getenv('OPENAI_API_KEY'):
        await update.message.reply_text("⚠️ Нужен OPENAI_API_KEY для транскрипции видео")
        return

    file = await update.message.video_note.get_file()
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        file_path = tmp.name

    await _process_and_respond(
        update, source_type='video',
        source_url='video_note',
        file_path=file_path
    )


# ──────────────────────────────────────────────
# Обработка документов (PDF, DOCX, видеофайлы)
# ──────────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    doc = update.message.document
    mime = doc.mime_type or ''
    fname = doc.file_name or ''

    # Определяем тип по MIME и расширению
    if 'pdf' in mime or fname.lower().endswith('.pdf'):
        source_type = 'document'
        suffix = '.pdf'
    elif 'docx' in mime or fname.lower().endswith('.docx'):
        source_type = 'document'
        suffix = '.docx'
    elif mime.startswith('video/') or mime.startswith('audio/'):
        if not os.getenv('OPENAI_API_KEY'):
            await update.message.reply_text("⚠️ Нужен OPENAI_API_KEY для транскрипции")
            return
        source_type = 'video' if mime.startswith('video/') else 'voice'
        suffix = '.mp4' if mime.startswith('video/') else '.ogg'
    else:
        await update.message.reply_text(
            f"Тип файла '{mime}' пока не поддерживается.\n"
            "Пришли PDF, DOCX, аудио или видеофайл."
        )
        return

    file = await doc.get_file()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        file_path = tmp.name

    await _process_and_respond(
        update, source_type=source_type,
        source_url=fname or source_type,
        file_path=file_path
    )


# ──────────────────────────────────────────────
# Основной пайплайн: обработка → гипотеза → БД → ответ
# ──────────────────────────────────────────────

async def _process_and_respond(
    update: Update,
    source_type: str,
    source_url: str,
    file_path: str = '',
    mime_type: str = ''
):
    """Общий пайплайн для всех типов контента."""
    msg = await update.message.reply_text("🔍 Анализирую контент...")

    # 1. Извлекаем текст
    result = await process_content(
        source_type=source_type,
        source_url=source_url,
        file_path=file_path,
        mime_type=mime_type
    )

    if not result['success']:
        await msg.edit_text(
            f"❌ Не удалось извлечь контент.\n"
            f"Причина: {result.get('error', 'неизвестная ошибка')}\n\n"
            f"Попробуй другую ссылку или формат."
        )
        return

    await msg.edit_text("🧠 Генерирую гипотезу...")

    # 2. Генерируем гипотезу через Claude
    extraction, hypothesis = await content_to_hypothesis(
        raw_text=result['text'],
        source_type=source_type,
        source_url=source_url,
        context=HYPOTHESIS_CONTEXT
    )

    if not extraction.get('is_useful', False):
        await msg.edit_text(
            f"🤔 В этом материале не нашлось применимых идей.\n"
            f"Причина: {extraction.get('not_useful_reason', '—')}\n\n"
            f"Попробуй другой контент."
        )
        return

    if not hypothesis:
        await msg.edit_text("❌ Не удалось сгенерировать гипотезу. Попробуй позже.")
        return

    await msg.edit_text("💾 Сохраняю в базу данных...")

    # 3. Сохраняем в Supabase
    saved = await save_hypothesis(hypothesis, source_type, source_url)

    if not saved:
        # Всё равно показываем гипотезу, даже если БД не сработала
        await msg.edit_text(
            "⚠️ Гипотеза создана, но не удалось сохранить в БД.\n"
            "Проверь настройки Supabase.\n\n" + _format_hypothesis(hypothesis)
        )
        return

    # 4. Отвечаем пользователю
    dashboard_url = os.getenv('DASHBOARD_URL', '')
    response = _format_hypothesis(hypothesis)
    if dashboard_url:
        response += f"\n\n📊 [Открыть дашборд]({dashboard_url})"

    await msg.edit_text(response, parse_mode='Markdown')


# ──────────────────────────────────────────────
# Форматирование ответа
# ──────────────────────────────────────────────

def _format_hypothesis(h: dict) -> str:
    """Форматирует гипотезу для отправки в Telegram."""
    tasks = h.get('tasks', [])
    tasks_text = '\n'.join(f"  {i+1}. {t}" for i, t in enumerate(tasks[:4]))

    primary = h.get('primary_metric', {})
    metric_text = (
        f"{primary.get('name', '—')}: "
        f"{primary.get('baseline', '?')} → {primary.get('target', '?')} "
        f"{primary.get('unit', '')}"
    ) if primary else '—'

    return (
        f"✅ *Гипотеза сформирована!*\n\n"
        f"📌 *{h.get('title', 'Без названия')}*\n\n"
        f"💡 _{h.get('hypothesis_statement', '—')}_\n\n"
        f"📊 *Метрика:* {metric_text}\n"
        f"⏱ *Срок:* {h.get('duration_days', 14)} дней\n"
        f"🎯 *Успех когда:* {h.get('success_criteria', '—')}\n\n"
        f"📋 *Задачи:*\n{tasks_text}"
    )
