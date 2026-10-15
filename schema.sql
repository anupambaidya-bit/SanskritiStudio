-- Sanskriti website schema (SQLite). Safe to run repeatedly.

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    phone       TEXT UNIQUE NOT NULL,          -- digits only, with country code, e.g. 919876543210
    role        TEXT NOT NULL DEFAULT 'customer', -- customer | admin
    name        TEXT,
    age         INTEGER,
    community   TEXT,
    parent_name TEXT,                           -- required when age < 14
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS classes (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    fee         INTEGER NOT NULL DEFAULT 0,     -- monthly fee in rupees
    image       TEXT,                           -- filename in static/uploads
    color       TEXT NOT NULL DEFAULT '#6b3fa0',
    active      INTEGER NOT NULL DEFAULT 1
);

-- A batch is a recurring weekly schedule for a class.
CREATE TABLE IF NOT EXISTS batches (
    id          INTEGER PRIMARY KEY,
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    days        TEXT NOT NULL,                  -- comma separated weekdays, Mon=0 ... Sun=6
    start_time  TEXT NOT NULL,                  -- HH:MM
    end_time    TEXT NOT NULL,
    teacher     TEXT,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS demos (
    id          INTEGER PRIMARY KEY,
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    date        TEXT NOT NULL,                  -- YYYY-MM-DD
    start_time  TEXT NOT NULL,
    end_time    TEXT,
    location    TEXT,
    notes       TEXT
);

-- One row per student per class; status walks the funnel:
-- interested -> demo (booked) -> demo_done (feedback pending) -> subscribed   (or dropped)
CREATE TABLE IF NOT EXISTS enrollments (
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id         INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    status           TEXT NOT NULL DEFAULT 'interested',
    demo_id          INTEGER REFERENCES demos(id) ON DELETE SET NULL,
    batch_id         INTEGER REFERENCES batches(id) ON DELETE SET NULL,
    last_reminded_at TEXT,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, class_id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id    INTEGER REFERENCES classes(id) ON DELETE SET NULL,
    kind        TEXT NOT NULL,                  -- demo | regular
    rating      INTEGER,
    comment     TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payments (
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id         INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    period           TEXT NOT NULL,             -- YYYY-MM
    amount           INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending', -- pending | submitted | paid | waived
    method           TEXT,
    reference        TEXT,
    paid_at          TEXT,
    last_reminded_at TEXT,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, class_id, period)
);

CREATE TABLE IF NOT EXISTS promotions (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    body        TEXT,
    media       TEXT,                           -- filename in static/uploads
    media_type  TEXT,                           -- image | video
    class_id    INTEGER REFERENCES classes(id) ON DELETE SET NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Every WhatsApp message the app sends (or would send, in console mode).
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    to_phone    TEXT NOT NULL,
    body        TEXT NOT NULL,
    kind        TEXT,
    provider    TEXT,
    status      TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS otps (
    phone       TEXT PRIMARY KEY,
    code        TEXT NOT NULL,
    expires_at  REAL NOT NULL,
    sent_at     REAL NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Homepage carousel (Admin → Website).
CREATE TABLE IF NOT EXISTS slides (
    id          INTEGER PRIMARY KEY,
    media       TEXT NOT NULL,                  -- uploaded file name
    media_type  TEXT NOT NULL DEFAULT 'image',  -- image | video
    caption     TEXT,
    class_id    INTEGER REFERENCES classes(id) ON DELETE SET NULL,
    sort        INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1
);
