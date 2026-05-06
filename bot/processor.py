"""
processor.py — Извлечение текста из разных типов контента.

Поддерживаемые типы:
  - YouTube / Shorts / Reels (через youtube-transcript-api + yt-dlp fallback)
  - Статьи и сайты (requests + BeautifulSoup)
  - PDF документы (PyMuPDF)
  - DOCX документы (python-docx)
  - Голосовые сообщения и видеофайлы (OpenAI Whisper)
"""

import os
import re
import tempfile
import logging
from typing import Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Определение типа контента
# ──────────────────────────────────────────────

YOUTUBE_PATTERN = re.compile(
    r'(https?://)?(www\.)?(youtube\.com|youtu\.be|youtube\.com/shorts|'
    r'instagram\.com/reel|tiktok\.com|vk\.com/video)',
    re.IGNORECASE
)

def detect_source_type(text: str, mime_type: str = '') -> str:
    """Определяет тип источника по URL или MIME-типу файла."""
    if YOUTUBE_PATTERN.search(text):
        return 'youtube'
    if mime_type.startswith('audio/') or mime_type.startswith('video/'):
        return 'voice' if 'audio' in mime_type else 'video'
    if 'application/pdf' in mime_type:
        return 'document'
    if 'application/vnd.openxmlformats' in mime_type or 'docx' in mime_type:
        return 'document'
    if text.startswith('http'):
        return 'article'
    return 'other'


# ──────────────────────────────────────────────
# YouTube / видео с субтитрами
# ──────────────────────────────────────────────

def extract_youtube(url: str) -> Tuple[str, str]:
    """
    Возвращает (transcript_text, video_title).
    Сначала пробует youtube-transcript-api, потом yt-dlp.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        video_id = _parse_youtube_id(url)
        if not video_id:
            raise ValueError("Не удалось извлечь video_id")

        api = YouTubeTranscriptApi()

        # Предпочитаем русский, потом английский, потом любой
        try:
            transcript_list = api.list(video_id)
            try:
                transcript = transcript_list.find_transcript(['ru', 'en'])
            except Exception:
                transcript = next(iter(transcript_list))
            snippets = transcript.fetch()
        except Exception:
            # Fallback: прямой fetch
            snippets = api.fetch(video_id)

        text = ' '.join(
            s.get('text', s) if isinstance(s, dict) else str(s)
            for s in snippets
        )
        return text, url

    except Exception as e:
        logger.warning(f"youtube-transcript-api failed: {e}, trying yt-dlp")
        return _extract_youtube_ydlp(url)


def _parse_youtube_id(url: str) -> str:
    """Извлекает video_id из разных форматов YouTube URL."""
    patterns = [
        r'(?:v=|/shorts/|youtu\.be/)([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return ''


def _get_ydlp_cookies_opts() -> dict:
    """Возвращает опции куки для yt-dlp."""
    browser = os.getenv('YTDLP_COOKIES_BROWSER', '')
    cookies_file = os.getenv('YTDLP_COOKIES_FILE', '')
    if browser:
        return {'cookiesfrombrowser': (browser,)}
    elif cookies_file and os.path.exists(cookies_file):
        return {'cookiefile': cookies_file}
    return {}


def _extract_youtube_ydlp(url: str) -> Tuple[str, str]:
    """Скачивает субтитры через yt-dlp. Если субтитров нет — транскрибирует аудио через Whisper."""
    try:
        import yt_dlp
        with tempfile.TemporaryDirectory() as tmpdir:
            opts = {
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': ['ru', 'en'],
                'skip_download': True,
                'outtmpl': os.path.join(tmpdir, '%(title)s.%(ext)s'),
                'quiet': True,
            }
            opts.update(_get_ydlp_cookies_opts())

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', url)

            # Ищем файл субтитров
            for fname in os.listdir(tmpdir):
                if fname.endswith('.vtt') or fname.endswith('.srt'):
                    with open(os.path.join(tmpdir, fname), 'r', encoding='utf-8') as f:
                        raw = f.read()
                    text = _clean_subtitles(raw)
                    if text.strip():
                        return text, title

        # Субтитров нет — скачиваем аудио и транскрибируем через Whisper
        logger.info("Субтитры не найдены, пробуем транскрибацию через Whisper...")
        return _extract_audio_via_whisper(url)

    except Exception as e:
        logger.error(f"yt-dlp failed: {e}")
        return '', url


def _extract_audio_via_whisper(url: str) -> Tuple[str, str]:
    """Скачивает аудио через yt-dlp и транскрибирует через OpenAI Whisper."""
    openai_key = os.getenv('OPENAI_API_KEY', '')
    if not openai_key:
        logger.warning("OPENAI_API_KEY не задан — транскрибация недоступна")
        return '', url

    try:
        import yt_dlp
        from openai import OpenAI

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, 'audio.mp3')
            opts = {
                'format': 'bestaudio/best',
                'outtmpl': audio_path,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '64',
                }],
                'quiet': True,
            }
            opts.update(_get_ydlp_cookies_opts())

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', url)

            # Ищем скачанный аудиофайл
            audio_file = None
            for fname in os.listdir(tmpdir):
                if fname.endswith('.mp3') or fname.endswith('.m4a') or fname.endswith('.webm'):
                    audio_file = os.path.join(tmpdir, fname)
                    break

            if not audio_file:
                logger.error("Аудиофайл не найден после скачивания")
                return '', url

            client = OpenAI(api_key=openai_key)
            with open(audio_file, 'rb') as f:
                response = client.audio.transcriptions.create(
                    model='whisper-1',
                    file=f,
                    response_format='text'
                )
            return str(response), title

    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return '', url


def _clean_subtitles(raw: str) -> str:
    """Убирает тайминги и HTML-теги из VTT/SRT субтитров."""
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if re.match(r'^\d{2}:\d{2}', line):  # тайминги
            continue
        if re.match(r'^\d+$', line):  # номера блоков SRT
            continue
        if line in ('WEBVTT', ''):
            continue
        line = re.sub(r'<[^>]+>', '', line)  # HTML-теги
        if line:
            lines.append(line)
    return ' '.join(lines)


# ──────────────────────────────────────────────
# Статьи и веб-страницы
# ──────────────────────────────────────────────

def extract_article(url: str) -> Tuple[str, str]:
    """
    Скрейпит текст статьи. Сначала пробует Jina Reader API (бесплатно),
    потом BeautifulSoup как fallback.
    """
    # Jina Reader: превращает URL в чистый текст
    try:
        jina_url = f"https://r.jina.ai/{url}"
        resp = requests.get(jina_url, timeout=15, headers={'Accept': 'text/plain'})
        if resp.status_code == 200 and len(resp.text) > 200:
            return resp.text[:8000], url
    except Exception as e:
        logger.warning(f"Jina Reader failed: {e}")

    # Fallback: BeautifulSoup
    try:
        resp = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; IdeaBot/1.0)'
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')

        # Убираем мусор
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form']):
            tag.decompose()

        # Ищем основной контент
        content = (
            soup.find('article') or
            soup.find('main') or
            soup.find(class_=re.compile(r'content|article|post|entry', re.I)) or
            soup.body
        )
        text = content.get_text(separator=' ', strip=True) if content else soup.get_text()
        # Чистим лишние пробелы
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:8000], url

    except Exception as e:
        logger.error(f"Article extraction failed: {e}")
        return '', url


# ──────────────────────────────────────────────
# Голосовые и видеофайлы (Whisper)
# ──────────────────────────────────────────────

def extract_audio(file_path: str) -> Tuple[str, str]:
    """
    Транскрибирует аудио/видео через OpenAI Whisper API.
    Требует OPENAI_API_KEY в .env
    """
    openai_key = os.getenv('OPENAI_API_KEY', '')
    if not openai_key:
        return '', 'voice'

    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_key)

        with open(file_path, 'rb') as f:
            response = client.audio.transcriptions.create(
                model='whisper-1',
                file=f,
                language='ru',  # Можно убрать для авто-определения
                response_format='text'
            )
        return str(response), 'voice'

    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return '', 'voice'


# ──────────────────────────────────────────────
# PDF документы
# ──────────────────────────────────────────────

def extract_pdf(file_path: str) -> Tuple[str, str]:
    """Извлекает текст из PDF через PyMuPDF."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        text = ''
        for page in doc:
            text += page.get_text()
        doc.close()
        return text[:8000], 'document'
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return '', 'document'


# ──────────────────────────────────────────────
# DOCX документы
# ──────────────────────────────────────────────

def extract_docx(file_path: str) -> Tuple[str, str]:
    """Извлекает текст из DOCX."""
    try:
        from docx import Document
        doc = Document(file_path)
        text = '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
        return text[:8000], 'document'
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        return '', 'document'


# ──────────────────────────────────────────────
# Главная функция
# ──────────────────────────────────────────────

async def process_content(
    source_type: str,
    source_url: str = '',
    file_path: str = '',
    mime_type: str = ''
) -> dict:
    """
    Главный обработчик. Принимает тип + url/путь к файлу.
    Возвращает словарь: { text, source_type, source_url, success, error }
    """
    text = ''
    error = ''

    try:
        if source_type == 'youtube':
            text, _ = extract_youtube(source_url)

        elif source_type == 'article':
            text, _ = extract_article(source_url)

        elif source_type in ('voice', 'video') and file_path:
            text, _ = extract_audio(file_path)

        elif source_type == 'document' and file_path:
            if file_path.lower().endswith('.pdf'):
                text, _ = extract_pdf(file_path)
            elif file_path.lower().endswith('.docx'):
                text, _ = extract_docx(file_path)
            else:
                # Пробуем как текст
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()[:8000]

        else:
            error = f"Неизвестный тип источника: {source_type}"

    except Exception as e:
        error = str(e)
        logger.error(f"process_content error: {e}")

    return {
        'text': text.strip(),
        'source_type': source_type,
        'source_url': source_url,
        'success': bool(text.strip()),
        'error': error
    }
