"""
handlers.py — Обработчики сообщений Telegram бота.

Поток обработки:
  1. Пользователь присылает URL / файл / голосовое
  2. Бот задаёт вопрос: «Для кого генерировать гипотезу?»
     с кнопками [🏢 СОЗИДАЙ] и [👤 Даниил]
  3. Пользователь нажимает кнопку
  4. Извлекаем текст через processor.py
  5. Генерируем гипотезу через claude_client.py (с выбранным контекстом)
  6. Сохраняем в Supabase
  7. Отправляем результат
"""

import os
import logging
import tempfile

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from processor import process_content, detect_source_type
from claude_client import content_to_hypothesis
from db import save_hypothesis

logger = logging.getLogger(__name__)

ALLOWED_USER_ID = int(os.getenv('ALLOWED_USER_ID', '0'))

# Inline-клавиатура выбора контекста
CONTEXT_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("🏢 СОЗИДАЙ (бизнес)", callback_data="ctx_startup"),
        InlineKeyboardButton("👤 Даниил (личный бренд)", callback_data="ctx_personal_brand"),
    ]
])

CTX_LABELS = {
    'ctx_startup': ('startup', '🏢 СОЗИДАЙ'),
    'ctx_personal_brand': ('personal_brand', '👤 Даниил'),
}


# ──────────────────────────────────────────────
# Проверка доступа
# ──────────────────────────────────────────────

def is_allowed(update: Update) -> bool:
    """Бот отвечает только владельцу."""
    if not ALLOWED_USER_ID:
        return True
    return update.effective_user.id == ALLOWED_USER_ID


# ──────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "👋 Привет! Я превращаю контент в гипотезы для стартапа и личного бренда.\n\n"
        "Пришли мне:\n"
        "• 🔗 Ссылку на YouTube, статью, Reels, TikTok\n"
        "• 🎙 Голосовое сообщение\n"
        "• 📄 PDF или DOCX документ\n"
        "• 🎬 Видеофайл\n\n"
        "После этого выбери, для кого генерировать гипотезу — "
        "для стартапа 🏢 СОЗИДАЙ или личного бренда 👤 Даниил."
    )


# ──────────────────────────────────────────────
# Хранение ожидающего контента в user_data
# ──────────────────────────────────────────────

def _store_pending(context: ContextTypes.DEFAULT_TYPE, user_id: int,
                   source_type: str, source_url: str,
                   file_path: str = '', mime_type: str = ''):
    """Сохраняет данные контента в user_data до выбора контекста."""
    context.user_data[f'pending_{user_id}'] = {
        'source_type': source_type,
        'source_url': source_url,
        'file_path': file_path,
        'mime_type': mime_type,
    }


def _pop_pending(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict | None:
    """Извлекает и удаляет ожидающие данные."""
    return context.user_data.pop(f'pending_{user_id}', None)


async def _ask_context(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       source_type: str, source_url: str,
                       file_path: str = '', mime_type: str = ''):
    """Сохраняет данные и спрашивает пользователя о контексте."""
    user_id = update.effective_user.id
    _store_pending(context, user_id, source_type, source_url, file_path, mime_type)
    await update.message.reply_text(
        "📥 Контент получен! Для кого генерировать гипотезу?",
        reply_markup=CONTEXT_KEYBOARD
    )


# ──────────────────────────────────────────────
# Обработка текстовых сообщений (URL или свободный текст)
# ──────────────────────────────────────────────

MIN_TEXT_LENGTH = 30  # минимум символов для свободного текста

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    text = update.message.text.strip()
    source_type = detect_source_type(text)

    if source_type in ('youtube', 'article'):
        # Ссылка — обрабатываем как раньше
        await _ask_context(update, context, source_type=source_type, source_url=text)

    elif len(text) >= MIN_TEXT_LENGTH:
        # Свободный текст достаточной длины — генерируем гипотезу напрямую
        await _ask_context(update, context, source_type='other', source_url='text_message', file_path='', mime_type='__text__:' + text)

    else:
        await update.message.reply_text(
            "Пришли:\n"
            "• 🔗 Ссылку на YouTube, статью, Reels\n"
            "• 💬 Текст или идею (от 30 символов)\n"
            "• 🎙 Голосовое сообщение\n"
            "• 📄 PDF или DOCX документ"
        )


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

    await _ask_context(update, context, source_type='voice',
                       source_url='voice_message', file_path=file_path)


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

    await _ask_context(update, context, source_type='video',
                       source_url='video_note', file_path=file_path)


# ──────────────────────────────────────────────
# Обработка документов (PDF, DOCX, видеофайлы)
# ──────────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    doc = update.message.document
    mime = doc.mime_type or ''
    fname = doc.file_name or ''

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

    await _ask_context(update, context, source_type=source_type,
                       source_url=fname or source_type, file_path=file_path,
                       mime_type=mime)


# ──────────────────────────────────────────────
# Обработка нажатия кнопки выбора контекста
# ──────────────────────────────────────────────

async def handle_context_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """CallbackQueryHandler: пользователь выбрал контекст → запускаем пайплайн."""
    query = update.callback_query
    await query.answer()

    if query.data not in CTX_LABELS:
        await query.edit_message_text("❌ Неизвестный выбор. Пришли контент снова.")
        return

    user_id = query.from_user.id
    pending = _pop_pending(context, user_id)
    if not pending:
        await query.edit_message_text(
            "❌ Данные устарели или уже обработаны. Пришли контент ещё раз."
        )
        return

    chosen_context, ctx_label = CTX_LABELS[query.data]

    # Редактируем сообщение с кнопками → показываем статус
    status_msg = await query.edit_message_text(
        f"✅ Контекст: {ctx_label}\n🔍 Анализирую контент..."
    )

    await _run_pipeline(
        status_msg=status_msg,
        source_type=pending['source_type'],
        source_url=pending['source_url'],
        file_path=pending.get('file_path', ''),
        mime_type=pending.get('mime_type', ''),
        chosen_context=chosen_context,
        ctx_label=ctx_label,
    )


# ──────────────────────────────────────────────
# Основной пайплайн: обработка → гипотеза → БД → ответ
# ──────────────────────────────────────────────

async def _run_pipeline(
    status_msg,
    source_type: str,
    source_url: str,
    file_path: str = '',
    mime_type: str = '',
    chosen_context: str = 'both',
    ctx_label: str = '',
):
    """Общий пайплайн для всех типов контента."""

    # 1. Извлекаем текст
    result = await process_content(
        source_type=source_type,
        source_url=source_url,
        file_path=file_path,
        mime_type=mime_type
    )

    if not result['success']:
        await status_msg.edit_text(
            f"❌ Не удалось извлечь контент.\n"
            f"Причина: {result.get('error', 'неизвестная ошибка')}\n\n"
            f"Попробуй другую ссылку или формат."
        )
        return

    await status_msg.edit_text(
        f"✅ Контекст: {ctx_label}\n🧠 Генерирую гипотезу..."
    )

    # 2. Генерируем гипотезу через Claude
    extraction, hypothesis = await content_to_hypothesis(
        raw_text=result['text'],
        source_type=source_type,
        source_url=source_url,
        context=chosen_context
    )

    if not extraction.get('is_useful', False):
        await status_msg.edit_text(
            f"🤔 В этом материале не нашлось применимых идей.\n"
            f"Причина: {extraction.get('not_useful_reason', '—')}\n\n"
            f"Попробуй другой контент."
        )
        return

    if not hypothesis:
        await status_msg.edit_text("❌ Не удалось сгенерировать гипотезу. Попробуй позже.")
        return

    await status_msg.edit_text(
        f"✅ Контекст: {ctx_label}\n💾 Сохраняю в базу данных..."
    )

    # Убеждаемся, что context_type проставлен правильно
    hypothesis['context_type'] = chosen_context

    # 3. Сохраняем в Supabase
    saved = await save_hypothesis(hypothesis, source_type, source_url)

    if not saved:
        await status_msg.edit_text(
            "⚠️ Гипотеза создана, но не удалось сохранить в БД.\n"
            "Проверь настройки Supabase.\n\n" + _format_hypothesis(hypothesis, ctx_label)
        )
        return

    # 4. Отвечаем пользователю
    dashboard_url = os.getenv('DASHBOARD_URL', '')
    response = _format_hypothesis(hypothesis, ctx_label)
    if dashboard_url:
        response += f"\n\n📊 [Открыть дашборд]({dashboard_url})"

    await status_msg.edit_text(response, parse_mode='Markdown')


# ──────────────────────────────────────────────
# Форматирование ответа
# ──────────────────────────────────────────────

def _format_hypothesis(h: dict, ctx_label: str = '') -> str:
    """Форматирует гипотезу для отправки в Telegram."""
    tasks = h.get('tasks', [])
    tasks_text = '\n'.join(f"  {i+1}. {t}" for i, t in enumerate(tasks[:4]))

    primary = h.get('primary_metric', {})
    metric_text = (
        f"{primary.get('name', '—')}: "
        f"{primary.get('baseline', '?')} → {primary.get('target', '?')} "
        f"{primary.get('unit', '')}"
    ) if primary else '—'

    header = f"✅ *Гипотеза сформирована!*"
    if ctx_label:
        header += f" {ctx_label}"

    return (
        f"{header}\n\n"
        f"📌 *{h.get('title', 'Без названия')}*\n\n"
        f"💡 _{h.get('hypothesis_statement', '—')}_\n\n"
        f"📊 *Метрика:* {metric_text}\n"
        f"⏱ *Срок:* {h.get('duration_days', 14)} дней\n"
        f"🎯 *Успех когда:* {h.get('success_criteria', '—')}\n\n"
        f"📋 *Задачи:*\n{tasks_text}"
    )
