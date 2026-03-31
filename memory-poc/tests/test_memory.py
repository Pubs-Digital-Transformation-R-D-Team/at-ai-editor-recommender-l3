"""
Memory POC tests — NO Docker, NO Postgres, NO AWS needed.
Run: cd memory-poc && pytest tests/ -v
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["MOCK_LLM_RESPONSE"] = "true"

from memory import save_assignment, search_assignments, format_for_prompt


class FakeMs:
    def __init__(self, num, journal):
        self.manuscript_number = num
        self.journal_id = journal


def _state(num, journal, editor, reasoning="Expert match"):
    return {
        "manuscript_submission": FakeMs(num, journal),
        "editor_person_id": editor,
        "reasoning": reasoning,
        "runner_up": "person-999",
        "filtered_out_editors": "",
    }


# ── L3 Save & Search ─────────────────────────────────────────────────────────

class TestL3Memory:
    @pytest.mark.asyncio
    async def test_save_and_retrieve(self):
        from langgraph.store.memory import InMemoryStore
        store = InMemoryStore()
        await save_assignment(store, _state("MS-1", "JACS", "p-001"))
        items = await store.asearch(("assignments", "JACS"))
        assert len(items) == 1
        assert items[0].value["editor_person_id"] == "p-001"

    @pytest.mark.asyncio
    async def test_multi_journal_isolation(self):
        from langgraph.store.memory import InMemoryStore
        store = InMemoryStore()
        await save_assignment(store, _state("MS-1", "JACS", "p-001"))
        await save_assignment(store, _state("MS-2", "OC", "p-002"))
        assert len(await store.asearch(("assignments", "JACS"))) == 1
        assert len(await store.asearch(("assignments", "OC"))) == 1

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        from langgraph.store.memory import InMemoryStore
        store = InMemoryStore()
        await save_assignment(store, _state("MS-1", "JACS", "p-001", "catalysis expert"))
        results = await search_assignments(store, "catalysis", journal_id="JACS")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_empty(self):
        from langgraph.store.memory import InMemoryStore
        store = InMemoryStore()
        assert await search_assignments(store, "anything", journal_id="JACS") == []

    @pytest.mark.asyncio
    async def test_skip_when_no_manuscript(self):
        from langgraph.store.memory import InMemoryStore
        store = InMemoryStore()
        await save_assignment(store, {"no_manuscript": True})
        assert len(await store.asearch(("assignments",))) == 0


# ── Prompt Formatting ────────────────────────────────────────────────────────

class TestFormatting:
    def test_empty(self):
        assert format_for_prompt([]) == ""

    def test_formats_results(self):
        class Item:
            def __init__(self, v): self.value = v
        items = [Item({"manuscript_number": "MS-1", "editor_person_id": "p-1", "reasoning": "Good fit"})]
        out = format_for_prompt(items)
        assert "MS-1" in out and "p-1" in out

    def test_truncates_long_reasoning(self):
        class Item:
            def __init__(self, v): self.value = v
        items = [Item({"manuscript_number": "X", "editor_person_id": "p", "reasoning": "A" * 500})]
        assert "..." in format_for_prompt(items)

    def test_max_results(self):
        class Item:
            def __init__(self, v): self.value = v
        items = [Item({"manuscript_number": f"MS-{i}", "editor_person_id": f"p-{i}", "reasoning": "r"}) for i in range(10)]
        out = format_for_prompt(items, max_results=3)
        assert "MS-0" in out
        assert "MS-5" not in out


# ── L2 Session Checkpoint ────────────────────────────────────────────────────

class TestL2Session:
    @pytest.mark.asyncio
    async def test_checkpoint_and_resume(self):
        from langgraph.graph import StateGraph, START, END
        from langgraph.checkpoint.memory import MemorySaver
        from typing import TypedDict

        class St(TypedDict):
            s1: str; s2: str; s3: str

        async def n1(s): return {"s1": "fetched"}
        async def n2(s): return {"s2": "recommended"}
        async def n3(s): return {"s3": "assigned"}

        def build(cp, interrupt=None):
            g = StateGraph(St)
            g.add_node("n1", n1); g.add_node("n2", n2); g.add_node("n3", n3)
            g.add_edge(START, "n1"); g.add_edge("n1", "n2")
            g.add_edge("n2", "n3"); g.add_edge("n3", END)
            kw = {"checkpointer": cp}
            if interrupt: kw["interrupt_before"] = interrupt
            return g.compile(**kw)

        cp = MemorySaver()
        cfg = {"configurable": {"thread_id": "t-001"}}

        # Phase 1: crash before n3
        r1 = await build(cp, ["n3"]).ainvoke({"s1": "", "s2": "", "s3": ""}, cfg)
        assert r1["s2"] == "recommended" and r1["s3"] == ""

        # Phase 2: resume
        r2 = await build(cp).ainvoke(None, cfg)
        assert r2["s3"] == "assigned"


# ── Agent (mock mode) ────────────────────────────────────────────────────────

class TestAgent:
    @pytest.mark.asyncio
    async def test_mock_execute(self):
        from langgraph.store.memory import InMemoryStore
        from agent import EditorAssignmentAgent, ManuscriptSubmission

        store = InMemoryStore()
        agent = EditorAssignmentAgent(store=store, model_id="us.amazon.nova-premier-v1:0")
        ms = ManuscriptSubmission("MS-TEST", "JACS")
        result = await agent.execute(ms)

        assert result["editor_person_id"] == "mock-person"
        assert result["reasoning"] == "Mock LLM response for testing"

        # Verify L3 was written
        items = await store.asearch(("assignments", "JACS"))
        assert len(items) == 1
        assert items[0].value["manuscript_number"] == "MS-TEST"

