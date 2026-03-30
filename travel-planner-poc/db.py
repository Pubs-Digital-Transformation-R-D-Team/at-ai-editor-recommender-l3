"""
Postgres connection, schema init, and seed data.
─────────────────────────────────────────────────
All tables live under the `travel_poc` schema.

Tables:
  session_checkpoints   — L2 Session Memory
  trip_history          — L3 Long-term Memory (trips)
  travel_preferences    — L3 Long-term Memory (preferences)
"""

import logging
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "mspubs-dev.cdeku8g0y28t.us-east-1.rds.amazonaws.com"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "mspubs"),
    "user": os.getenv("DB_USER", "mspubs_user"),
    "password": os.getenv("DB_PASSWORD", "mspubs_user"),
}
SCHEMA = os.getenv("DB_SCHEMA", "travel_poc")

# ── Connection ────────────────────────────────────────────────────────────────

def get_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {SCHEMA}, public;")
    return conn


def execute_query(sql: str, params: tuple = ()):
    """Run a SELECT and return rows as list[dict]."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def execute_insert(sql: str, params: tuple = ()):
    """Run an INSERT / UPDATE / DELETE."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    finally:
        conn.close()


# ── Schema DDL ────────────────────────────────────────────────────────────────

_DDL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};
SET search_path TO {SCHEMA}, public;

CREATE TABLE IF NOT EXISTS session_checkpoints (
    id          SERIAL PRIMARY KEY,
    session_id  VARCHAR(64) NOT NULL,
    step_number INTEGER     NOT NULL,
    agent_state JSONB       NOT NULL,
    node_name   VARCHAR(100),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (session_id, step_number)
);
CREATE INDEX IF NOT EXISTS idx_sc_session ON session_checkpoints (session_id);

CREATE TABLE IF NOT EXISTS trip_history (
    id             SERIAL PRIMARY KEY,
    trip_id        VARCHAR(64) UNIQUE NOT NULL,
    destination    VARCHAR(200) NOT NULL,
    country        VARCHAR(100),
    start_date     DATE,
    end_date       DATE,
    budget_planned NUMERIC(10,2),
    budget_actual  NUMERIC(10,2),
    travel_style   VARCHAR(50),
    accommodation  VARCHAR(200),
    accom_type     VARCHAR(50),
    accom_rating   INTEGER CHECK (accom_rating BETWEEN 1 AND 5),
    activities     JSONB,
    highlights     TEXT,
    lowlights      TEXT,
    overall_rating INTEGER CHECK (overall_rating BETWEEN 1 AND 5),
    trip_summary   TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS travel_preferences (
    id         SERIAL PRIMARY KEY,
    pref_key   VARCHAR(100) UNIQUE NOT NULL,
    pref_value TEXT         NOT NULL,
    confidence NUMERIC(3,2) DEFAULT 0.50,
    source     VARCHAR(200),
    updated_at TIMESTAMPTZ  DEFAULT NOW()
);
"""


def init_db():
    """Create schema + tables if they don't exist."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(_DDL)
    conn.close()
    logger.info("Schema '%s' ready ✅", SCHEMA)


# ── Seed demo data ───────────────────────────────────────────────────────────

def seed_demo_data():
    """Wipe and re-populate 3 sample trips + 7 preferences for demo."""
    from memory import save_trip, save_preference, reset_all_memory

    reset_all_memory()

    save_trip(destination="Tokyo", country="Japan", start_date="2025-10-15", end_date="2025-10-22",
              budget_planned=1200, budget_actual=1085, travel_style="solo",
              accommodation="Hotel Sunroute Ginza", accom_type="boutique", accom_rating=4,
              activities=["Tsukiji food tour", "Meiji Shrine walk", "Yanaka Old Town", "Ramen tasting Shinjuku"],
              highlights="Tsukiji market food tour was incredible. Yanaka was peaceful and authentic.",
              lowlights="Shibuya Crossing was way too crowded. Akihabara felt overwhelming.",
              overall_rating=4,
              trip_summary="Great solo trip focused on food & culture. Boutique hotel in quiet Ginza was perfect.")

    save_trip(destination="Lisbon", country="Portugal", start_date="2025-06-01", end_date="2025-06-07",
              budget_planned=900, budget_actual=820, travel_style="couple",
              accommodation="Santiago de Alfama", accom_type="boutique", accom_rating=5,
              activities=["Alfama Fado & street food tour", "Belém Tower", "LX Factory brunch", "Tram 28"],
              highlights="Alfama street food tour was the highlight. Hotel was stunning. LX Factory was a hidden gem.",
              lowlights="Tram 28 was unbearably crowded. Belém area felt very touristy.",
              overall_rating=5,
              trip_summary="Perfect romantic trip. Boutique hotel in Alfama was the best. Food outstanding. Avoid Tram 28.")

    save_trip(destination="Rome", country="Italy", start_date="2025-08-10", end_date="2025-08-16",
              budget_planned=1100, budget_actual=1250, travel_style="couple",
              accommodation="NH Collection Roma Centro", accom_type="chain", accom_rating=3,
              activities=["Colosseum tour", "Vatican Museums", "Trastevere food tour", "Testaccio market"],
              highlights="Trastevere food tour was fantastic. Testaccio market felt authentic.",
              lowlights="Colosseum and Vatican were exhaustingly crowded in August. Chain hotel was bland. Over budget.",
              overall_rating=3,
              trip_summary="Rome in August was a mistake — too hot, too crowded. Chain hotel disappointing. Food saved the trip.")

    save_preference("accom_style", "boutique", 0.85, "Loved boutique in Tokyo (4/5) and Lisbon (5/5). Disliked chain in Rome (3/5).")
    save_preference("budget_per_night", "150", 0.70, "Avg across Tokyo ($135) and Lisbon ($130).")
    save_preference("activity_preference", "food + cultural", 0.85, "Rated food tours 5/5 in all 3 trips.")
    save_preference("avoid_crowds", "true", 0.75, "Mentioned 'too crowded' in Tokyo, Lisbon, Rome.")
    save_preference("dietary", "vegetarian-friendly", 0.50, "Chose veg options in Tokyo and Lisbon tours.")
    save_preference("travel_pace", "relaxed", 0.60, "Preferred Yanaka (quiet) over Akihabara (hectic).")
    save_preference("avoid_peak_season", "true", 0.65, "Rome in August rated 3/5 due to crowds + heat.")

    logger.info("Seeded 3 trips + 7 preferences ✅")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    seed_demo_data()
    print("✅ DB ready + demo data seeded")

