"""
Memory module for Editor Assignment Workflow.

Implements two memory tiers from the architecture:

Tier 2 - SESSION MEMORY
    LangGraph Checkpointer + Postgres Master
    Survives restarts. Resumes after human approval. Audit trail.

Tier 3 - LONG-TERM MEMORY
    LangGraph Store + Postgres
    Lessons learned. Editor patterns. Key-value store (semantic search later).

Usage:
    from at_ai_editor_recommender.memory import create_checkpointer, create_store

    # Session memory (checkpointer)
    checkpointer = await create_checkpointer()

    # Long-term memory (store)
    store = await create_store()
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Database Connection ──────────────────────────────────────────────────────

def _get_postgres_uri() -> str:
    """Build Postgres connection URI from environment variables."""
    return os.getenv(
        "POSTGRES_URI",
        "postgresql://postgres:postgres@localhost:5432/editor_recommender"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  TIER 2: SESSION MEMORY — LangGraph Checkpointer + Postgres
# ═══════════════════════════════════════════════════════════════════════════════
#
#  What it does:
#    - Saves workflow state to Postgres AFTER EACH NODE executes
#    - If pod crashes mid-workflow, you can resume from last checkpoint
#    - Every run is identified by a unique thread_id
#    - Full audit trail of every step
#
#  How it works:
#    1. Graph runs node "fetch_manuscript_data"
#    2. Checkpointer saves State to Postgres → checkpoint_1
#    3. Graph runs node "generate_editor_recommendation"
#    4. Checkpointer saves State to Postgres → checkpoint_2
#    5. Pod crashes! 💥
#    6. Pod restarts, loads checkpoint_2 from Postgres
#    7. Graph resumes from "verify_recommendation" (next node)
#
# ═══════════════════════════════════════════════════════════════════════════════

async def create_checkpointer():
    """
    Create an async Postgres checkpointer for session memory.

    The checkpointer automatically saves LangGraph state after each node.
    Uses the `langgraph-checkpoint-postgres` package.

    Returns:
        AsyncPostgresSaver instance (used as `checkpointer` in graph.compile())

    Example:
        checkpointer = await create_checkpointer()
        graph = workflow_builder.compile(checkpointer=checkpointer)

        # Run with a thread_id to enable resume
        config = {"configurable": {"thread_id": "manuscript-MS12345"}}
        result = await graph.ainvoke(initial_state, config)

        # Later, resume from where it stopped:
        result = await graph.ainvoke(None, config)  # None = use saved state
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    uri = _get_postgres_uri()
    logger.info("Initializing Session Memory (Postgres Checkpointer) at %s", uri.split("@")[-1])

    # In langgraph-checkpoint-postgres v3.x, from_conn_string() returns an async
    # context manager. For long-lived FastAPI apps, we create the connection pool
    # ourselves and pass it to the checkpointer.
    pool = AsyncConnectionPool(
        conninfo=uri,
        max_size=5,
        open=False,  # We'll open it explicitly
    )
    await pool.open()

    checkpointer = AsyncPostgresSaver(pool)

    # Create the checkpoint tables if they don't exist
    await checkpointer.setup()
    logger.info("Session Memory ready — checkpoints will persist to Postgres")

    return checkpointer


# ═══════════════════════════════════════════════════════════════════════════════
#  TIER 3: LONG-TERM MEMORY — LangGraph Store + Postgres + pgvector
# ═══════════════════════════════════════════════════════════════════════════════
#
#  What it does:
#    - Stores completed assignment results permanently
#    - Uses pgvector for semantic search over past assignments
#    - Agent can query: "What editors worked well for AI + chemistry papers?"
#    - Stores lessons learned, editor preferences, patterns
#
#  How it works:
#    1. Workflow completes → editor assigned to manuscript
#    2. Store saves: {manuscript_topics, editor_id, reasoning, outcome}
#    3. Next workflow runs → queries store for similar past assignments
#    4. LLM uses past patterns to make better decisions
#
#  Storage structure (namespaced):
#    namespace = ("assignments", journal_id)
#    key = manuscript_number
#    value = {editor_id, reasoning, topics, timestamp, ...}
#
# ═══════════════════════════════════════════════════════════════════════════════

async def create_store():
    """
    Create an async Postgres-backed store for long-term memory.

    The store persists completed assignment data with vector embeddings
    for semantic search. Uses `langgraph-store-postgres` package.

    Returns:
        AsyncPostgresStore instance

    Example:
        store = await create_store()

        # Save a completed assignment
        await store.aput(
            namespace=("assignments", "JACS"),
            key="MS-12345",
            value={
                "editor_id": "130958",
                "reasoning": "Expert in organic chemistry...",
                "timestamp": "2026-02-21T10:30:00Z"
            }
        )

        # Search for similar past assignments
        results = await store.asearch(
            namespace_prefix=("assignments",),
            query="organic chemistry synthesis",
            limit=5
        )
    """
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from psycopg_pool import AsyncConnectionPool

    uri = _get_postgres_uri()
    logger.info("Initializing Long-term Memory (Postgres Store + pgvector) at %s", uri.split("@")[-1])

    # In langgraph v3.x, from_conn_string() returns an async context manager.
    # For long-lived FastAPI apps, we create the pool ourselves.
    pool = AsyncConnectionPool(
        conninfo=uri,
        max_size=5,
        open=False,
    )
    await pool.open()

    # For the POC, we use the store as a key-value store without vector
    # embeddings.  Semantic search (pgvector) will be enabled later once:
    #   1. The DBA enables the pgvector extension on RDS
    #   2. We configure an embedding model (e.g., Bedrock Titan)
    # Until then, aput / aget / alist work; asearch uses exact-match only.
    store = AsyncPostgresStore(pool)

    await store.setup()
    logger.info("Long-term Memory ready \u2014 assignments will persist to Postgres")

    return store


# ─── Helper: Save completed assignment to long-term memory ────────────────────

async def save_assignment_to_memory(store, state: dict) -> None:
    """
    Save a completed editor assignment to long-term memory.

    Called after a successful assignment. Stores the result with metadata
    so future workflows can query past patterns.

    Args:
        store: The AsyncPostgresStore instance
        state: The final LangGraph state dict after assignment
    """
    try:
        manuscript = state.get("manuscript_submission")
        if manuscript is None:
            logger.warning("No manuscript_submission in state — skipping memory save")
            return

        journal_id = getattr(manuscript, "journal_id", "unknown")
        manuscript_number = getattr(manuscript, "manuscript_number", "unknown")

        # Build the memory record
        memory_record = {
            "editor_id": state.get("editor_id", ""),
            "editor_person_id": state.get("editor_person_id", ""),
            "reasoning": state.get("reasoning", ""),
            "runner_up": state.get("runner_up", ""),
            "filtered_out_editors": state.get("filtered_out_editors", ""),
            "journal_id": journal_id,
            "manuscript_number": manuscript_number,
            "topics": _extract_topics_from_reasoning(state.get("reasoning", "")),
            "assignment_result": state.get("assignment_result", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Store under namespace ("assignments", journal_id)
        await store.aput(
            namespace=("assignments", journal_id),
            key=manuscript_number,
            value=memory_record,
        )

        logger.info(
            "Saved assignment to long-term memory: %s → editor %s",
            manuscript_number,
            state.get("editor_person_id", "unknown"),
        )

    except Exception as e:
        # Never let memory saves break the main workflow
        logger.error("Failed to save to long-term memory: %s", e, exc_info=True)


async def search_similar_assignments(store, query: str, journal_id: Optional[str] = None, limit: int = 5) -> list:
    """
    Search long-term memory for similar past assignments.

    Searches by namespace prefix and returns past assignments.
    (Semantic vector search will be added later with pgvector + Bedrock embeddings.)

    Args:
        store: The AsyncPostgresStore instance
        query: Text to search for (e.g., manuscript abstract or topics)
        journal_id: Optional journal filter. None = search all journals.
        limit: Max results to return

    Returns:
        List of past assignment records sorted by similarity

    Example:
        results = await search_similar_assignments(
            store,
            query="organic chemistry synthesis catalyst",
            journal_id="JACS",
            limit=3
        )
        for r in results:
            print(f"Editor {r.value['editor_id']} — {r.value['reasoning'][:80]}")
    """
    try:
        if journal_id:
            namespace_prefix = ("assignments", journal_id)
        else:
            namespace_prefix = ("assignments",)

        results = await store.asearch(
            namespace_prefix,
            query=query,
            limit=limit,
        )

        logger.info(
            "Long-term memory search returned %d results for query: %.60s...",
            len(results),
            query,
        )
        return results

    except Exception as e:
        logger.error("Long-term memory search failed: %s", e, exc_info=True)
        return []


def format_past_assignments_for_prompt(results: list, max_results: int = 5) -> str:
    """
    Format long-term memory search results into a text block for the LLM prompt.

    Converts raw store results into a readable section that the LLM can use
    to make better, data-driven editor recommendations based on past assignments.

    Args:
        results: List of store search results from search_similar_assignments()
        max_results: Maximum number of past assignments to include

    Returns:
        Formatted string to inject into the LLM prompt, or empty string if no results.

    Example output:
        ## Past Editor Assignments for Similar Manuscripts
        The following are past editor assignments for similar manuscripts in this journal.
        Use these as reference — they show which editors worked well for similar topics.

        1. Manuscript JACS-2026-00001
           - Assigned Editor: person-001
           - Reasoning: Expert in organic chemistry with strong catalysis background...
           - Topics: catalysis, organic chemistry, synthesis
           - Runner-up: person-002
    """
    if not results:
        return ""

    lines = []
    lines.append("## Past Editor Assignments for Similar Manuscripts")
    lines.append("The following are past editor assignments for similar manuscripts in this journal.")
    lines.append("Use these as additional context — they show which editors were previously assigned for similar topics.")
    lines.append("Do NOT blindly copy past assignments. Evaluate each manuscript on its own merits.")
    lines.append("")

    for i, item in enumerate(results[:max_results], 1):
        val = item.value if hasattr(item, 'value') else item
        manuscript_num = val.get("manuscript_number", "unknown")
        editor_id = val.get("editor_person_id", val.get("editor_id", "unknown"))
        reasoning = val.get("reasoning", "No reasoning recorded")
        topics = val.get("topics", "")
        runner_up = val.get("runner_up", "")
        timestamp = val.get("timestamp", "")

        lines.append(f"{i}. Manuscript {manuscript_num}")
        lines.append(f"   - Assigned Editor: {editor_id}")
        # Truncate reasoning to keep prompt size reasonable
        reasoning_short = reasoning[:200] + "..." if len(reasoning) > 200 else reasoning
        lines.append(f"   - Reasoning: {reasoning_short}")
        if topics:
            topics_short = topics[:150] + "..." if len(topics) > 150 else topics
            lines.append(f"   - Topics: {topics_short}")
        if runner_up:
            lines.append(f"   - Runner-up: {runner_up}")
        if timestamp:
            lines.append(f"   - Date: {timestamp[:10]}")
        lines.append("")

    return "\n".join(lines)


def _extract_topics_from_reasoning(reasoning: str) -> str:
    """
    Extract a topic summary from the LLM reasoning text.
    Simple heuristic — the LLM reasoning typically mentions research areas.
    """
    if not reasoning:
        return ""
    # Take first 500 chars as topic signal — the LLM reasoning
    # usually front-loads the topic analysis
    return reasoning[:500]
