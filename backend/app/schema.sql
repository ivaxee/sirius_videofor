-- «Пока жду» — схема БД (PostgreSQL 14+).
-- Идемпотентна: применяется при старте бэкенда и командой `python -m app.cli init-db`.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Остановки (id приходит из QR-кода: ?stop=<id>)
CREATE TABLE IF NOT EXISTS stops (
    id          text PRIMARY KEY CHECK (id ~ '^[A-Za-z0-9_-]{1,32}$'),
    name        text NOT NULL,
    region      text,                       -- район: позволяет подбирать контент «по месту»
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Анонимные пользователи. Никаких персональных данных: только случайный UUID.
CREATE TABLE IF NOT EXISTS users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    consent_at    timestamptz,              -- NULL = согласие не дано / отозвано
    locale        text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now()
);

-- Агрегаты по пользователю: точность на золотых клипах, вес, серия дней.
CREATE TABLE IF NOT EXISTS user_stats (
    user_id           uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    answers_total     integer NOT NULL DEFAULT 0,   -- принятые ответы
    answers_rejected  integer NOT NULL DEFAULT 0,   -- отброшенные антиспамом
    gold_total        integer NOT NULL DEFAULT 0,   -- ответы на золотых клипах (без «Не уверен»)
    gold_correct      integer NOT NULL DEFAULT 0,
    weight            real    NOT NULL DEFAULT 0.5, -- вес голоса во взвешенном большинстве
    is_blocked        boolean NOT NULL DEFAULT false,
    last_answer       text,
    same_answer_run   integer NOT NULL DEFAULT 0,   -- длина серии одинаковых ответов подряд
    last_answer_at    timestamptz,
    streak_days       integer NOT NULL DEFAULT 0,
    last_active_day   date,
    updated_at        timestamptz NOT NULL DEFAULT now()
);

-- Клипы. Лица и номера размыты в пайплайне ДО загрузки; здесь только метаданные.
CREATE TABLE IF NOT EXISTS clips (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id    text UNIQUE,                 -- id из пайплайна (не показывается клиенту)
    storage_key    text NOT NULL,               -- ключ объекта в S3
    duration_ms    integer NOT NULL CHECK (duration_ms BETWEEN 500 AND 10000),
    width          integer,
    height         integer,
    size_bytes     integer,
    -- Трек рамки: [{"t": сек, "x":0..1, "y":0..1, "w":0..1, "h":0..1}, ...]
    bbox           jsonb NOT NULL,
    region         text,
    status         text NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'hidden', 'retired')),
    -- Денормализованное состояние разметки (пересчитывается после каждого ответа)
    votes          integer NOT NULL DEFAULT 0,
    label_state    text NOT NULL DEFAULT 'pending'
                   CHECK (label_state IN ('pending', 'disputed', 'done')),
    final_label    text CHECK (final_label IN ('cig', 'vape', 'no', 'unsure')),
    confidence     real,
    reports_count  integer NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS clips_queue_idx ON clips (label_state, votes) WHERE status = 'active';

-- Золотые клипы: известный ответ эксперта и пояснение для обратной связи.
CREATE TABLE IF NOT EXISTS gold_clips (
    clip_id      uuid PRIMARY KEY REFERENCES clips(id) ON DELETE CASCADE,
    answer       text NOT NULL CHECK (answer IN ('cig', 'vape', 'no')),
    explanation  jsonb NOT NULL,                -- {"ru": "...", "en": "..."}
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Выдача клипа пользователю. Ответ принимается только на выданный клип,
-- поэтому нельзя «разметить» произвольный clip_id или узнать, какой клип золотой.
CREATE TABLE IF NOT EXISTS assignments (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    clip_id      uuid NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    stop_id      text REFERENCES stops(id),
    is_gold      boolean NOT NULL,
    issued_at    timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,          -- до этого момента клип «занят» под ответ
    answered_at  timestamptz,
    UNIQUE (user_id, clip_id)                   -- один пользователь видит клип один раз
);
CREATE INDEX IF NOT EXISTS assignments_inflight_idx
    ON assignments (clip_id) WHERE answered_at IS NULL;

-- Ответы. Для каждого: clip_id, user_id, answer, sub_answer, response_time_ms, stop_id, timestamp.
CREATE TABLE IF NOT EXISTS answers (
    id                bigserial PRIMARY KEY,
    assignment_id     uuid NOT NULL UNIQUE REFERENCES assignments(id) ON DELETE CASCADE,
    clip_id           uuid NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    user_id           uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    answer            text NOT NULL CHECK (answer IN ('cig', 'vape', 'no', 'unsure')),
    sub_answer        text CHECK (sub_answer IN ('scratch', 'eat', 'phone', 'mask', 'other')),
    response_time_ms  integer NOT NULL CHECK (response_time_ms >= 0),
    stop_id           text REFERENCES stops(id),
    is_gold           boolean NOT NULL,
    gold_match        boolean,                  -- NULL для обычных клипов и «Не уверен»
    status            text NOT NULL DEFAULT 'accepted' CHECK (status IN ('accepted', 'rejected')),
    reject_reason     text,                     -- too_fast | burst | same_answer_run | no_consent
    ip_hash           text,                     -- HMAC(IP + день), сырой IP не хранится
    created_at        timestamptz NOT NULL DEFAULT now()   -- timestamp ответа
);
CREATE INDEX IF NOT EXISTS answers_clip_idx ON answers (clip_id) WHERE status = 'accepted';
CREATE INDEX IF NOT EXISTS answers_user_idx ON answers (user_id, created_at);
CREATE INDEX IF NOT EXISTS answers_ip_idx   ON answers (ip_hash, created_at);
CREATE INDEX IF NOT EXISTS answers_stop_idx ON answers (stop_id, created_at);

-- Жалобы на клипы.
CREATE TABLE IF NOT EXISTS clip_reports (
    id           bigserial PRIMARY KEY,
    clip_id      uuid NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason       text NOT NULL CHECK (reason IN ('inappropriate', 'privacy', 'broken', 'other')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz,
    resolution   text CHECK (resolution IN ('restored', 'removed')),
    UNIQUE (clip_id, user_id)
);
CREATE INDEX IF NOT EXISTS clip_reports_open_idx ON clip_reports (clip_id) WHERE resolved_at IS NULL;
