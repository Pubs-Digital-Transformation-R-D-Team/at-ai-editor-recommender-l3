"""
L3 Long-term Memory for Editor Assignment.

Stores completed assignments in Postgres so the LLM learns from past decisions.
Uses langgraph's AsyncPostgresStore (namespace + key-value).

Functions:
  create_store()          — init Postgres store
  save_assignment()       — L3 WRITE after each assignment
  search_assignments()    — L3 READ before each recommendation
  format_for_prompt()     — convert results to LLM-readable text
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _get_postgres_uri() -> str:
    return os.getenv("POSTGRES_URI", "postgresql://postgres:postgres@localhost:5432/editor_recommender")


async def create_store():
    """Create async Postgres-backed store for L3 memory."""
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from psycopg_pool import AsyncConnectionPool

    uri = _get_postgres_uri()
    pool = AsyncConnectionPool(conninfo=uri, max_size=5, open=False)
    await pool.open()
    store = AsyncPostgresStore(pool)
    await store.setup()
    logger.info("L3 memory ready")
    return store


async def save_assignment(store, state: dict) -> None:
    """Save completed assignment to L3 memory."""
    ms = state.get("manuscript_submission")
    if ms is None:
        logger.warning("No manuscript_submission — skip save")
        return

    journal = getattr(ms, "journal_id", "unknown")
    ms_num = getattr(ms, "manuscript_number", "unknown")

    try:
        await store.aput(
            namespace=("assignments", journal),
            key=ms_num,
            value={
                "editor_person_id": state.get("editor_person_id", ""),
                "reasoning": state.get("reasoning", ""),
                "runner_up": state.get("runner_up", ""),
                "filtered_out": state.get("filtered_out_editors", ""),
                "journal_id": journal,
                "manuscript_number": ms_num,
                "topics": state.get("reasoning", "")[:500],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info("L3 saved: %s → %s", ms_num, state.get("editor_person_id", "?"))
    except Exception as e:
        logger.error("L3 save failed: %s", e)


async def search_assignments(store, query: str, journal_id: Optional[str] = None, limit: int = 5) -> list:
    """Search L3 memory for similar past assignments."""
    try:
        ns = ("assignments", journal_id) if journal_id else ("assignments",)
        return await store.asearch(ns, query=query, limit=limit)
    except Exception as e:
        logger.error("L3 search failed: %s", e)
        return []


def format_for_prompt(results: list, max_results: int = 5) -> str:
    """Format past assignments into text the LLM can use."""
    if not results:
        return ""

    lines = ["## Past Assignments for Similar Manuscripts", ""]
    for i, item in enumerate(results[:max_results], 1):
        v = item.value if hasattr(item, "value") else item
        r = v.get("reasoning", "")
        lines.append(f"{i}. **{v.get('manuscript_number', '?')}** → Editor {v.get('editor_person_id', '?')}")
        lines.append(f"   Reasoning: {r[:200]}{'...' if len(r) > 200 else ''}")
        if v.get("runner_up"):
            lines.append(f"   Runner-up: {v['runner_up']}")
        lines.append("")
    return "\n".join(lines)

