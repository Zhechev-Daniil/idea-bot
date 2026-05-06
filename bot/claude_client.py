"""
claude_client.py — Интеграция с Claude через OpenRouter API.

Два метода:
  - extract_content()  — предобработка контента (content_extract.md)
  - generate_hypothesis() — генерация гипотезы (hypothesis_gen.md)
"""

import os
import json
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1/chat/completions'

# Пути к промптам (относительно корня репо)
PROMPTS_DIR = Path(__file__).parent.parent / 'prompts'


def _load_prompt(filename: str) -> str:
    """Читает промпт из файла."""
    path = PROMPTS_DIR / filename
    if path.exists():
        return path.read_text(encoding='utf-8')
    logger.warning(f"Промпт не найден: {path}")
    return ''


def _fill_template(template: str, variables: dict) -> str:
    """Простая замена {{variable}} в тексте промпта."""
    for key, value in variables.items():
        template = template.replace('{{' + key + '}}', str(value))
    return template


def _parse_json_response(text: str) -> dict:
    """Пробует распарсить JSON из ответа Claude."""
    text = text.strip()
    if text.startswith('```'):
        text = text.split('```')[1]
        if text.startswith('json'):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nResponse: {text[:500]}")
        return {}


def _call_openrouter(model: str, prompt: str, max_tokens: int) -> str:
    """Синхронный вызов OpenRouter API, возвращает текст ответа."""
    api_key = os.getenv('OPENROUTER_API_KEY')
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com/hypothesis-bot',
        'X-Title': 'Hypothesis Bot',
    }
    payload = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': [{'role': 'user', 'content': prompt}],
    }
    response = httpx.post(OPENROUTER_BASE_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data['choices'][0]['message']['content']


# ──────────────────────────────────────────────
# Предобработка контента
# ──────────────────────────────────────────────

async def extract_content(
    raw_content: str,
    source_type: str,
    source_url: str
) -> dict:
    """
    Шаг 1: Отправляет сырой текст в Claude, получает очищенный контент.
    Возвращает словарь из content_extract.md структуры.
    """
    model = os.getenv('CLAUDE_MODEL', 'anthropic/claude-sonnet-4-6')

    prompt_template = _load_prompt('content_extract.md')
    prompt = _fill_template(prompt_template, {
        'source_type': source_type,
        'source_url': source_url,
        'raw_content': raw_content[:6000]
    })

    try:
        response_text = _call_openrouter(model, prompt, max_tokens=2048)
        return _parse_json_response(response_text)

    except Exception as e:
        logger.error(f"extract_content error: {e}")
        return {'is_useful': False, 'not_useful_reason': str(e)}


# ──────────────────────────────────────────────
# Генерация гипотезы
# ──────────────────────────────────────────────

async def generate_hypothesis(
    cleaned_content: str,
    source_type: str,
    source_url: str,
    context: str = 'both'
) -> dict:
    """
    Шаг 2: Генерирует структурированную гипотезу из очищенного контента.
    Возвращает словарь из hypothesis_gen.md структуры.
    """
    model = os.getenv('CLAUDE_MODEL', 'anthropic/claude-sonnet-4-6')

    prompt_template = _load_prompt('hypothesis_gen.md')
    prompt = _fill_template(prompt_template, {
        'source_type': source_type,
        'source_url': source_url,
        'context': context,
        'extracted_content': cleaned_content
    })

    try:
        response_text = _call_openrouter(model, prompt, max_tokens=4096)
        return _parse_json_response(response_text)

    except Exception as e:
        logger.error(f"generate_hypothesis error: {e}")
        return {}


# ──────────────────────────────────────────────
# Полный пайплайн: контент → гипотеза
# ──────────────────────────────────────────────

async def content_to_hypothesis(
    raw_text: str,
    source_type: str,
    source_url: str,
    context: str = 'both'
) -> tuple[dict, dict]:
    """
    Полный пайплайн:
      1. extract_content — очищаем и анализируем контент
      2. generate_hypothesis — генерируем гипотезу

    Возвращает (extraction_result, hypothesis_result).
    Если контент не полезен — hypothesis_result будет пустым.
    """
    # Шаг 1: Предобработка
    extraction = await extract_content(raw_text, source_type, source_url)

    if not extraction.get('is_useful', False):
        return extraction, {}

    cleaned = extraction.get('cleaned_content', raw_text)

    # Шаг 2: Генерация гипотезы
    hypothesis = await generate_hypothesis(cleaned, source_type, source_url, context)

    return extraction, hypothesis
