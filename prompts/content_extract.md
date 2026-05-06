# Промпт: Извлечение контента и предобработка

Ты получаешь сырой текст из разных источников (транскрипт YouTube, статья, расшифровка голосового, PDF). Твоя задача — подготовить его для следующего шага (генерации гипотезы).

## Входные данные

- **source_type**: {{source_type}}
- **source_url**: {{source_url}}
- **raw_content**: {{raw_content}}

---

## Задача

Верни JSON со следующими полями:

```json
{
  "is_useful": true,

  "language": "ru | en | other",

  "content_type": "interview | tutorial | case_study | opinion | research | story | other",

  "main_topic": "О чём этот материал в одном предложении",

  "key_ideas": [
    "Идея 1 — конкретная мысль из материала",
    "Идея 2 — конкретная мысль из материала",
    "Идея 3 — конкретная мысль из материала"
  ],

  "applicable_experience": "Чужой опыт или процесс, который можно применить. Конкретно что делали и каков результат.",

  "cleaned_content": "Очищенный и сжатый текст материала (до 2000 символов). Убери воду, рекламу, офф-топик. Оставь суть.",

  "not_useful_reason": null
}
```

### Если материал не содержит применимых идей:

```json
{
  "is_useful": false,
  "not_useful_reason": "Причина: реклама / нет конкретики / нерелевантная тема / и т.д.",
  "language": "ru",
  "content_type": "other",
  "main_topic": null,
  "key_ideas": [],
  "applicable_experience": null,
  "cleaned_content": null
}
```

---

## Правила

- Если `is_useful: false` — верни только этот объект, дальше не обрабатываем
- `cleaned_content` — самое важное поле, именно оно идёт в hypothesis_gen
- Убирай таймкоды, рекламные вставки, повторы
- Верни только JSON, без markdown-обёртки
