"""
db.py — Работа с Supabase.

Сохранение гипотез и получение данных для scheduled tasks.
"""

import os
import logging
from datetime import date, timedelta

from supabase import create_client, Client

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    """Возвращает Supabase клиент (singleton)."""
    global _client
    if _client is None:
        url = os.getenv('SUPABASE_URL', '')
        key = os.getenv('SUPABASE_SERVICE_KEY', '')
        if not url or not key:
            raise ValueError("SUPABASE_URL и SUPABASE_SERVICE_KEY должны быть заданы в .env")
        _client = create_client(url, key)
    return _client


async def save_hypothesis(hypothesis: dict, source_type: str, source_url: str) -> bool:
    """
    Сохраняет гипотезу в таблицу hypotheses.
    Возвращает True при успехе.
    """
    try:
        client = get_client()
        primary = hypothesis.get('primary_metric', {})
        secondary = hypothesis.get('secondary_metrics', [])
        guardrail = hypothesis.get('guardrail_metrics', [])
        tasks = hypothesis.get('tasks', [])
        tags = hypothesis.get('tags', [])

        # Считаем дедлайн
        duration = int(hypothesis.get('duration_days', 14))
        deadline = (date.today() + timedelta(days=duration)).isoformat()

        data = {
            'source_url': source_url,
            'source_type': source_type,
            'source_summary': hypothesis.get('source_summary', ''),
            'title': hypothesis.get('title', 'Без названия'),
            'observation': hypothesis.get('observation', ''),
            'hypothesis_statement': hypothesis.get('hypothesis_statement', ''),
            'change_to_test': hypothesis.get('change_to_test', ''),
            'audience': hypothesis.get('audience', ''),
            'expected_outcome': hypothesis.get('expected_outcome', ''),

            # Главная метрика
            'primary_metric_name': primary.get('name', ''),
            'primary_metric_description': primary.get('description', ''),
            'primary_metric_baseline': str(primary.get('baseline', '')),
            'primary_metric_target': str(primary.get('target', '')),
            'primary_metric_unit': primary.get('unit', ''),

            # Вторичные метрики и предохранители
            'secondary_metrics': secondary,
            'guardrail_metrics': guardrail,

            # Критерии
            'success_criteria': hypothesis.get('success_criteria', ''),
            'failure_criteria': hypothesis.get('failure_criteria', ''),
            'tasks': tasks,

            # Планирование
            'duration_days': duration,
            'start_date': date.today().isoformat(),
            'deadline': deadline,

            # Классификация
            'status': 'pending',
            'confidence_level': hypothesis.get('confidence_level', 'medium'),
            'tags': tags,
            'context_type': hypothesis.get('context_type', 'both'),
        }

        result = client.table('hypotheses').insert(data).execute()
        return bool(result.data)

    except Exception as e:
        logger.error(f"save_hypothesis error: {e}")
        return False


async def get_active_hypotheses() -> list:
    """Возвращает гипотезы в статусе in_progress и pending."""
    try:
        client = get_client()
        result = client.table('hypotheses') \
            .select('*') \
            .in_('status', ['in_progress', 'pending']) \
            .order('created_at', desc=True) \
            .execute()
        return result.data or []
    except Exception as e:
        logger.error(f"get_active_hypotheses error: {e}")
        return []


async def get_stale_hypotheses(days_without_update: int = 14) -> list:
    """Возвращает гипотезы без обновлений дольше N дней."""
    try:
        from datetime import datetime
        client = get_client()
        cutoff = (date.today() - timedelta(days=days_without_update)).isoformat()
        result = client.table('hypotheses') \
            .select('*') \
            .eq('status', 'in_progress') \
            .lt('updated_at', cutoff) \
            .execute()
        return result.data or []
    except Exception as e:
        logger.error(f"get_stale_hypotheses error: {e}")
        return []
