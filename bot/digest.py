"""
digest.py — Ежедневный дайджест активных гипотез.

Запуск: python digest.py
Отправляет Telegram-сообщение владельцу со сводкой активных гипотез.
"""

import os
import asyncio
from datetime import date, timedelta
from dotenv import load_dotenv
from supabase import create_client
import requests

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
ALLOWED_USER_ID = os.getenv('ALLOWED_USER_ID', '')
SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY', '')


def send_telegram(text: str):
    """Отправляет сообщение через Telegram Bot API."""
    if not TELEGRAM_TOKEN or not ALLOWED_USER_ID:
        print("⚠️  TELEGRAM_BOT_TOKEN или ALLOWED_USER_ID не заданы")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        'chat_id': ALLOWED_USER_ID,
        'text': text,
        'parse_mode': 'Markdown'
    }, timeout=10)
    if not resp.ok:
        print(f"Telegram error: {resp.text}")


def get_hypotheses():
    """Получает гипотезы из Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return [], []
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Активные гипотезы
    active = client.table('hypotheses') \
        .select('id, title, status, primary_metric_name, primary_metric_target, primary_metric_unit, deadline, updated_at') \
        .in_('status', ['in_progress', 'pending']) \
        .order('created_at', desc=False) \
        .execute().data or []

    # Устаревшие (нет обновлений 7+ дней)
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    stale = client.table('hypotheses') \
        .select('id, title, updated_at') \
        .eq('status', 'in_progress') \
        .lt('updated_at', cutoff) \
        .execute().data or []

    return active, stale


def format_digest(active: list, stale: list) -> str:
    today = date.today().strftime('%d %b %Y')
    lines = [f"☀️ *Дайджест гипотез — {today}*\n"]

    in_progress = [h for h in active if h['status'] == 'in_progress']
    pending = [h for h in active if h['status'] == 'pending']

    if in_progress:
        lines.append(f"🔵 *В работе ({len(in_progress)}):*")
        for h in in_progress:
            deadline = h.get('deadline', '')
            deadline_str = f" · дедлайн {deadline}" if deadline else ''
            lines.append(f"  • {h['title']}{deadline_str}")
        lines.append('')

    if pending:
        lines.append(f"⏳ *Ожидают старта ({len(pending)}):*")
        for h in pending[:3]:
            lines.append(f"  • {h['title']}")
        if len(pending) > 3:
            lines.append(f"  _...и ещё {len(pending) - 3}_")
        lines.append('')

    if stale:
        lines.append(f"⚠️ *Нет обновлений 7+ дней ({len(stale)}):*")
        for h in stale:
            lines.append(f"  • {h['title']}")
        lines.append('\n_Не забудь внести промежуточные метрики!_')

    if not active:
        lines.append("Нет активных гипотез. Пришли контент боту, чтобы создать новую! 💡")

    return '\n'.join(lines)


def main():
    print("📊 Запускаю дайджест гипотез...")
    active, stale = get_hypotheses()
    digest = format_digest(active, stale)
    print(digest)
    send_telegram(digest)
    print("✅ Дайджест отправлен")


if __name__ == '__main__':
    main()
