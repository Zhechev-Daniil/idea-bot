# 💡 Бот с идеями — Hypothesis Tracker

Telegram бот который превращает контент в проверяемые гипотезы для стартапа и личного бренда. Дашборд для трекинга результатов с чатом Claude Opus.

## Как это работает

```
Ты → [ссылка / файл / голосовое] → Бот
                                      ↓
                            Извлечение текста
                        (YouTube / статья / Whisper / PDF)
                                      ↓
                              Claude Sonnet
                         (анализ → гипотеза + метрики)
                                      ↓
                              Supabase БД
                                      ↓
                    Дашборд (GitHub Pages) + чат с Opus
```

## Быстрый старт

### 1. Клонируй репо
```bash
git clone https://github.com/YOUR_USERNAME/idea-bot.git
cd idea-bot
```

### 2. Создай `.env` из шаблона
```bash
cp .env.example .env
```
Заполни все значения в `.env` (см. раздел Настройка ниже).

### 3. Создай БД в Supabase
- Зарегистрируйся на [supabase.com](https://supabase.com) (бесплатно)
- Создай новый проект
- Перейди в SQL Editor и выполни `database/schema.sql`

### 4. Запусти бота локально
```bash
cd bot
pip install -r requirements.txt
python main.py
```

### 5. Задеплой на Railway
- Зарегистрируйся на [railway.app](https://railway.app)
- New Project → Deploy from GitHub → выбери репо
- В настройках: Start Command = `cd bot && python main.py`
- Добавь все переменные из `.env` в Railway Variables

### 6. Настрой дашборд
- В GitHub репо: Settings → Pages → Deploy from branch `main`, папка `/dashboard`
- Открой `https://YOUR_USERNAME.github.io/idea-bot`
- Введи Supabase URL, Anon Key и Anthropic API Key в настройках дашборда

---

## Настройка (.env)

| Переменная | Где взять | Обязательна |
|-----------|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | @BotFather в Telegram | ✅ |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | ✅ |
| `SUPABASE_URL` | Supabase → Project Settings → API | ✅ |
| `SUPABASE_SERVICE_KEY` | Supabase → Project Settings → API → service_role | ✅ |
| `SUPABASE_ANON_KEY` | Supabase → Project Settings → API → anon | ✅ (для дашборда) |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) | ❌ (только для голоса/видео) |
| `ALLOWED_USER_ID` | @userinfobot в Telegram | Рекомендуется |
| `DASHBOARD_URL` | После деплоя на GitHub Pages | ❌ |

---

## Что умеет бот

| Тип контента | Как отправить | Требования |
|-------------|---------------|------------|
| YouTube видео | Ссылка на видео или Shorts | — |
| Статья / сайт | URL | — |
| Голосовое сообщение | Голосовое в Telegram | OPENAI_API_KEY |
| Видео-кружочек | Видео в Telegram | OPENAI_API_KEY |
| PDF документ | Файл в Telegram | — |
| DOCX документ | Файл в Telegram | — |
| Видеофайл | Файл в Telegram | OPENAI_API_KEY |

---

## Структура репозитория

```
idea-bot/
├── .env.example              # Шаблон переменных окружения
├── .gitignore
├── README.md
│
├── prompts/                  # Промпты для Claude
│   ├── hypothesis_gen.md     # Генерация гипотезы
│   ├── content_extract.md    # Предобработка контента
│   └── consultation.md       # Системный промпт для чата
│
├── database/
│   └── schema.sql            # Схема Supabase
│
├── dashboard/
│   └── index.html            # Дашборд (GitHub Pages)
│
├── bot/                      # Telegram бот (Python)
│   ├── main.py               # Точка входа
│   ├── handlers.py           # Обработчики сообщений
│   ├── processor.py          # Извлечение контента
│   ├── claude_client.py      # Интеграция с Claude API
│   ├── db.py                 # Работа с Supabase
│   └── requirements.txt
│
└── .github/workflows/        # CI/CD
    ├── deploy-dashboard.yml  # Деплой дашборда на GitHub Pages
    └── deploy-bot.yml        # Тесты при push
```

---

## Стек

- **Бот**: Python 3.11, python-telegram-bot 21
- **AI**: Claude Sonnet (гипотезы) + Claude Opus (чат)
- **Транскрипция**: OpenAI Whisper
- **БД**: Supabase (PostgreSQL)
- **Дашборд**: Vanilla JS + Chart.js, хостинг на GitHub Pages
- **Деплой бота**: Railway

---

## Безопасность

- Никогда не коммить `.env` — он в `.gitignore`
- `SUPABASE_SERVICE_KEY` только на сервере (боте), не на фронте
- `SUPABASE_ANON_KEY` — для дашборда (только чтение при правильных RLS политиках)
- `ALLOWED_USER_ID` — бот отвечает только тебе
- Перевыпусти Telegram токен если он попал в публичный чат
