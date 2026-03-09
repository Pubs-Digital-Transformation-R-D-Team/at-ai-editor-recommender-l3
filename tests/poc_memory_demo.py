"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         PROOF OF CONCEPT — Session Memory & Long-term Memory               ║
║         Editor Assignment AI Agent — Memory Architecture                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

This script demonstrates the TWO new memory tiers added to the Editor 
Assignment Workflow. Run it and it shows exactly what happens.

NO Docker, NO Postgres, NO AWS needed. Uses in-memory backends.

Run:
    python tests/poc_memory_demo.py

What it demonstrates:
    DEMO 1: Session Memory — Checkpoint & Resume (survives pod crashes)
    DEMO 2: Session Memory — Full Audit Trail (every step is logged)
    DEMO 3: Long-term Memory — Store & Search past assignments
    DEMO 4: Full Workflow — Both memories working together in the real graph
"""

import asyncio
import os
import sys
import json
import logging

# Add src/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Force mock LLM (no AWS/Bedrock needed)
os.environ["MOCK_LLM_RESPONSE"] = "true"
os.environ.setdefault("EE_URL", "http://localhost:9999/mock")
os.environ.setdefault("ASSIGN_URL", "http://localhost:9999/mock/assign")
os.environ.setdefault("VALIDATE_ASSIGNMENT_URL", "http://localhost:9999/mock/validate")

logging.basicConfig(level=logging.WARNING)  # Keep demo output clean


def print_header(title):
    width = 72
    print()
    print("═" * width)
    print(f"  {title}")
    print("═" * width)


def print_step(text):
    print(f"  → {text}")


def print_ok(text):
    print(f"  ✅ {text}")


def print_warn(text):
    print(f"  ⚠️  {text}")


# ═══════════════════════════════════════════════════════════════════════════════
#  DEMO 1: Session Memory — What happens when a pod crashes mid-workflow?
# ═══════════════════════════════════════════════════════════════════════════════

async def demo_1_session_memory_checkpoint_resume():
    """
    BEFORE (no memory):
        Pod crashes → workflow is LOST → must restart from scratch
    
    AFTER (with session memory):
        Pod crashes → new pod loads checkpoint → resumes from last step
    """
    print_header("DEMO 1: Session Memory — Crash Recovery")
    print()
    print("  SCENARIO: Our workflow has 3 steps:")
    print("    Step 1: Fetch manuscript data from EE API")
    print("    Step 2: Ask Claude to recommend an editor")
    print("    Step 3: Execute the assignment via Assign API")
    print()
    print("  💥 Pod CRASHES after Step 2, before Step 3!")
    print("  🔄 New pod starts... can it resume?")
    print()

    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from typing import TypedDict

    class WorkflowState(TypedDict):
        manuscript_data: str
        recommended_editor: str
        assignment_result: str

    async def step1_fetch_data(state):
        return {"manuscript_data": "JACS-2026-001: Novel Catalysis Method"}

    async def step2_recommend_editor(state):
        return {"recommended_editor": "Dr. Alice Smith (person-12345)"}

    async def step3_execute_assignment(state):
        return {"assignment_result": "Dr. Alice Smith assigned successfully!"}

    def build_graph(checkpointer, interrupt_before=None):
        g = StateGraph(WorkflowState)
        g.add_node("fetch_data", step1_fetch_data)
        g.add_node("recommend_editor", step2_recommend_editor)
        g.add_node("execute_assignment", step3_execute_assignment)
        g.add_edge(START, "fetch_data")
        g.add_edge("fetch_data", "recommend_editor")
        g.add_edge("recommend_editor", "execute_assignment")
        g.add_edge("execute_assignment", END)
        kwargs = {"checkpointer": checkpointer}
        if interrupt_before:
            kwargs["interrupt_before"] = interrupt_before
        return g.compile(**kwargs)

    # This is the Postgres checkpointer in production. For demo, we use MemorySaver.
    checkpointer = MemorySaver()
    thread_id = "jacs-JACS-2026-001"
    config = {"configurable": {"thread_id": thread_id}}

    # ── Phase 1: Run until crash (interrupt before step 3) ──
    print_step("Phase 1: Running workflow... (pod will crash before Step 3)")
    graph = build_graph(checkpointer, interrupt_before=["execute_assignment"])
    result = await graph.ainvoke(
        {"manuscript_data": "", "recommended_editor": "", "assignment_result": ""},
        config
    )

    print(f"    manuscript_data:    '{result['manuscript_data']}'")
    print(f"    recommended_editor: '{result['recommended_editor']}'")
    print(f"    assignment_result:  '{result['assignment_result']}'  ← EMPTY (pod crashed!)")
    print()

    # ── Phase 2: New pod starts, resumes from checkpoint ──
    print_step("Phase 2: 🔄 New pod starts → loads checkpoint → resumes...")
    graph2 = build_graph(checkpointer)  # NEW graph instance (like a new pod)
    result2 = await graph2.ainvoke(None, config)  # None = resume from checkpoint

    print(f"    manuscript_data:    '{result2['manuscript_data']}'")
    print(f"    recommended_editor: '{result2['recommended_editor']}'")
    print(f"    assignment_result:  '{result2['assignment_result']}'")
    print()
    print_ok("Pod crashed and recovered! Workflow resumed from checkpoint — no data lost!")
    print()
    print("  📝 IN PRODUCTION: MemorySaver is replaced with AsyncPostgresSaver")
    print("     so checkpoints survive even if ALL pods die. Postgres holds the state.")


# ═══════════════════════════════════════════════════════════════════════════════
#  DEMO 2: Session Memory — Audit Trail
# ═══════════════════════════════════════════════════════════════════════════════

async def demo_2_audit_trail():
    """Every node creates a checkpoint. Full history of every decision."""
    print_header("DEMO 2: Session Memory — Audit Trail")
    print()
    print("  Every step in the workflow creates a checkpoint.")
    print("  This gives us a complete audit trail — compliance & debugging.")
    print()

    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from typing import TypedDict

    class AuditState(TypedDict):
        value: str

    async def fetch(state):
        return {"value": state["value"] + " → fetched_manuscript"}

    async def recommend(state):
        return {"value": state["value"] + " → recommended_editor"}

    async def assign(state):
        return {"value": state["value"] + " → assigned_editor"}

    checkpointer = MemorySaver()
    g = StateGraph(AuditState)
    g.add_node("fetch", fetch)
    g.add_node("recommend", recommend)
    g.add_node("assign", assign)
    g.add_edge(START, "fetch")
    g.add_edge("fetch", "recommend")
    g.add_edge("recommend", "assign")
    g.add_edge("assign", END)
    compiled = g.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "audit-demo"}}
    result = await compiled.ainvoke({"value": "START"}, config)

    print_step(f"Final result: '{result['value']}'")
    print()

    # Show the audit trail
    history = []
    async for state in compiled.aget_state_history(config):
        history.append(state)

    print_step(f"Audit trail has {len(history)} checkpoint entries:")
    print()
    for i, h in enumerate(reversed(history)):
        val = h.values.get("value", "(empty)")
        source = h.metadata.get("source", "?") if h.metadata else "?"
        marker = " ←── current" if i == len(history) - 1 else ""
        print(f"    Checkpoint {i}: [{source:5s}] '{val}'{marker}")

    print()
    print_ok(f"{len(history)} checkpoints recorded — every step is auditable!")
    print("  📝 Useful for: debugging failed assignments, compliance, performance analysis")


# ═══════════════════════════════════════════════════════════════════════════════
#  DEMO 3: Long-term Memory — Store & Search Past Assignments
# ═══════════════════════════════════════════════════════════════════════════════

async def demo_3_long_term_memory():
    """Store completed assignments and retrieve them later."""
    print_header("DEMO 3: Long-term Memory — Store & Search Past Assignments")
    print()
    print("  After each successful assignment, we store the result.")
    print("  Future workflows can query past assignments to make better decisions.")
    print()

    from langgraph.store.memory import InMemoryStore

    store = InMemoryStore()

    # Simulate saving 3 completed assignments
    assignments = [
        {
            "namespace": ("assignments", "JACS"),
            "key": "JACS-2026-001",
            "value": {
                "editor_person_id": "person-12345",
                "reasoning": "Expert in organic chemistry, catalysis, and synthesis. Strong track record with similar manuscripts.",
                "journal_id": "JACS",
                "manuscript_number": "JACS-2026-001",
                "topics": "organic chemistry, catalysis, synthesis",
                "timestamp": "2026-02-21T10:00:00Z",
            }
        },
        {
            "namespace": ("assignments", "JACS"),
            "key": "JACS-2026-002",
            "value": {
                "editor_person_id": "person-67890",
                "reasoning": "Specialist in machine learning applications for drug discovery and computational chemistry.",
                "journal_id": "JACS",
                "manuscript_number": "JACS-2026-002",
                "topics": "machine learning, drug discovery, computational chemistry",
                "timestamp": "2026-02-21T11:00:00Z",
            }
        },
        {
            "namespace": ("assignments", "OC"),
            "key": "OC-2026-001",
            "value": {
                "editor_person_id": "person-54321",
                "reasoning": "Expert in polymer science and nanomaterials. Excellent fit for materials-focused submissions.",
                "journal_id": "OC",
                "manuscript_number": "OC-2026-001",
                "topics": "polymer science, nanomaterials",
                "timestamp": "2026-02-21T12:00:00Z",
            }
        },
    ]

    print_step("Saving 3 completed assignments to long-term memory...")
    for a in assignments:
        await store.aput(namespace=a["namespace"], key=a["key"], value=a["value"])
    print()

    # Show what's stored
    for a in assignments:
        ns = "/".join(a["namespace"])
        print(f"    📦 {ns}/{a['key']}")
        print(f"       Editor: {a['value']['editor_person_id']}")
        print(f"       Topics: {a['value']['topics']}")
        print()

    # Retrieve by key
    print_step("Retrieving JACS-2026-001 by key...")
    item = await store.aget(namespace=("assignments", "JACS"), key="JACS-2026-001")
    print(f"    Found: editor={item.value['editor_person_id']}, reasoning='{item.value['reasoning'][:60]}...'")
    print()

    # Search by journal
    print_step("Searching all JACS assignments...")
    jacs = await store.asearch(("assignments", "JACS"))
    print(f"    Found {len(jacs)} JACS assignments:")
    for item in jacs:
        print(f"      → {item.key}: {item.value['editor_person_id']} ({item.value['topics']})")
    print()

    # Search all journals
    print_step("Searching ALL assignments across all journals...")
    all_items = await store.asearch(("assignments",))
    print(f"    Found {len(all_items)} total assignments")
    print()

    print_ok("Long-term memory stores and retrieves assignment history!")
    print("  📝 IN PRODUCTION: InMemoryStore is replaced with AsyncPostgresStore + pgvector")
    print("     which enables SEMANTIC SEARCH: 'Find editors who handled catalysis papers'")


# ═══════════════════════════════════════════════════════════════════════════════
#  DEMO 4: Real Workflow — Both Memories Working Together
# ═══════════════════════════════════════════════════════════════════════════════

async def demo_4_real_workflow():
    """Run the actual EditorAssignmentWorkflow with both memories."""
    print_header("DEMO 4: Real Workflow — Both Memories Together")
    print()
    print("  Running the ACTUAL EditorAssignmentWorkflow graph from ee_graph_anthropic.py")
    print("  with MOCK_LLM_RESPONSE=true (no AWS Bedrock needed)")
    print()
    print("  This is the SAME code that runs in production on EKS!")
    print()

    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.store.memory import InMemoryStore
    from at_ai_editor_recommender.ee_graph_anthropic import (
        EditorAssignmentWorkflow,
        ManuscriptSubmission,
    )

    checkpointer = MemorySaver()
    store = InMemoryStore()

    workflow = EditorAssignmentWorkflow(
        model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
        checkpointer=checkpointer,
        store=store,
    )

    # Patch external APIs (they're inside K8s cluster only)
    async def fake_fetch(self, state):
        return {
            "manuscript_information": "Title: Novel Catalysis\nAbstract: Breakthrough in organic synthesis...",
            "available_editors": "Editor 1: person-001 (Catalysis expert)\nEditor 2: person-002 (ML expert)",
        }

    async def fake_assign(self, ms, editor_id, state):
        pass  # Mock — no real API call

    original_fetch = EditorAssignmentWorkflow._fetch_manuscript_data
    original_assign = EditorAssignmentWorkflow._call_assign_api
    EditorAssignmentWorkflow._fetch_manuscript_data = fake_fetch
    EditorAssignmentWorkflow._call_assign_api = fake_assign
    workflow._graph = workflow._build_graph()

    try:
        # ── Process 3 manuscripts ──
        manuscripts = [
            ManuscriptSubmission("JACS-2026-001", "jacs", False),
            ManuscriptSubmission("JACS-2026-002", "jacs", False),
            ManuscriptSubmission("OC-2026-001", "oc", False),
        ]

        for ms in manuscripts:
            print_step(f"Processing {ms.journal_id}/{ms.manuscript_number}...")
            result = await workflow.async_execute_workflow(ms)
            # Get the node output
            for node_name, output in result.items():
                if isinstance(output, dict) and "editor_person_id" in output:
                    print(f"    Assigned editor: {output['editor_person_id']}")
                    print(f"    Reasoning: {output.get('reasoning', '')[:60]}...")
            print()

        # ── Check Session Memory (checkpoints) ──
        print_step("SESSION MEMORY — Checking checkpoints for each manuscript:")
        print()
        for ms in manuscripts:
            thread_id = f"{ms.journal_id}-{ms.manuscript_number}"
            config = {"configurable": {"thread_id": thread_id}}
            count = 0
            async for _ in workflow._graph.aget_state_history(config):
                count += 1
            print(f"    Thread '{thread_id}': {count} checkpoints ✅")
        print()

        # ── Check Long-term Memory (stored assignments) ──
        print_step("LONG-TERM MEMORY — Checking stored assignments:")
        print()
        jacs_items = await store.asearch(("assignments", "jacs"))
        oc_items = await store.asearch(("assignments", "oc"))
        all_items = await store.asearch(("assignments",))

        print(f"    JACS assignments saved: {len(jacs_items)}")
        print(f"    OC assignments saved:   {len(oc_items)}")
        print(f"    Total saved:            {len(all_items)}")
        print()
        for item in all_items:
            print(f"    📦 {item.key}: editor={item.value.get('editor_person_id', '?')}")

        print()
        print_ok("Both memories working together in the real workflow!")

    finally:
        EditorAssignmentWorkflow._fetch_manuscript_data = original_fetch
        EditorAssignmentWorkflow._call_assign_api = original_assign


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN — Run all demos in sequence
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║     PROOF OF CONCEPT — Editor Assignment AI Agent Memory Tiers      ║")
    print("║                                                                      ║")
    print("║     Tier 1: In-Context Memory  → LangGraph State (already existed)   ║")
    print("║     Tier 2: Session Memory     → Checkpointer + Postgres  [NEW]      ║")
    print("║     Tier 3: Long-term Memory   → Store + pgvector         [NEW]      ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    await demo_1_session_memory_checkpoint_resume()
    await demo_2_audit_trail()
    await demo_3_long_term_memory()
    await demo_4_real_workflow()

    print()
    print("═" * 72)
    print("  ALL DEMOS COMPLETE!")
    print("═" * 72)
    print()
    print("  Summary:")
    print("    ✅ Session Memory protects against pod crashes (checkpoint/resume)")
    print("    ✅ Full audit trail of every workflow step")
    print("    ✅ Long-term memory stores assignment history across runs")
    print("    ✅ Both memories integrate with the real EditorAssignmentWorkflow")
    print()
    print("  What's needed for production:")
    print("    1. Postgres instance (RDS or in-cluster)")
    print("    2. Set POSTGRES_URI environment variable")
    print("    3. The app auto-detects and enables memory — no code changes needed")
    print("    4. Without POSTGRES_URI, app runs in no-memory mode (backward compatible)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
