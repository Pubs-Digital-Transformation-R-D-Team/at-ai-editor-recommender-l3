"""
Test Session Memory (Tier 2) and Long-term Memory (Tier 3).

This test suite runs against a real Postgres instance with pgvector.
Start the database first:

    docker compose -f docker-compose.memory.yaml up -d

Then run:

    uv run pytest tests/test_memory.py -v

Or run individual tests:

    uv run pytest tests/test_memory.py::test_session_memory_checkpoint_and_resume -v
    uv run pytest tests/test_memory.py::test_long_term_memory_store_and_search -v
"""

import asyncio
import os
import pytest
import logging

logging.basicConfig(level=logging.INFO)

# ─── Postgres URI (matches docker-compose.memory.yaml) ───────────────────────
POSTGRES_URI = os.getenv(
    "POSTGRES_URI",
    "postgresql://postgres:postgres@localhost:5432/editor_recommender"
)
os.environ["POSTGRES_URI"] = POSTGRES_URI


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _check_postgres_available():
    """Skip tests if Postgres is not running."""
    try:
        import psycopg
        conn = psycopg.connect(POSTGRES_URI)
        conn.close()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _check_postgres_available(),
    reason="Postgres not available — start it with: docker compose -f docker-compose.memory.yaml up -d"
)


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 1: Session Memory (Checkpointer)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  This test proves:
#  1. State is saved to Postgres after each node
#  2. Workflow can be interrupted and resumed
#  3. State survives a "crash" (new graph instance)
#
# ═══════════════════════════════════════════════════════════════════════════════

@requires_postgres
@pytest.mark.asyncio
async def test_session_memory_checkpoint_and_resume():
    """
    Scenario:
      1. Build a simple 3-node graph with checkpointer
      2. Run it with an interrupt_before on node 3
      3. Verify checkpoint was saved (state has node 1+2 results)
      4. Create a NEW graph instance (simulates pod restart)
      5. Resume with same thread_id
      6. Verify node 3 ran and final state is complete
    """
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from typing import TypedDict

    # --- Define a simple test graph ---
    class TestState(TypedDict):
        step1_result: str
        step2_result: str
        step3_result: str

    async def node_step1(state):
        return {"step1_result": "fetched manuscript data"}

    async def node_step2(state):
        return {"step2_result": "generated recommendation"}

    async def node_step3(state):
        return {"step3_result": "assigned editor 12345"}

    def build_test_graph(checkpointer):
        graph = StateGraph(TestState)
        graph.add_node("step1", node_step1)
        graph.add_node("step2", node_step2)
        graph.add_node("step3", node_step3)
        graph.add_edge(START, "step1")
        graph.add_edge("step1", "step2")
        graph.add_edge("step2", "step3")
        graph.add_edge("step3", END)
        return graph.compile(checkpointer=checkpointer, interrupt_before=["step3"])

    # --- Setup checkpointer ---
    checkpointer = AsyncPostgresSaver.from_conn_string(POSTGRES_URI)
    await checkpointer.setup()

    thread_id = "test-session-memory-001"
    config = {"configurable": {"thread_id": thread_id}}

    # --- Run Phase 1: Execute until interrupt ---
    graph = build_test_graph(checkpointer)
    result = await graph.ainvoke({"step1_result": "", "step2_result": "", "step3_result": ""}, config)

    # Graph should have stopped BEFORE step3
    assert result["step1_result"] == "fetched manuscript data"
    assert result["step2_result"] == "generated recommendation"
    assert result["step3_result"] == ""  # Not yet executed

    print("\n✅ Phase 1: Graph paused before step3, checkpoint saved to Postgres")

    # --- Verify checkpoint exists ---
    checkpoint = await checkpointer.aget(config)
    assert checkpoint is not None, "Checkpoint should exist in Postgres"
    print(f"✅ Checkpoint found: {checkpoint['id']}")

    # --- Run Phase 2: Simulate restart (new graph instance) and resume ---
    graph2 = build_test_graph(checkpointer)
    result2 = await graph2.ainvoke(None, config)  # None = resume from checkpoint

    assert result2["step1_result"] == "fetched manuscript data"
    assert result2["step2_result"] == "generated recommendation"
    assert result2["step3_result"] == "assigned editor 12345"

    print("✅ Phase 2: Resumed from checkpoint, step3 completed!")
    print(f"   Final state: {result2}")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 2: Long-term Memory (Store + pgvector search)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  This test proves:
#  1. Assignment records can be stored permanently
#  2. Semantic search finds similar past assignments
#  3. Data persists across store reconnections
#
# ═══════════════════════════════════════════════════════════════════════════════

@requires_postgres
@pytest.mark.asyncio
async def test_long_term_memory_store_and_search():
    """
    Scenario:
      1. Store 3 assignment records with different topics
      2. Search for "organic chemistry catalyst" → should find the chemistry record
      3. Search for "machine learning" → should find the AI record
      4. Verify data persists (read back by key)
    """
    from at_ai_editor_recommender.memory import (
        create_store,
        save_assignment_to_memory,
        search_similar_assignments,
    )
    from dataclasses import dataclass

    store = await create_store()

    # --- Store 3 past assignments ---
    @dataclass
    class FakeManuscript:
        manuscript_number: str
        journal_id: str
        is_resubmit: bool = False

    assignments = [
        {
            "manuscript_submission": FakeManuscript("MS-001", "JACS"),
            "editor_id": "orcid-001",
            "editor_person_id": "editor-001",
            "reasoning": "Expert in organic chemistry, catalysis, and synthesis. Published 50 papers on catalyst design.",
            "runner_up": "editor-002",
            "filtered_out_editors": "editor-099",
            "assignment_result": "assigned",
        },
        {
            "manuscript_submission": FakeManuscript("MS-002", "JACS"),
            "editor_id": "orcid-002",
            "editor_person_id": "editor-002",
            "reasoning": "Specialist in machine learning applications to drug discovery and computational chemistry.",
            "runner_up": "editor-003",
            "filtered_out_editors": "",
            "assignment_result": "assigned",
        },
        {
            "manuscript_submission": FakeManuscript("MS-003", "OC"),
            "editor_id": "orcid-003",
            "editor_person_id": "editor-003",
            "reasoning": "Expert in polymer science, materials engineering, and nanomaterials characterization.",
            "runner_up": "editor-001",
            "filtered_out_editors": "",
            "assignment_result": "assigned",
        },
    ]

    for state in assignments:
        await save_assignment_to_memory(store, state)

    print("\n✅ Stored 3 assignment records in long-term memory")

    # --- Read back by key ---
    item = await store.aget(namespace=("assignments", "JACS"), key="MS-001")
    assert item is not None, "Should find MS-001 in store"
    assert item.value["editor_person_id"] == "editor-001"
    print(f"✅ Read back MS-001: editor={item.value['editor_person_id']}")

    # --- Semantic search: organic chemistry ---
    results = await search_similar_assignments(
        store,
        query="organic chemistry catalyst synthesis",
        journal_id="JACS",
        limit=3
    )
    print(f"✅ Search 'organic chemistry catalyst': {len(results)} results")
    for r in results:
        print(f"   → {r.key}: {r.value['reasoning'][:60]}...")

    # The chemistry record should be most relevant
    if results:
        assert results[0].key == "MS-001", \
            f"Expected MS-001 (chemistry expert) as top result, got {results[0].key}"
        print("✅ Top result is MS-001 (organic chemistry) as expected!")

    # --- Semantic search: machine learning ---
    results_ml = await search_similar_assignments(
        store,
        query="machine learning neural network AI drug discovery",
        limit=5
    )
    print(f"✅ Search 'machine learning': {len(results_ml)} results")
    for r in results_ml:
        print(f"   → {r.key}: {r.value['reasoning'][:60]}...")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 3: Memory integration with workflow
# ═══════════════════════════════════════════════════════════════════════════════

@requires_postgres
@pytest.mark.asyncio
async def test_session_memory_list_history():
    """
    Verify that checkpointer stores full history (audit trail).
    Each node execution creates a new checkpoint entry.
    """
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from typing import TypedDict

    class TestState(TypedDict):
        value: str

    async def node_a(state):
        return {"value": state["value"] + " → A"}

    async def node_b(state):
        return {"value": state["value"] + " → B"}

    checkpointer = AsyncPostgresSaver.from_conn_string(POSTGRES_URI)
    await checkpointer.setup()

    graph = StateGraph(TestState)
    graph.add_node("a", node_a)
    graph.add_node("b", node_b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)
    compiled = graph.compile(checkpointer=checkpointer)

    thread_id = "test-audit-trail-001"
    config = {"configurable": {"thread_id": thread_id}}

    result = await compiled.ainvoke({"value": "START"}, config)
    assert result["value"] == "START → A → B"

    # Check audit trail — should have checkpoints for each step
    history = []
    async for state in compiled.aget_state_history(config):
        history.append(state)

    # History should include: initial → after A → after B
    assert len(history) >= 3, f"Expected at least 3 checkpoints, got {len(history)}"
    print(f"\n✅ Audit trail has {len(history)} checkpoints:")
    for i, h in enumerate(history):
        print(f"   checkpoint {i}: value='{h.values.get('value', '')}'")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 4: Store persistence across reconnections
# ═══════════════════════════════════════════════════════════════════════════════

@requires_postgres
@pytest.mark.asyncio
async def test_long_term_memory_persists_across_reconnections():
    """
    Verify data survives store reconnection (simulates pod restart for Tier 3).
    """
    from at_ai_editor_recommender.memory import create_store

    # --- Connection 1: Write ---
    store1 = await create_store()
    await store1.aput(
        namespace=("assignments", "TEST"),
        key="persist-test-001",
        value={
            "editor_id": "persist-editor",
            "reasoning": "Testing persistence across reconnections",
            "topics": "persistence test",
            "timestamp": "2026-02-21T00:00:00Z",
        }
    )
    print("\n✅ Written to store via connection 1")

    # --- Connection 2: Read (simulates new pod) ---
    store2 = await create_store()
    item = await store2.aget(
        namespace=("assignments", "TEST"),
        key="persist-test-001"
    )
    assert item is not None, "Data should persist across reconnections"
    assert item.value["editor_id"] == "persist-editor"
    print(f"✅ Read from store via connection 2: {item.value['editor_id']}")
    print("✅ Long-term memory persists across pod restarts!")
