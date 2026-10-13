"""Database helpers and first-run sample data.

Production uses Postgres (Supabase) via DATABASE_URL. Without it, a local SQLite
file is used so the site can be tried on a laptop with no setup.
Queries are written once with `?` placeholders and work on both.
"""
import os
import re
import sqlite3
from datetime import date, timedelta

from flask import current_app, g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(BASE_DIR, "schema.sql")
# Tables whose primary key is a generated integer `id` (INSERTs return it).
ID_TABLES = {"users", "classes", "batches", "demos", "enrollments", "feedback",
             "payments", "promotions", "messages"}
_INSERT_TABLE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.I)


def database_url():
    return os.environ.get("DATABASE_URL", "").strip()


def is_postgres():
    return database_url().startswith(("postgres://", "postgresql://"))


class _Conn:
    """Thin wrapper so the app code doesn't care which database is underneath."""

    def __init__(self, sqlite_path=None):
        self.pg = is_postgres()
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            # prepare_threshold=None: Supabase's pooler doesn't support prepared statements.
            self.raw = psycopg.connect(database_url(), row_factory=dict_row, prepare_threshold=None)
        else:
            os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
            self.raw = sqlite3.connect(sqlite_path)
            self.raw.row_factory = sqlite3.Row
            self.raw.execute("PRAGMA foreign_keys = ON")

    def _sql(self, sql):
        return sql.replace("?", "%s") if self.pg else sql

    def query(self, sql, args=()):
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(args))
        return cur.fetchall()

    def execute(self, sql, args=()):
        """Run a write. For an INSERT into a table with an id column, returns the new id."""
        m = _INSERT_TABLE.match(sql)
        wants_id = bool(m and m.group(1).lower() in ID_TABLES and "SELECT" not in sql.upper())
        cur = self.raw.cursor()
        if self.pg and wants_id and "RETURNING" not in sql.upper():
            cur.execute(self._sql(sql) + " RETURNING id", tuple(args))
            row = cur.fetchone()
            return row["id"] if row else None
        cur.execute(self._sql(sql), tuple(args))
        return cur.lastrowid if wants_id and not self.pg else None

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()


def connect(app=None):
    app = app or current_app
    return _Conn(app.config["DATABASE"])


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, args=(), one=False):
    rows = get_db().query(sql, args)
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, args=()):
    conn = get_db()
    new_id = conn.execute(sql, args)
    conn.commit()
    return new_id


def _schema_statements(pg):
    with open(SCHEMA) as f:
        text = f.read()
    text = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    if pg:
        text = (text.replace("INTEGER PRIMARY KEY", "BIGSERIAL PRIMARY KEY")
                    .replace("REAL NOT NULL", "DOUBLE PRECISION NOT NULL")
                    .replace("DEFAULT CURRENT_TIMESTAMP",
                             "DEFAULT (to_char(now() AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI:SS'))"))
    return [s.strip() for s in text.split(";") if s.strip()]


def init_db(app, seed=True):
    conn = connect(app)
    fresh = not conn.query(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users'" if conn.pg
        else "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'")
    for stmt in _schema_statements(conn.pg):
        conn.execute(stmt)
    if fresh and seed:
        seed_sample_data(conn)
    conn.commit()
    conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    init_db(app, seed=app.config.get("SEED_SAMPLE_DATA", True))


def seed_sample_data(conn):
    """Sample classes, batches, demos and promotions so the site isn't empty on day one.
    Everything here can be edited or deleted from the admin screens."""
    today = date.today()

    def add_class(name, desc, fee, image, color):
        return conn.execute(
            "INSERT INTO classes (name, description, fee, image, color) VALUES (?,?,?,?,?)",
            (name, desc, fee, image, color),
        )

    odissi = add_class(
        "Odissi",
        "Graceful classical dance from Odisha. Tribhangi, chauka and expressive abhinaya, for beginners and continuing students.",
        2000, "seed-odissi.jpg", "#6b3fa0",
    )
    bharat = add_class(
        "Bharatanatyam",
        "Classical dance from Tamil Nadu. Adavus, rhythm and storytelling, building towards stage performances.",
        2000, "seed-bharatanatyam.jpg", "#c0392b",
    )
    kids = add_class(
        "Kids Classical Foundation",
        "A playful first step into classical dance for children aged 5 to 10: rhythm, posture and mudras.",
        1500, "seed-performance.jpg", "#2e8b57",
    )

    for row in [
        (odissi, "1,3", "17:00", "18:30", ""),
        (odissi, "5", "10:00", "11:30", ""),
        (bharat, "0,2", "17:30", "19:00", ""),
        (bharat, "6", "10:00", "11:30", ""),
        (kids, "5,6", "16:00", "17:00", ""),
    ]:
        conn.execute("INSERT INTO batches (class_id, days, start_time, end_time, teacher) VALUES (?,?,?,?,?)", row)

    loc = "Sanskriti Studio, Ragam Gardens"
    for row in [
        (odissi, (today + timedelta(days=5)).isoformat(), "10:00", "11:00", loc, "Free trial class. Wear comfortable clothes."),
        (bharat, (today + timedelta(days=8)).isoformat(), "11:30", "12:30", loc, "Free trial class."),
        (kids, (today + timedelta(days=12)).isoformat(), "16:00", "17:00", loc, "Parents are welcome to watch."),
    ]:
        conn.execute("INSERT INTO demos (class_id, date, start_time, end_time, location, notes) VALUES (?,?,?,?,?,?)", row)

    for row in [
        ("Free Odissi demo class", "Try a full Odissi class at Sanskriti Studio, Ragam Gardens. Spots are limited, book in one tap.",
         "seed-group.jpg", "image", odissi),
        ("Watch our students perform", "A glimpse of our recent performances. New batches are open for all ages.",
         "seed-reel.mp4", "video", None),
    ]:
        conn.execute("INSERT INTO promotions (title, body, media, media_type, class_id) VALUES (?,?,?,?,?)", row)
