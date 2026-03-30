"""
L2 + L3 Memory — read/write helpers for Postgres.
───────────────────────────────────────────────────
L2: session_checkpoints  — save/load/list/delete
L3: trip_history         — save/search/get_all
L3: travel_preferences   — save/get_all/get_one/delete
"""

import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal

from db import execute_query, execute_insert

logger = logging.getLogger(__name__)


# ─── JSON serialiser for Postgres types ───────────────────────────────────────

def _json_serial(obj):
    """Serialise date / datetime / Decimal for json.dumps."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def to_json(obj) -> str:
    return json.dumps(obj, default=_json_serial, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
#  L2: SESSION MEMORY
# ═══════════════════════════════════════════════════════════════════════════════

def save_checkpoint(session_id: str, step_number: int,
                    state: dict, node_name: str = "") -> None:
    """Upsert a session checkpoint (L2 WRITE)."""
    execute_insert(
        """
        INSERT INTO session_checkpoints (session_id, step_number, agent_state, node_name)
        VALUES (%s, %s, %s::jsonb, %s)
        ON CONFLICT (session_id, step_number)
        DO UPDATE SET agent_state = EXCLUDED.agent_state,
                      node_name   = EXCLUDED.node_name,
                      created_at  = NOW()
        """,
        (session_id, step_number, json.dumps(state), node_name),
    )
    logger.info("L2 checkpoint saved: session=%s step=%s node=%s",
                session_id, step_number, node_name)


def load_latest_checkpoint(session_id: str) -> dict | None:
    """Load the most recent checkpoint for a session (L2 READ)."""
    rows = execute_query(
        """
        SELECT step_number, agent_state, node_name, created_at
        FROM session_checkpoints
        WHERE session_id = %s
        ORDER BY step_number DESC
        LIMIT 1
        """,
        (session_id,),
    )
    if rows:
        row = rows[0]
        logger.info("L2 checkpoint loaded: session=%s step=%s", session_id, row["step_number"])
        return {
            "step_number": row["step_number"],
            "state": row["agent_state"],
            "node_name": row["node_name"],
            "saved_at": row["created_at"].isoformat() if row["created_at"] else "",
        }
    logger.info("L2 no checkpoint found for session=%s", session_id)
    return None


def list_checkpoints(session_id: str) -> list[dict]:
    """List all checkpoints for a session, ordered by step (L2 READ)."""
    return execute_query(
        """
        SELECT step_number, node_name, created_at
        FROM session_checkpoints
        WHERE session_id = %s
        ORDER BY step_number ASC
        """,
        (session_id,),
    )


def delete_session(session_id: str) -> None:
    """Delete all checkpoints for a session."""
    execute_insert(
        "DELETE FROM session_checkpoints WHERE session_id = %s",
        (session_id,),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  L3: LONG-TERM MEMORY — Trip History
# ═══════════════════════════════════════════════════════════════════════════════

def save_trip(
    destination: str,
    country: str = "",
    start_date: str = "",
    end_date: str = "",
    budget_planned: float = 0,
    budget_actual: float = 0,
    travel_style: str = "",
    accommodation: str = "",
    accom_type: str = "",
    accom_rating: int = 0,
    activities: list | None = None,
    highlights: str = "",
    lowlights: str = "",
    overall_rating: int = 0,
    trip_summary: str = "",
) -> str:
    """Save a completed trip to long-term memory (L3 WRITE). Returns trip_id."""
    trip_id = f"trip-{uuid.uuid4().hex[:8]}"
    execute_insert(
        """
        INSERT INTO trip_history
            (trip_id, destination, country, start_date, end_date,
             budget_planned, budget_actual, travel_style,
             accommodation, accom_type, accom_rating,
             activities, highlights, lowlights,
             overall_rating, trip_summary)
        VALUES (%s,%s,%s,%s,%s, %s,%s,%s, %s,%s,%s, %s::jsonb,%s,%s, %s,%s)
        """,
        (
            trip_id, destination, country or None,
            start_date or None, end_date or None,
            budget_planned or None, budget_actual or None,
            travel_style or None,
            accommodation or None, accom_type or None,
            accom_rating or None,
            json.dumps(activities or []),
            highlights or None, lowlights or None,
            overall_rating or None, trip_summary or None,
        ),
    )
    logger.info("L3 trip saved: %s → %s (rating=%s)", trip_id, destination, overall_rating)
    return trip_id


def search_trips(query: str, limit: int = 5) -> list[dict]:
    """Search past trips by keyword — destination, country, highlights, activities (L3 READ)."""
    q = f"%{query}%"
    return execute_query(
        """
        SELECT trip_id, destination, country, start_date, end_date,
               budget_actual, travel_style, accommodation, accom_type,
               accom_rating, activities, highlights, lowlights,
               overall_rating, trip_summary, created_at
        FROM trip_history
        WHERE destination   ILIKE %s
           OR country       ILIKE %s
           OR highlights    ILIKE %s
           OR lowlights     ILIKE %s
           OR trip_summary  ILIKE %s
           OR activities::text ILIKE %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (q, q, q, q, q, q, limit),
    )


def get_all_trips() -> list[dict]:
    """Return every trip in long-term memory, newest first."""
    return execute_query(
        """
        SELECT trip_id, destination, country, start_date, end_date,
               budget_actual, travel_style, accommodation, accom_type,
               accom_rating, activities, highlights, lowlights,
               overall_rating, trip_summary, created_at
        FROM trip_history
        ORDER BY created_at DESC
        """
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  L3: LONG-TERM MEMORY — Travel Preferences
# ═══════════════════════════════════════════════════════════════════════════════

def save_preference(
    pref_key: str,
    pref_value: str,
    confidence: float = 0.5,
    source: str = "",
) -> None:
    """Upsert a traveler preference (L3 WRITE).  Confidence only goes UP."""
    execute_insert(
        """
        INSERT INTO travel_preferences (pref_key, pref_value, confidence, source)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (pref_key) DO UPDATE SET
            pref_value = EXCLUDED.pref_value,
            confidence = GREATEST(travel_preferences.confidence, EXCLUDED.confidence),
            source     = EXCLUDED.source,
            updated_at = NOW()
        """,
        (pref_key, pref_value, confidence, source or None),
    )
    logger.info("L3 preference saved: %s = %s (%.2f)", pref_key, pref_value, confidence)


def get_all_preferences() -> list[dict]:
    """Load all known preferences, highest confidence first (L3 READ)."""
    return execute_query(
        """
        SELECT pref_key, pref_value, confidence, source, updated_at
        FROM travel_preferences
        ORDER BY confidence DESC
        """
    )


def get_preference(key: str) -> dict | None:
    """Get a single preference by key."""
    rows = execute_query(
        "SELECT pref_key, pref_value, confidence, source FROM travel_preferences WHERE pref_key = %s",
        (key,),
    )
    return rows[0] if rows else None


def delete_preference(key: str) -> None:
    execute_insert("DELETE FROM travel_preferences WHERE pref_key = %s", (key,))


# ── Bulk reset (for demo) ────────────────────────────────────────────────────

def reset_all_memory() -> None:
    """Wipe all 3 tables — for demo resets."""
    execute_insert("DELETE FROM session_checkpoints")
    execute_insert("DELETE FROM trip_history")
    execute_insert("DELETE FROM travel_preferences")
    logger.info("All memory wiped  🗑️")



