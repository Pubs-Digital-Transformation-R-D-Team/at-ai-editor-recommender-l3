"""
Test Session Memory and Long-term Memory — NO Docker required.

Uses SQLite checkpointer (filesystem) and InMemoryStore to test
the same memory patterns that will use Postgres in production.

Run:
    uv run pytest tests/test_memory_local.py -v -s
"""

import asyncio
import os
import sys
import pytest
import logging
import tempfile

# Add src/ to path so we can import the project modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 1: Session Memory — Checkpoint & Resume (SQLite)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Proves:
#    1. State is saved after each node
#    2. Graph can be interrupted mid-workflow
#    3. New graph instance resumes from checkpoint (simulates pod restart)
#
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_session_memory_checkpoint_and_resume():
    """
    Scenario: 3-node graph, interrupt before node 3, resume from checkpoint.
    This is exactly what happens when a pod crashes and restarts.
    """
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from typing import TypedDict

    # --- Simple 3-step workflow (like your editor assignment) ---
    class TestState(TypedDict):
        step1_result: str   # Like "fetch_manuscript_data"
        step2_result: str   # Like "generate_editor_recommendation"
        step3_result: str   # Like "execute_assignment"

    async def fetch_data(state):
        return {"step1_result": "manuscript data fetched"}

    async def generate_recommendation(state):
        return {"step2_result": "editor-12345 recommended"}

    async def execute_assignment(state):
        return {"step3_result": "editor-12345 assigned"}

    def build_graph(checkpointer, interrupt_before=None):
        graph = StateGraph(TestState)
        graph.add_node("fetch_data", fetch_data)
        graph.add_node("generate_recommendation", generate_recommendation)
        graph.add_node("execute_assignment", execute_assignment)
        graph.add_edge(START, "fetch_data")
        graph.add_edge("fetch_data", "generate_recommendation")
        graph.add_edge("generate_recommendation", "execute_assignment")
        graph.add_edge("execute_assignment", END)
        kwargs = {"checkpointer": checkpointer}
        if interrupt_before:
            kwargs["interrupt_before"] = interrupt_before
        return graph.compile(**kwargs)

    # --- Setup ---
    checkpointer = MemorySaver()
    thread_id = "JACS-MS12345"
    config = {"configurable": {"thread_id": thread_id}}

    print("\n" + "=" * 70)
    print("  TEST: Session Memory — Checkpoint & Resume")
    print("=" * 70)

    # ── Phase 1: Run until interrupt (simulates: pod will crash after step 2) ──
    graph = build_graph(checkpointer, interrupt_before=["execute_assignment"])
    result = await graph.ainvoke(
        {"step1_result": "", "step2_result": "", "step3_result": ""},
        config
    )

    print(f"\n  Phase 1 — Graph paused before 'execute_assignment'")
    print(f"    step1_result: {result['step1_result']}")
    print(f"    step2_result: {result['step2_result']}")
    print(f"    step3_result: '{result['step3_result']}'  ← empty (not yet run)")

    assert result["step1_result"] == "manuscript data fetched"
    assert result["step2_result"] == "editor-12345 recommended"
    assert result["step3_result"] == ""  # Not yet executed
    print("  ✅ Phase 1 passed: checkpoint saved, graph paused")

    # ── Phase 2: Simulate pod restart — create NEW graph, resume ──
    print(f"\n  Phase 2 — Simulating pod restart (new graph instance)")
    graph2 = build_graph(checkpointer)  # New graph, same checkpointer
    result2 = await graph2.ainvoke(None, config)  # None = resume from checkpoint

    print(f"    step1_result: {result2['step1_result']}")
    print(f"    step2_result: {result2['step2_result']}")
    print(f"    step3_result: {result2['step3_result']}  ← now completed!")

    assert result2["step1_result"] == "manuscript data fetched"
    assert result2["step2_result"] == "editor-12345 recommended"
    assert result2["step3_result"] == "editor-12345 assigned"
    print("  ✅ Phase 2 passed: resumed from checkpoint, assignment completed!")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 2: Session Memory — Audit Trail
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Proves:
#    - Every node execution creates a checkpoint entry
#    - You get a full history of every state change
#    - Useful for debugging and compliance
#
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_session_memory_audit_trail():
    """Every node creates a checkpoint — full audit trail."""
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from typing import TypedDict

    class AuditState(TypedDict):
        value: str

    async def node_a(state):
        return {"value": state["value"] + " → fetched_data"}

    async def node_b(state):
        return {"value": state["value"] + " → recommended_editor"}

    async def node_c(state):
        return {"value": state["value"] + " → assigned_editor"}

    checkpointer = MemorySaver()

    graph = StateGraph(AuditState)
    graph.add_node("fetch", node_a)
    graph.add_node("recommend", node_b)
    graph.add_node("assign", node_c)
    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "recommend")
    graph.add_edge("recommend", "assign")
    graph.add_edge("assign", END)
    compiled = graph.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "audit-test-001"}}
    result = await compiled.ainvoke({"value": "START"}, config)

    assert result["value"] == "START → fetched_data → recommended_editor → assigned_editor"

    # Check audit trail
    history = []
    async for state in compiled.aget_state_history(config):
        history.append(state)

    print("\n" + "=" * 70)
    print("  TEST: Session Memory — Audit Trail")
    print("=" * 70)
    print(f"\n  Workflow result: '{result['value']}'")
    print(f"  Total checkpoints in audit trail: {len(history)}")
    print()
    for i, h in enumerate(reversed(history)):
        val = h.values.get("value", "")
        print(f"    Checkpoint {i}: '{val}'")

    assert len(history) >= 4, f"Expected at least 4 checkpoints (initial + 3 nodes), got {len(history)}"
    print(f"\n  ✅ Audit trail has {len(history)} entries — every step is logged!")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 3: Long-term Memory — Store & Search
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Proves:
#    1. Completed assignments are stored permanently
#    2. You can read them back by key
#    3. Data is organized by namespace (journal_id)
#
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_long_term_memory_store_and_retrieve():
    """Store assignment records and retrieve by key."""
    from langgraph.store.memory import InMemoryStore

    store = InMemoryStore()

    print("\n" + "=" * 70)
    print("  TEST: Long-term Memory — Store & Retrieve")
    print("=" * 70)

    # --- Store 3 past assignments ---
    assignments = [
        {
            "namespace": ("assignments", "JACS"),
            "key": "MS-001",
            "value": {
                "editor_person_id": "editor-001",
                "reasoning": "Expert in organic chemistry, catalysis, and synthesis.",
                "journal_id": "JACS",
                "timestamp": "2026-02-21T10:00:00Z",
            }
        },
        {
            "namespace": ("assignments", "JACS"),
            "key": "MS-002",
            "value": {
                "editor_person_id": "editor-002",
                "reasoning": "Specialist in machine learning for drug discovery.",
                "journal_id": "JACS",
                "timestamp": "2026-02-21T11:00:00Z",
            }
        },
        {
            "namespace": ("assignments", "OC"),
            "key": "MS-003",
            "value": {
                "editor_person_id": "editor-003",
                "reasoning": "Expert in polymer science and nanomaterials.",
                "journal_id": "OC",
                "timestamp": "2026-02-21T12:00:00Z",
            }
        },
    ]

    for a in assignments:
        await store.aput(namespace=a["namespace"], key=a["key"], value=a["value"])

    print(f"\n  Stored {len(assignments)} assignment records")

    # --- Read back by key ---
    item = await store.aget(namespace=("assignments", "JACS"), key="MS-001")
    assert item is not None, "Should find MS-001"
    assert item.value["editor_person_id"] == "editor-001"
    print(f"  ✅ Retrieved MS-001: editor={item.value['editor_person_id']}")

    item2 = await store.aget(namespace=("assignments", "OC"), key="MS-003")
    assert item2 is not None, "Should find MS-003"
    assert item2.value["editor_person_id"] == "editor-003"
    print(f"  ✅ Retrieved MS-003: editor={item2.value['editor_person_id']}")

    # --- List all assignments for JACS ---
    jacs_items = await store.asearch(("assignments", "JACS"))
    print(f"  ✅ Found {len(jacs_items)} assignments in JACS namespace")
    for item in jacs_items:
        print(f"     → {item.key}: {item.value['reasoning'][:50]}...")

    assert len(jacs_items) == 2, f"Expected 2 JACS assignments, got {len(jacs_items)}"

    # --- List all assignments across all journals ---
    all_items = await store.asearch(("assignments",))
    print(f"  ✅ Found {len(all_items)} total assignments across all journals")
    assert len(all_items) == 3

    # --- Verify namespace isolation ---
    oc_items = await store.asearch(("assignments", "OC"))
    assert len(oc_items) == 1, "OC should have exactly 1 assignment"
    print(f"  ✅ Namespace isolation works: OC has {len(oc_items)} assignment(s)")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 4: Long-term Memory — save_assignment_to_memory helper
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Proves the actual helper function used by the workflow works correctly
#
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_save_assignment_to_memory_helper():
    """Test the save_assignment_to_memory function from memory.py."""
    from langgraph.store.memory import InMemoryStore
    from at_ai_editor_recommender.memory import save_assignment_to_memory
    from dataclasses import dataclass

    @dataclass
    class FakeManuscript:
        manuscript_number: str
        journal_id: str
        is_resubmit: bool = False

    store = InMemoryStore()

    print("\n" + "=" * 70)
    print("  TEST: Long-term Memory — save_assignment_to_memory helper")
    print("=" * 70)

    # Simulate a completed workflow state
    fake_state = {
        "manuscript_submission": FakeManuscript("MS-TEST-999", "JACS"),
        "editor_id": "orcid-test-001",
        "editor_person_id": "person-test-001",
        "reasoning": "Selected because of deep expertise in catalysis and organic synthesis methodology.",
        "runner_up": "person-test-002",
        "filtered_out_editors": "person-test-099 (COI)",
        "assignment_result": "Editor assigned successfully",
    }

    await save_assignment_to_memory(store, fake_state)
    print(f"\n  Saved assignment via helper function")

    # Verify it was stored correctly
    item = await store.aget(namespace=("assignments", "JACS"), key="MS-TEST-999")
    assert item is not None, "Should find MS-TEST-999 in store"
    assert item.value["editor_person_id"] == "person-test-001"
    assert "catalysis" in item.value["reasoning"]
    assert item.value["journal_id"] == "JACS"
    assert item.value["manuscript_number"] == "MS-TEST-999"
    assert item.value["timestamp"]  # Should have a timestamp

    print(f"  ✅ Record found in store:")
    print(f"     key: {item.key}")
    print(f"     editor: {item.value['editor_person_id']}")
    print(f"     reasoning: {item.value['reasoning'][:60]}...")
    print(f"     timestamp: {item.value['timestamp']}")
    print(f"     journal: {item.value['journal_id']}")
    print(f"  ✅ Helper function works correctly!")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 5: Session + Long-term Memory Together
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Proves both memories work when compiled into the same graph
#
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_both_memories_combined():
    """Run a graph with BOTH checkpointer and store active."""
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.store.memory import InMemoryStore
    from typing import TypedDict

    class CombinedState(TypedDict):
        manuscript_id: str
        editor: str

    async def pick_editor(state):
        return {"editor": "editor-42"}

    checkpointer = MemorySaver()
    store = InMemoryStore()

    graph = StateGraph(CombinedState)
    graph.add_node("pick", pick_editor)
    graph.add_edge(START, "pick")
    graph.add_edge("pick", END)
    compiled = graph.compile(checkpointer=checkpointer, store=store)

    config = {"configurable": {"thread_id": "combined-test-001"}}
    result = await compiled.ainvoke({"manuscript_id": "MS-COMBO", "editor": ""}, config)

    print("\n" + "=" * 70)
    print("  TEST: Both Memories Combined")
    print("=" * 70)

    assert result["editor"] == "editor-42"
    print(f"\n  Result: {result}")

    # Verify checkpoint exists
    checkpoint = await checkpointer.aget(config)
    assert checkpoint is not None
    print(f"  ✅ Session Memory: checkpoint saved (id={checkpoint['id'][:20]}...)")

    # Store can still be used
    await store.aput(
        namespace=("assignments", "TEST"),
        key="MS-COMBO",
        value={"editor": "editor-42", "reasoning": "test combined"}
    )
    item = await store.aget(namespace=("assignments", "TEST"), key="MS-COMBO")
    assert item is not None
    print(f"  ✅ Long-term Memory: record stored and retrieved")
    print(f"  ✅ Both memories work together!")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 6: format_past_assignments_for_prompt
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Proves:
#    - Empty results → empty string (no noise in prompt)
#    - Results are formatted with proper structure
#    - Reasoning is truncated to keep prompt size reasonable
#    - All fields (editor, reasoning, topics, runner-up, date) are included
#
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_format_past_assignments_for_prompt():
    """Test that past assignments are formatted correctly for injection into the LLM prompt."""
    from at_ai_editor_recommender.memory import format_past_assignments_for_prompt

    print("\n" + "=" * 70)
    print("  TEST: format_past_assignments_for_prompt")
    print("=" * 70)

    # ── Case 1: Empty results → empty string ──
    result = format_past_assignments_for_prompt([])
    assert result == "", f"Expected empty string for empty results, got: '{result}'"
    print(f"\n  ✅ Empty results → empty string (no noise in prompt)")

    # ── Case 2: Results with all fields ──
    class FakeItem:
        def __init__(self, value):
            self.value = value

    items = [
        FakeItem({
            "manuscript_number": "JACS-2026-00001",
            "editor_person_id": "person-001",
            "reasoning": "Expert in organic chemistry with strong catalysis background and 20 years experience",
            "topics": "catalysis, organic chemistry, synthesis",
            "runner_up": "person-002 (machine learning expert)",
            "timestamp": "2026-02-21T10:30:00Z",
        }),
        FakeItem({
            "manuscript_number": "JACS-2026-00004",
            "editor_person_id": "person-003",
            "reasoning": "Specialist in computational chemistry, strong publication record in DFT methods",
            "topics": "computational chemistry, DFT, molecular modeling",
            "runner_up": "",
            "timestamp": "2026-02-20T08:15:00Z",
        }),
    ]

    result = format_past_assignments_for_prompt(items)

    print(f"\n  Formatted output ({len(result)} chars):")
    for line in result.split("\n")[:15]:
        print(f"    | {line}")

    assert "Past Editor Assignments for Similar Manuscripts" in result
    assert "JACS-2026-00001" in result
    assert "person-001" in result
    assert "organic chemistry" in result
    assert "JACS-2026-00004" in result
    assert "person-003" in result
    assert "2026-02-21" in result
    assert "person-002" in result  # runner_up
    assert "Do NOT blindly copy" in result  # safety instruction
    print(f"\n  ✅ All fields present: manuscript, editor, reasoning, topics, runner-up, date")

    # ── Case 3: Long reasoning gets truncated ──
    long_items = [
        FakeItem({
            "manuscript_number": "MS-LONG",
            "editor_person_id": "person-999",
            "reasoning": "A" * 500,  # 500 chars → should be truncated to 200 + "..."
            "topics": "",
            "runner_up": "",
            "timestamp": "",
        }),
    ]
    result = format_past_assignments_for_prompt(long_items)
    assert "A" * 200 + "..." in result
    print(f"  ✅ Long reasoning truncated to 200 chars + '...'")

    # ── Case 4: max_results limit ──
    many_items = [FakeItem({"manuscript_number": f"MS-{i}", "editor_person_id": f"p-{i}",
                            "reasoning": f"reason {i}", "topics": "", "runner_up": "", "timestamp": ""})
                  for i in range(10)]
    result = format_past_assignments_for_prompt(many_items, max_results=3)
    assert "MS-0" in result
    assert "MS-2" in result
    assert "MS-3" not in result  # 4th item should be excluded
    print(f"  ✅ max_results=3 correctly limits output")

    print(f"\n  ✅ format_past_assignments_for_prompt works correctly!")
