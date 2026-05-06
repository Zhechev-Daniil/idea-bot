"""
Hypothesis Tracker MCP Server
==============================
Даёт Claude нативный доступ к твоим гипотезам в Supabase.
Работает в любом чате Claude Desktop — не только в Cowork.

Запуск для проверки:
    python server.py

Регистрация в Claude Desktop: см. claude_desktop_config.json
"""

import os
import json
from datetime import date, datetime
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from supabase import create_client, Client

# Загружаем .env из папки проекта (на уровень выше mcp_server/)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# ──────────────────────────────────────────────
# Supabase клиент
# ──────────────────────────────────────────────
def get_db() -> Client:
    url = os.getenv('SUPABASE_URL', '')
    key = os.getenv('SUPABASE_SERVICE_KEY', '')
    if not url or not key:
        raise ValueError(
            "Не заданы SUPABASE_URL и SUPABASE_SERVICE_KEY в .env\n"
            f"Путь к .env: {os.path.join(os.path.dirname(__file__), '..', '.env')}"
        )
    return create_client(url, key)


def resolve_id(db: Client, hypothesis_id: str, select: str = 'id') -> str | None:
    """
    Резолвит короткий префикс (8+ символов) в полный UUID.
    Шаг 1: тянем только колонку id — минимум данных, работает с любым объёмом.
    Шаг 2: возвращаем полный UUID для точного запроса.
    """
    if len(hypothesis_id) == 36:
        return hypothesis_id
    # Fetch only IDs — очень маленький payload даже при тысячах гипотез
    result = db.table('hypotheses').select('id').execute()
    ids = [r['id'] for r in (result.data or [])]
    matches = [uid for uid in ids if uid.startswith(hypothesis_id)]
    return matches[0] if matches else None


# ──────────────────────────────────────────────
# MCP сервер
# ──────────────────────────────────────────────
mcp = FastMCP(
    "hypothesis-tracker",
    instructions=(
        "Ты имеешь доступ к трекеру гипотез пользователя. "
        "Используй инструменты чтобы читать и обновлять гипотезы, метрики и статусы. "
        "Всегда отвечай на русском языке. Будь конкретным и полезным."
    )
)


# ──────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────
STATUS_LABELS = {
    'pending': 'Ожидает',
    'in_progress': 'В работе',
    'success': 'Успех ✅',
    'failure': 'Провал ❌',
    'archived': 'Архив'
}

def fmt_date(d: str) -> str:
    if not d:
        return '—'
    try:
        return datetime.fromisoformat(d[:10]).strftime('%d.%m.%Y')
    except Exception:
        return d[:10]

def fmt_hypothesis_short(h: dict) -> str:
    status = STATUS_LABELS.get(h.get('status', ''), h.get('status', ''))
    deadline = fmt_date(h.get('deadline', ''))
    metric = h.get('primary_metric_name', '')
    target = h.get('primary_metric_target', '')
    unit = h.get('primary_metric_unit', '')
    metric_str = f" | Метрика: {metric} → {target} {unit}".rstrip() if metric else ''
    deadline_str = f" | Дедлайн: {deadline}" if h.get('deadline') else ''
    return f"[{h['id'][:8]}] {h['title']} [{status}]{metric_str}{deadline_str}"

def fmt_hypothesis_full(h: dict, updates: list = None, notes: list = None) -> str:
    lines = []
    lines.append(f"# {h['title']}")
    lines.append(f"**ID:** {h['id']}")
    lines.append(f"**Статус:** {STATUS_LABELS.get(h.get('status',''), h.get('status',''))}")
    lines.append(f"**Контекст:** {h.get('context_type', '—')}")
    lines.append(f"**Уверенность:** {h.get('confidence_level', '—')}")
    if h.get('tags'):
        tags = h['tags'] if isinstance(h['tags'], list) else json.loads(h['tags'] or '[]')
        lines.append(f"**Теги:** {', '.join(tags)}")
    lines.append('')

    if h.get('source_summary'):
        lines.append(f"**Источник:** {h['source_summary']}")
        if h.get('source_url'):
            lines.append(f"**URL:** {h['source_url']}")
        lines.append('')

    if h.get('hypothesis_statement'):
        lines.append(f"**Гипотеза:**\n> {h['hypothesis_statement']}")
        lines.append('')

    if h.get('change_to_test'):
        lines.append(f"**Что тестируем:** {h['change_to_test']}")
    if h.get('audience'):
        lines.append(f"**Аудитория:** {h['audience']}")
    if h.get('expected_outcome'):
        lines.append(f"**Ожидаемый результат:** {h['expected_outcome']}")
    lines.append('')

    # Метрики
    lines.append("## Метрики")
    pm = h.get('primary_metric_name', '—')
    baseline = h.get('primary_metric_baseline', '?')
    target = h.get('primary_metric_target', '?')
    unit = h.get('primary_metric_unit', '')

    # Последнее значение из обновлений
    current = baseline
    if updates:
        primary_updates = [u for u in updates if u.get('metric_name') == pm]
        if primary_updates:
            current = str(primary_updates[-1]['metric_value'])

    lines.append(f"**Главная — {pm}:** {baseline} → текущее: {current} → цель: {target} {unit}".rstrip())

    sec = h.get('secondary_metrics', [])
    if isinstance(sec, str):
        sec = json.loads(sec or '[]')
    for m in sec:
        lines.append(f"  - {m.get('name','')}: {m.get('description','')} ({m.get('unit','')})")

    lines.append('')
    if h.get('success_criteria'):
        lines.append(f"**Критерий успеха:** {h['success_criteria']}")
    if h.get('failure_criteria'):
        lines.append(f"**Критерий провала:** {h['failure_criteria']}")

    lines.append(f"**Срок:** {h.get('duration_days', '?')} дней | Дедлайн: {fmt_date(h.get('deadline',''))}")
    lines.append('')

    # Задачи
    tasks = h.get('tasks', [])
    if isinstance(tasks, str):
        tasks = json.loads(tasks or '[]')
    if tasks:
        lines.append("## Задачи")
        for t in tasks:
            lines.append(f"  - {t}")
        lines.append('')

    # История метрик
    if updates:
        lines.append("## Последние обновления метрик")
        for u in updates[-8:]:
            note = f" — {u['note']}" if u.get('note') else ''
            lines.append(f"  {fmt_date(u['date'])}: {u['metric_name']} = {u['metric_value']} {unit}{note}".rstrip())
        lines.append('')

    # Заметки
    if notes:
        lines.append("## Заметки")
        for n in notes[-5:]:
            lines.append(f"  {fmt_date(n['created_at'])}: {n['note']}")
        lines.append('')

    if h.get('result_summary'):
        lines.append(f"## Итог\n{h['result_summary']}")

    return '\n'.join(lines)


# ──────────────────────────────────────────────
# ИНСТРУМЕНТЫ
# ──────────────────────────────────────────────

@mcp.tool()
def get_hypotheses(status: str = None) -> str:
    """
    Показывает список гипотез. Без фильтра — все активные (pending + in_progress).
    Укажи status='success', 'failure', 'archived' или 'all' для других фильтров.
    """
    db = get_db()
    query = db.table('hypotheses').select(
        'id, title, status, primary_metric_name, primary_metric_target, '
        'primary_metric_unit, deadline, confidence_level, tags, context_type'
    )

    if status == 'all':
        pass
    elif status in ('success', 'failure', 'archived', 'pending', 'in_progress'):
        query = query.eq('status', status)
    else:
        # По умолчанию — активные
        query = query.in_('status', ['pending', 'in_progress'])

    result = query.order('created_at', desc=False).execute()
    rows = result.data or []

    if not rows:
        label = STATUS_LABELS.get(status, status or 'активных')
        return f"Нет гипотез со статусом «{label}»."

    label = STATUS_LABELS.get(status, 'Активные') if status and status != 'all' else \
            ('Все' if status == 'all' else 'Активные')

    lines = [f"## {label} гипотезы ({len(rows)})\n"]
    for h in rows:
        lines.append(fmt_hypothesis_short(h))

    lines.append(f"\nЧтобы узнать детали, вызови get_hypothesis_detail с полным ID.")
    return '\n'.join(lines)


@mcp.tool()
def get_hypothesis_detail(hypothesis_id: str) -> str:
    """
    Показывает полную информацию о гипотезе: описание, метрики, задачи,
    историю обновлений и заметки. Принимает полный UUID или первые 8 символов.
    """
    db = get_db()

    full_id = resolve_id(db, hypothesis_id)
    if not full_id:
        return f"Гипотеза с ID «{hypothesis_id}» не найдена."

    result = db.table('hypotheses').select('*').eq('id', full_id).execute()
    rows = result.data or []
    if not rows:
        return f"Гипотеза с ID «{hypothesis_id}» не найдена."
    h = rows[0]

    # Загружаем обновления метрик
    updates_result = db.table('metric_updates').select('*') \
        .eq('hypothesis_id', full_id).order('date').execute()
    updates = updates_result.data or []

    # Загружаем заметки
    notes_result = db.table('hypothesis_notes').select('*') \
        .eq('hypothesis_id', full_id).order('created_at').execute()
    notes = notes_result.data or []

    return fmt_hypothesis_full(h, updates, notes)


@mcp.tool()
def update_hypothesis_status(
    hypothesis_id: str,
    status: str,
    result_summary: str = None
) -> str:
    """
    Обновляет статус гипотезы.
    status: pending | in_progress | success | failure | archived
    result_summary: краткий итог (обязателен для success/failure).
    Принимает полный UUID или первые 8 символов ID.
    """
    valid = ('pending', 'in_progress', 'success', 'failure', 'archived')
    if status not in valid:
        return f"Неверный статус «{status}». Допустимые: {', '.join(valid)}"

    db = get_db()

    full_id = resolve_id(db, hypothesis_id)
    if not full_id:
        return f"Гипотеза «{hypothesis_id}» не найдена."
    r = db.table('hypotheses').select('id, title').eq('id', full_id).execute()
    title = r.data[0]['title'] if r.data else '—'

    update_data = {'status': status}
    if result_summary:
        update_data['result_summary'] = result_summary

    db.table('hypotheses').update(update_data).eq('id', full_id).execute()

    label = STATUS_LABELS.get(status, status)
    result_str = f"\nИтог: {result_summary}" if result_summary else ''
    return f"✅ Гипотеза «{title}» → статус обновлён на «{label}».{result_str}"


@mcp.tool()
def add_metric_update(
    hypothesis_id: str,
    metric_name: str,
    value: float,
    note: str = None,
    update_date: str = None
) -> str:
    """
    Добавляет обновление метрики для гипотезы.
    hypothesis_id: полный UUID или первые 8 символов.
    metric_name: название метрики (например 'Охват публикаций').
    value: числовое значение.
    note: опциональный комментарий.
    update_date: дата в формате YYYY-MM-DD (по умолчанию — сегодня).
    """
    db = get_db()

    full_id = resolve_id(db, hypothesis_id)
    if not full_id:
        return f"Гипотеза «{hypothesis_id}» не найдена."
    r = db.table('hypotheses').select(
        'id, title, primary_metric_name, primary_metric_target, primary_metric_unit'
    ).eq('id', full_id).execute()
    if not r.data:
        return f"Гипотеза «{hypothesis_id}» не найдена."
    h = r.data[0]
    today = update_date or date.today().isoformat()

    db.table('metric_updates').insert({
        'hypothesis_id': full_id,
        'date': today,
        'metric_name': metric_name,
        'metric_value': value,
        'note': note
    }).execute()

    # Проверяем прогресс к цели
    target = h.get('primary_metric_target', '')
    unit = h.get('primary_metric_unit', '')
    progress_str = ''
    if target and h.get('primary_metric_name') == metric_name:
        try:
            pct = round((value / float(target)) * 100)
            progress_str = f"\nПрогресс к цели ({target} {unit}): {pct}%"
        except Exception:
            pass

    return (
        f"✅ Метрика добавлена для «{h['title']}»\n"
        f"  {metric_name}: {value} {unit} ({today})"
        f"{progress_str}"
        + (f"\n  Заметка: {note}" if note else '')
    )


@mcp.tool()
def add_hypothesis_note(hypothesis_id: str, note: str) -> str:
    """
    Добавляет текстовую заметку к гипотезе — наблюдение, вывод, идею.
    Принимает полный UUID или первые 8 символов ID.
    """
    db = get_db()

    full_id = resolve_id(db, hypothesis_id)
    if not full_id:
        return f"Гипотеза «{hypothesis_id}» не найдена."
    r = db.table('hypotheses').select('id, title').eq('id', full_id).execute()
    title = r.data[0]['title'] if r.data else '—'

    db.table('hypothesis_notes').insert({
        'hypothesis_id': full_id,
        'note': note
    }).execute()

    return f"✅ Заметка добавлена к «{title}»:\n  {note}"


@mcp.tool()
def get_metrics_history(hypothesis_id: str, metric_name: str = None) -> str:
    """
    Показывает историю обновлений метрик для гипотезы в виде таблицы.
    metric_name: если указан — только эта метрика, иначе все.
    Принимает полный UUID или первые 8 символов ID.
    """
    db = get_db()

    full_id = resolve_id(db, hypothesis_id)
    if not full_id:
        return f"Гипотеза «{hypothesis_id}» не найдена."
    r = db.table('hypotheses').select('id, title, primary_metric_unit').eq('id', full_id).execute()
    if not r.data:
        return f"Гипотеза «{hypothesis_id}» не найдена."
    h = r.data[0]
    unit = h.get('primary_metric_unit', '')

    query = db.table('metric_updates').select('*').eq('hypothesis_id', h['id'])
    if metric_name:
        query = query.eq('metric_name', metric_name)
    result = query.order('date').execute()
    updates = result.data or []

    if not updates:
        return f"Нет обновлений метрик для «{h['title']}»."

    lines = [f"## История метрик: «{h['title']}»\n"]
    lines.append(f"{'Дата':<12} {'Метрика':<30} {'Значение':>10}  Заметка")
    lines.append('─' * 65)
    for u in updates:
        note = u.get('note') or ''
        lines.append(
            f"{fmt_date(u['date']):<12} {u['metric_name']:<30} "
            f"{str(u['metric_value']) + ' ' + unit:>10}  {note}"
        )

    # Трендовая стрелка для главной метрики
    if len(updates) >= 2:
        first = float(updates[0]['metric_value'])
        last = float(updates[-1]['metric_value'])
        diff = last - first
        arrow = '↑' if diff > 0 else ('↓' if diff < 0 else '→')
        pct = round(abs(diff) / first * 100) if first else 0
        lines.append(f"\nТренд: {arrow} {'+' if diff > 0 else ''}{diff:.1f} {unit} ({pct}% с начала)")

    return '\n'.join(lines)


# ──────────────────────────────────────────────
# Запуск
# ──────────────────────────────────────────────
if __name__ == '__main__':
    mcp.run()
