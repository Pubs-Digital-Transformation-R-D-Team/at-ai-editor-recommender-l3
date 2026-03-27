"""
Tests for strands_service/coi_agent.py and strands_service/agent_card.py
────────────────────────────────────────────────────────────────────────
Covers:
  - _extract_json_from_text — JSON parsing helper
  - _run_coi_check_mock — rule-based COI detection
  - Message parsing (authors and editors extraction)
  - Mock mode behavior
  - Strands Agent Card structure
"""

import json
from unittest.mock import patch, MagicMock

import pytest
from strands_service.coi_agent import (
    _extract_json_from_text,
    _run_coi_check_mock,
    SYSTEM_PROMPT,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  _extract_json_from_text
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractJsonFromText:

    def test_clean_json(self):
        text = '{"approved": ["Dr. A"], "flagged": []}'
        result = _extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed["approved"] == ["Dr. A"]

    def test_json_with_markdown_fences(self):
        text = '```json\n{"approved": ["Dr. A"], "flagged": []}\n```'
        result = _extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed["approved"] == ["Dr. A"]

    def test_json_with_thinking_block(self):
        text = (
            '<thinking>Let me analyze the editors...</thinking>'
            '{"approved": ["Dr. A"], "flagged": []}'
        )
        result = _extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed["approved"] == ["Dr. A"]

    def test_json_with_surrounding_text(self):
        text = 'Here is my analysis:\n{"approved": [], "flagged": [{"editor": "Dr. B", "reason": "conflict"}]}\nDone.'
        result = _extract_json_from_text(text)
        parsed = json.loads(result)
        assert len(parsed["flagged"]) == 1

    def test_no_json_returns_original(self):
        text = "This has no JSON at all"
        result = _extract_json_from_text(text)
        assert result == text

    def test_empty_string(self):
        result = _extract_json_from_text("")
        assert result == ""


# ═══════════════════════════════════════════════════════════════════════════════
#  _run_coi_check_mock
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunCoiCheckMock:
    """Tests for the rule-based mock COI detection.
    
    These mock the get_editor_history tool to avoid real HTTP calls.
    """

    @patch("strands_service.coi_agent.get_editor_history")
    def test_detects_coauthor_conflict(self, mock_history):
        """Dr. Emily Jones co-authored with John Smith → should be flagged."""
        mock_history.side_effect = lambda name: json.dumps({
            "editor": name,
            "publications": [],
            "coauthors": ["John Smith"] if "Jones" in name else [],
        })

        message = (
            "Check conflicts of interest.\n"
            'Manuscript authors: ["John Smith", "Jane Doe"]\n'
            'Candidate editors: ["Dr. Emily Jones", "Dr. Kevin Lee"]'
        )
        result = json.loads(_run_coi_check_mock(message))

        assert "Dr. Kevin Lee" in result["approved"]
        assert len(result["flagged"]) == 1
        assert result["flagged"][0]["editor"] == "Dr. Emily Jones"
        assert "John Smith" in result["flagged"][0]["reason"]

    @patch("strands_service.coi_agent.get_editor_history")
    def test_no_conflicts_all_approved(self, mock_history):
        mock_history.return_value = json.dumps({
            "editor": "Dr. A",
            "publications": [],
            "coauthors": ["Unrelated Person"],
        })

        message = (
            "Check conflicts of interest.\n"
            'Manuscript authors: ["Alice", "Bob"]\n'
            'Candidate editors: ["Dr. A", "Dr. B"]'
        )
        result = json.loads(_run_coi_check_mock(message))

        assert len(result["approved"]) == 2
        assert len(result["flagged"]) == 0

    @patch("strands_service.coi_agent.get_editor_history")
    def test_all_editors_flagged(self, mock_history):
        mock_history.return_value = json.dumps({
            "editor": "Dr. A",
            "publications": [],
            "coauthors": ["Alice"],
        })

        message = (
            "Check conflicts of interest.\n"
            'Manuscript authors: ["Alice"]\n'
            'Candidate editors: ["Dr. A", "Dr. B"]'
        )
        result = json.loads(_run_coi_check_mock(message))

        assert len(result["approved"]) == 0
        assert len(result["flagged"]) == 2

    @patch("strands_service.coi_agent.get_editor_history")
    def test_case_insensitive_coauthor_match(self, mock_history):
        mock_history.return_value = json.dumps({
            "editor": "Dr. A",
            "publications": [],
            "coauthors": ["john smith"],
        })

        message = (
            "Check conflicts of interest.\n"
            'Manuscript authors: ["John Smith"]\n'
            'Candidate editors: ["Dr. A"]'
        )
        result = json.loads(_run_coi_check_mock(message))

        assert len(result["flagged"]) == 1

    @patch("strands_service.coi_agent.get_editor_history")
    def test_empty_coauthors(self, mock_history):
        mock_history.return_value = json.dumps({
            "editor": "Dr. A",
            "publications": [],
            "coauthors": [],
        })

        message = (
            "Check conflicts of interest.\n"
            'Manuscript authors: ["Alice"]\n'
            'Candidate editors: ["Dr. A"]'
        )
        result = json.loads(_run_coi_check_mock(message))

        assert result["approved"] == ["Dr. A"]
        assert result["flagged"] == []

    @patch("strands_service.coi_agent.get_editor_history")
    def test_malformed_json_authors(self, mock_history):
        """Test fallback parsing when authors are not valid JSON."""
        mock_history.return_value = json.dumps({
            "editor": "Dr. A",
            "publications": [],
            "coauthors": [],
        })

        message = (
            "Check conflicts of interest.\n"
            "Manuscript authors: Alice, Bob\n"
            'Candidate editors: ["Dr. A"]'
        )
        result = json.loads(_run_coi_check_mock(message))
        # Should still parse and not crash
        assert isinstance(result["approved"], list)

    @patch("strands_service.coi_agent.get_editor_history")
    def test_returns_valid_json(self, mock_history):
        mock_history.return_value = json.dumps({
            "editor": "Dr. X",
            "publications": [],
            "coauthors": [],
        })

        message = (
            "Check conflicts of interest.\n"
            'Manuscript authors: ["Alice"]\n'
            'Candidate editors: ["Dr. X"]'
        )
        result_str = _run_coi_check_mock(message)
        # Must be valid JSON
        parsed = json.loads(result_str)
        assert "approved" in parsed
        assert "flagged" in parsed


# ═══════════════════════════════════════════════════════════════════════════════
#  SYSTEM_PROMPT
# ═══════════════════════════════════════════════════════════════════════════════

class TestSystemPrompt:

    def test_prompt_not_empty(self):
        assert len(SYSTEM_PROMPT) > 100

    def test_prompt_mentions_coi(self):
        assert "conflict" in SYSTEM_PROMPT.lower()

    def test_prompt_mentions_json_output(self):
        assert "JSON" in SYSTEM_PROMPT

    def test_prompt_mentions_approved_and_flagged(self):
        assert "approved" in SYSTEM_PROMPT
        assert "flagged" in SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════════════════════════
#  Strands Agent Card (agent_card.py)
# ═══════════════════════════════════════════════════════════════════════════════

from strands_service.agent_card import AGENT_CARD as STRANDS_AGENT_CARD


class TestStrandsAgentCard:

    def test_card_has_name(self):
        assert STRANDS_AGENT_CARD.name == "COI Checker (Strands)"

    def test_card_has_one_skill(self):
        assert len(STRANDS_AGENT_CARD.skills) == 1

    def test_card_skill_id(self):
        assert STRANDS_AGENT_CARD.skills[0].id == "check_conflicts"

    def test_card_version(self):
        assert STRANDS_AGENT_CARD.version == "1.0.0"

    def test_card_streaming_disabled(self):
        assert STRANDS_AGENT_CARD.capabilities.streaming is False

    def test_card_description_mentions_coi(self):
        assert "conflict" in STRANDS_AGENT_CARD.description.lower()


# ═══════════════════════════════════════════════════════════════════════════════
#  Strands server.py — health endpoint
# ═══════════════════════════════════════════════════════════════════════════════

import httpx
from strands_service.server import app as strands_app


@pytest.fixture
def strands_client():
    transport = httpx.ASGITransport(app=strands_app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class TestStrandsHealthEndpoint:

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, strands_client):
        async with strands_client as client:
            r = await client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["service"] == "strands-coi-checker"

