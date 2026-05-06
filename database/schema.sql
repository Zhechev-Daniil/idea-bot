-- ============================================================
-- Схема базы данных: Бот с идеями
-- Платформа: Supabase (PostgreSQL)
-- Как применить: Supabase Dashboard → SQL Editor → вставь и выполни
-- ============================================================

-- Расширения
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- ТАБЛИЦА: hypotheses
-- Основная таблица гипотез
-- ============================================================
CREATE TABLE IF NOT EXISTS hypotheses (
  id                    UUID DEFAULT uuid_generate_v4() PRIMARY KEY,

  -- Источник
  source_url            TEXT,
  source_type           TEXT CHECK (source_type IN ('youtube', 'article', 'voice', 'video', 'document', 'other')),
  source_summary        TEXT,                        -- О чём был материал

  -- Гипотеза
  title                 TEXT NOT NULL,               -- Короткое название
  observation           TEXT,                        -- Что натолкнуло на гипотезу
  hypothesis_statement  TEXT NOT NULL,               -- Because X, we believe Y will cause Z
  change_to_test        TEXT,                        -- Что конкретно тестируем
  audience              TEXT,                        -- На кого направлено
  expected_outcome      TEXT,                        -- Что должно произойти

  -- Метрики
  primary_metric_name        TEXT,                   -- Название главной метрики
  primary_metric_description TEXT,                   -- Что именно измеряем
  primary_metric_baseline    TEXT,                   -- Текущее значение
  primary_metric_target      TEXT,                   -- Целевое значение
  primary_metric_unit        TEXT,                   -- Единица измерения
  secondary_metrics          JSONB DEFAULT '[]',     -- [{name, description, unit}]
  guardrail_metrics          JSONB DEFAULT '[]',     -- [{name, description, threshold}]

  -- Критерии
  success_criteria      TEXT,
  failure_criteria      TEXT,
  tasks                 JSONB DEFAULT '[]',          -- ["задача 1", "задача 2"]

  -- Планирование
  duration_days         INTEGER DEFAULT 14,
  start_date            DATE,
  deadline              DATE,

  -- Статус и результат
  status                TEXT DEFAULT 'pending'
                        CHECK (status IN ('pending', 'in_progress', 'success', 'failure', 'archived')),
  result_summary        TEXT,                        -- Итог после завершения
  confidence_level      TEXT DEFAULT 'medium'
                        CHECK (confidence_level IN ('low', 'medium', 'high')),

  -- Классификация
  tags                  JSONB DEFAULT '[]',          -- ["growth", "content", ...]
  context_type          TEXT DEFAULT 'both'
                        CHECK (context_type IN ('startup', 'personal_brand', 'both')),

  -- Технические поля
  created_at            TIMESTAMPTZ DEFAULT NOW(),
  updated_at            TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ТАБЛИЦА: metric_updates
-- Промежуточные обновления метрик по гипотезе
-- ============================================================
CREATE TABLE IF NOT EXISTS metric_updates (
  id               UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  hypothesis_id    UUID REFERENCES hypotheses(id) ON DELETE CASCADE,

  date             DATE DEFAULT CURRENT_DATE,
  metric_name      TEXT NOT NULL,                    -- Название метрики
  metric_value     NUMERIC,                          -- Числовое значение
  metric_value_str TEXT,                             -- Если нечисловое
  note             TEXT,                             -- Комментарий

  created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ТАБЛИЦА: hypothesis_notes
-- Лог заметок и наблюдений по гипотезе
-- ============================================================
CREATE TABLE IF NOT EXISTS hypothesis_notes (
  id             UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  hypothesis_id  UUID REFERENCES hypotheses(id) ON DELETE CASCADE,

  note           TEXT NOT NULL,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ИНДЕКСЫ для производительности
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_hypotheses_status     ON hypotheses(status);
CREATE INDEX IF NOT EXISTS idx_hypotheses_context    ON hypotheses(context_type);
CREATE INDEX IF NOT EXISTS idx_hypotheses_created    ON hypotheses(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_metric_updates_hyp_id ON metric_updates(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_metric_updates_date   ON metric_updates(date DESC);
CREATE INDEX IF NOT EXISTS idx_notes_hyp_id          ON hypothesis_notes(hypothesis_id);

-- ============================================================
-- ТРИГГЕР: автообновление updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_hypotheses_updated_at
  BEFORE UPDATE ON hypotheses
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- ROW LEVEL SECURITY (RLS)
-- Включи если хочешь использовать anon key на фронте
-- ============================================================
ALTER TABLE hypotheses       ENABLE ROW LEVEL SECURITY;
ALTER TABLE metric_updates   ENABLE ROW LEVEL SECURITY;
ALTER TABLE hypothesis_notes ENABLE ROW LEVEL SECURITY;

-- Политика: полный доступ через service_role key (бот)
-- Политика: чтение/запись через anon key (дашборд) — только если нужна публичность
-- Для приватного дашборда используй service_role key

CREATE POLICY "service_role_all_hypotheses"
  ON hypotheses FOR ALL
  USING (true);

CREATE POLICY "service_role_all_metric_updates"
  ON metric_updates FOR ALL
  USING (true);

CREATE POLICY "service_role_all_notes"
  ON hypothesis_notes FOR ALL
  USING (true);

-- ============================================================
-- Пример тестовой гипотезы (можно удалить)
-- ============================================================
INSERT INTO hypotheses (
  title,
  source_type,
  source_summary,
  observation,
  hypothesis_statement,
  change_to_test,
  audience,
  expected_outcome,
  primary_metric_name,
  primary_metric_description,
  primary_metric_baseline,
  primary_metric_target,
  primary_metric_unit,
  success_criteria,
  failure_criteria,
  tasks,
  duration_days,
  status,
  confidence_level,
  tags,
  context_type
) VALUES (
  'Тестовая гипотеза — удали меня',
  'youtube',
  'Видео о том как основатель стартапа вырос с 0 до 10k подписчиков за 90 дней через Reels',
  'Автор публиковал 1 Reels в день с личными историями провалов и за 90 дней набрал 10k подписчиков',
  'Because автор вырос x10 публикуя личные истории ежедневно, we believe публикация 1 Reels в день с историями из опыта will cause рост аудитории для моего личного бренда. We''ll know this is true when охват вырастет на 50% за 30 дней.',
  'Публиковать 1 короткое видео (Reels/Shorts) в день с личной историей или инсайтом',
  'Потенциальные клиенты и подписчики',
  'Рост охвата и подписчиков на 50% за 30 дней',
  'Охват публикаций',
  'Суммарные просмотры всех Reels за период',
  '1000',
  '1500',
  'просмотры',
  'Суммарный охват за 30 дней > 15000 просмотров',
  'Суммарный охват за 30 дней < 8000 просмотров',
  '["Подготовить 7 идей для первой недели", "Снять и опубликовать первый Reels", "Настроить таблицу трекинга метрик", "Публиковать ежедневно в одно время"]',
  30,
  'pending',
  'high',
  '["content", "brand", "distribution"]',
  'personal_brand'
);
