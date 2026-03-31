"""
Tests for the LangGraph callback server (refactored modules)
─────────────────────────────────────────────────────────────
Tests are organised by module:

  1. editor_utils  — extract_editor_name, build_reasoning_points,
                     build_reasoning, editor_details
  2. agent_card    — Agent Card structure validation
  3. routes        — _parse_coi_response helper
  4. callback_server (app) — REST endpoints via ASGI test client

Imports use the *canonical* module paths (langgraph_service.editor_utils, etc.)
rather than the backward-compat re-exports in callback_server.py.
"""

import json
import pytest
import httpx

# Canonical imports from the refactored modules
from langgraph_service.editor_utils import (
    extract_editor_name,
    build_reasoning_points,
    build_reasoning,
    editor_details,
)
from langgraph_service.agent_card import AGENT_CARD
from langgraph_service.routes import _parse_coi_response

# The assembled Starlette app (entry point wires everything together)
from langgraph_service.callback_server import app


# ═══════════════════════════════════════════════════════════════════════════════
#  _extract_editor_name
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractEditorName:

    def test_standard_format(self):
        assert extract_editor_name("Get editor history for: Dr. Emily Jones") == "Dr. Emily Jones"

    def test_without_colon(self):
        result = extract_editor_name("Get editor history for Dr. Kevin Lee")
        assert result == "Dr. Kevin Lee"

    def test_case_insensitive(self):
        result = extract_editor_name("GET EDITOR HISTORY FOR: Dr. X")
        assert result == "Dr. X"

    def test_strips_quotes(self):
        assert extract_editor_name('Get editor history for: "Dr. A"') == "Dr. A"

    def test_plain_name_fallback(self):
        assert extract_editor_name("  Dr. Jones  ") == "Dr. Jones"

    def test_empty_string(self):
        assert extract_editor_name("  ") == ""


# ═══════════════════════════════════════════════════════════════════════════════
#  _build_reasoning_points
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildReasoningPoints:

    def test_good_capacity_no_coi_with_match(self):
        editor = {"expertise": ["polymer chemistry"], "current_load": 1, "max_load": 5}
        points = build_reasoning_points("Dr. A", editor, matched={"polymer chemistry"}, flagged_names=set())
        assert len(points) == 3
        assert any("polymer chemistry" in p for p in points)
        assert any("No conflict" in p for p in points)
        assert any("capacity" in p.lower() or "free" in p.lower() for p in points)

    def test_no_topic_overlap(self):
        editor = {"expertise": ["organic chemistry"], "current_load": 0, "max_load": 5}
        points = build_reasoning_points("Dr. B", editor, matched=set(), flagged_names=set())
        assert any("No direct topic overlap" in p for p in points)

    def test_at_capacity(self):
        editor = {"expertise": [], "current_load": 5, "max_load": 5}
        points = build_reasoning_points("Dr. C", editor, matched=set(), flagged_names=set())
        assert any("At capacity" in p or "no slots free" in p for p in points)

    def test_nearly_full(self):
        editor = {"expertise": [], "current_load": 4, "max_load": 5}
        points = build_reasoning_points("Dr. D", editor, matched=set(), flagged_names=set())
        assert any("Nearly full" in p or "1 slot" in p for p in points)

    def test_coi_flagged(self):
        editor = {"expertise": [], "current_load": 0, "max_load": 5}
        points = build_reasoning_points("Dr. E", editor, matched=set(), flagged_names={"Dr. E"})
        assert any("Conflict of interest" in p for p in points)


# ═══════════════════════════════════════════════════════════════════════════════
#  _build_reasoning
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildReasoning:

    def test_basic_reasoning_string(self):
        editor = {"expertise": ["catalysis"], "current_load": 2, "max_load": 5}
        result = build_reasoning("Dr. A", editor, matched={"catalysis"}, flagged_names=set())
        assert "catalysis" in result
        assert "No COI" in result
        assert "2/5" in result

    def test_flagged_editor(self):
        editor = {"expertise": [], "current_load": 0, "max_load": 5}
        result = build_reasoning("Dr. B", editor, matched=set(), flagged_names={"Dr. B"})
        assert "COI flagged" in result

    def test_no_match_general_relevance(self):
        editor = {"expertise": ["physics"], "current_load": 0, "max_load": 5}
        result = build_reasoning("Dr. C", editor, matched=set(), flagged_names=set())
        assert "general relevance" in result


# ═══════════════════════════════════════════════════════════════════════════════
#  _editor_details
# ═══════════════════════════════════════════════════════════════════════════════

class TestEditorDetails:

    def test_approved_editor_has_required_keys(self):
        coi_result = {"approved": ["Dr. Emily Jones"], "flagged": []}
        details = editor_details("Dr. Emily Jones", coi_result)
        required = {
            "name", "orcid", "person_id", "expertise", "current_load",
            "max_load", "coi_status", "coi_reason", "score", "composite_score",
            "reasoning", "reasoning_points", "topic_match",
        }
        assert required.issubset(details.keys())
        assert details["coi_status"] == "approved"
        assert details["coi_reason"] is None
        assert isinstance(details["composite_score"], float)

    def test_flagged_editor_shows_conflict(self):
        coi_result = {
            "approved": [],
            "flagged": [{"editor": "Dr. Emily Jones", "reason": "Co-authored with John Smith"}],
        }
        details = editor_details("Dr. Emily Jones", coi_result)
        assert details["coi_status"] == "flagged"
        assert "John Smith" in details["coi_reason"]

    def test_composite_score_in_range(self):
        coi_result = {"approved": ["Dr. Kevin Lee"], "flagged": []}
        details = editor_details("Dr. Kevin Lee", coi_result)
        assert 0 <= details["composite_score"] <= 100

    def test_unknown_editor_defaults(self):
        coi_result = {"approved": ["Dr. Nobody"], "flagged": []}
        details = editor_details("Dr. Nobody", coi_result)
        assert details["name"] == "Dr. Nobody"
        assert details["max_load"] == 5
        assert details["coi_status"] == "approved"


# ═══════════════════════════════════════════════════════════════════════════════
#  REST Endpoints (ASGI test client)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def async_client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class TestHealthEndpoint:

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, async_client):
        async with async_client as client:
            r = await client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestEditorsEndpoint:

    @pytest.mark.asyncio
    async def test_list_editors(self, async_client):
        async with async_client as client:
            r = await client.get("/editors")
        assert r.status_code == 200
        data = r.json()
        assert "editors" in data
        assert isinstance(data["editors"], list)
        assert len(data["editors"]) > 0

    @pytest.mark.asyncio
    async def test_editors_have_name_field(self, async_client):
        async with async_client as client:
            r = await client.get("/editors")
        for ed in r.json()["editors"]:
            assert "name" in ed


class TestManuscriptEndpoint:

    @pytest.mark.asyncio
    async def test_valid_manuscript(self, async_client):
        async with async_client as client:
            r = await client.get("/manuscript/MS-999")
        assert r.status_code == 200
        data = r.json()
        assert "title" in data
        assert "authors" in data

    @pytest.mark.asyncio
    async def test_invalid_manuscript_404(self, async_client):
        async with async_client as client:
            r = await client.get("/manuscript/NONEXISTENT")
        assert r.status_code == 404
        assert "error" in r.json()


class TestLegacyTasksSend:

    @pytest.mark.asyncio
    async def test_editor_history_request(self, async_client):
        payload = {
            "id": "test-001",
            "message": {
                "role": "user",
                "parts": [{"text": "Get editor history for: Dr. Emily Jones"}],
            },
        }
        async with async_client as client:
            r = await client.post("/tasks/send", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert "artifacts" in data
        # The artifact text should be parseable JSON with editor history
        artifact_text = data["artifacts"][0]["parts"][0]["text"]
        history = json.loads(artifact_text)
        assert "editor" in history or "coauthors" in history

    @pytest.mark.asyncio
    async def test_unknown_task_type(self, async_client):
        payload = {
            "id": "test-002",
            "message": {
                "role": "user",
                "parts": [{"text": "Do something random"}],
            },
        }
        async with async_client as client:
            r = await client.post("/tasks/send", json=payload)
        assert r.status_code == 200
        data = r.json()
        artifact_text = data["artifacts"][0]["parts"][0]["text"]
        parsed = json.loads(artifact_text)
        assert "error" in parsed


class TestFinalizeEndpoint:

    @pytest.mark.asyncio
    async def test_finalize_option_1(self, async_client):
        body = {
            "coi_result": {
                "approved": ["Dr. Kevin Lee", "Dr. Sarah Kim"],
                "flagged": [{"editor": "Dr. Emily Jones", "reason": "conflict"}],
            },
            "human_decision": "1",
        }
        async with async_client as client:
            r = await client.post("/finalize", json=body)
        assert r.status_code == 200
        data = r.json()
        assert data["selected_editor"]["name"] == "Dr. Kevin Lee"
        assert data["decision_label"].startswith("Approved")

    @pytest.mark.asyncio
    async def test_finalize_option_2_runner_up(self, async_client):
        body = {
            "coi_result": {
                "approved": ["Dr. Kevin Lee", "Dr. Sarah Kim"],
                "flagged": [],
            },
            "human_decision": "2",
        }
        async with async_client as client:
            r = await client.post("/finalize", json=body)
        data = r.json()
        assert data["selected_editor"]["name"] == "Dr. Sarah Kim"

    @pytest.mark.asyncio
    async def test_finalize_option_3_override(self, async_client):
        body = {
            "coi_result": {
                "approved": ["Dr. A"],
                "flagged": [{"editor": "Dr. B", "reason": "conflict"}],
            },
            "human_decision": "3",
        }
        async with async_client as client:
            r = await client.post("/finalize", json=body)
        data = r.json()
        assert data["selected_editor"]["name"] == "Dr. B"

    @pytest.mark.asyncio
    async def test_finalize_option_4_escalate(self, async_client):
        body = {
            "coi_result": {"approved": [], "flagged": []},
            "human_decision": "4",
        }
        async with async_client as client:
            r = await client.post("/finalize", json=body)
        data = r.json()
        assert data["selected_editor"]["name"] == "ESCALATED"
        assert "Escalated" in data["decision_label"]


# ═══════════════════════════════════════════════════════════════════════════════
#  AgentCard (agent_card.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentCard:

    def test_card_has_name(self):
        assert AGENT_CARD.name == "Editor Recommender (LangGraph)"

    def test_card_has_two_skills(self):
        assert len(AGENT_CARD.skills) == 2

    def test_card_skill_ids(self):
        ids = {s.id for s in AGENT_CARD.skills}
        assert ids == {"assign_editor", "editor_history"}

    def test_card_version(self):
        assert AGENT_CARD.version == "1.0.0"

    def test_card_streaming_disabled(self):
        assert AGENT_CARD.capabilities.streaming is False


# ═══════════════════════════════════════════════════════════════════════════════
#  _parse_coi_response (routes.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseCOIResponse:

    def test_clean_json(self):
        text = '{"approved": ["Dr. A"], "flagged": []}'
        result = _parse_coi_response(text)
        assert result["approved"] == ["Dr. A"]

    def test_with_thinking_block(self):
        text = '<thinking>reasoning...</thinking>{"approved": [], "flagged": [{"editor": "Dr. X", "reason": "conflict"}]}'
        result = _parse_coi_response(text)
        assert len(result["flagged"]) == 1

    def test_with_markdown_fences(self):
        text = 'Here is the result:\n```json\n{"approved": ["Dr. A"], "flagged": []}\n```'
        result = _parse_coi_response(text)
        assert result["approved"] == ["Dr. A"]

    def test_garbage_text_returns_empty(self):
        text = "This is not JSON at all"
        result = _parse_coi_response(text)
        assert result == {"approved": [], "flagged": []}

    def test_empty_string_returns_empty(self):
        result = _parse_coi_response("")
        assert result == {"approved": [], "flagged": []}


# ═══════════════════════════════════════════════════════════════════════════════
#  Backward-compat re-exports from callback_server.py
# ═══════════════════════════════════════════════════════════════════════════════

