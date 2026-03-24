"""
Strands COI Agent
──────────────────
A Strands Agent that performs conflict-of-interest checks.

It has ONE tool: get_editor_history
  → Makes an A2A callback to the LangGraph service (port 8000)
  → Returns editor publications and co-authors

The Strands LLM decides:
  - Which editors need history lookups
  - Whether a co-authorship constitutes a conflict
  - Final approved / flagged classification

This agent knows nothing about LangGraph — it just calls an HTTP endpoint.
"""

import json
import logging
import os
import re

import httpx
from strands import Agent, tool
from strands.models import BedrockModel

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-premier-v1:0")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
LANGGRAPH_URL = os.getenv("LANGGRAPH_CALLBACK_URL", "http://localhost:8000")

# ── Mock mode: bypass Bedrock (useful when AWS credentials are unavailable) ──
# Set MOCK_COI=true to enable. The agent still makes real A2A callbacks to
# LangGraph for editor history — only LLM reasoning is mocked.
MOCK_COI = os.getenv("MOCK_COI", "false").lower() in ("true", "1", "yes")

SYSTEM_PROMPT = (
    "You are a conflict-of-interest (COI) specialist for scientific peer review. "
    "Your job is to detect whether any candidate editors have a conflict of interest "
    "with the manuscript authors.\n\n"
    "A conflict exists if:\n"
    "  - The editor co-authored a paper with any manuscript author in the past 5 years\n"
    "  - The editor is at the same institution as any manuscript author\n"
    "  - The editor has a close personal/professional relationship with an author\n\n"
    "Process:\n"
    "  1. For EACH candidate editor, call get_editor_history to retrieve their publication history\n"
    "  2. Check if any manuscript authors appear in the editor's co-author list\n"
    "  3. Return a JSON object with:\n"
    '     - "approved": list of editor names with NO conflicts\n'
    '     - "flagged": list of objects {"editor": name, "reason": explanation}\n\n'
    "Return ONLY valid JSON. No markdown, no extra text."
)


# ─── Tool: get_editor_history ────────────────────────────────────────────────

@tool
def get_editor_history(editor_name: str) -> str:
    """
    Fetch the publication history and co-authors for a specific editor.
    Call this for each candidate editor to check for conflicts of interest.
    Returns JSON with fields: editor, publications, coauthors, recent_manuscripts_handled.

    Args:
        editor_name: The full name of the editor (e.g. "Dr. Emily Jones")
    """
    logger.info(
        "[Strands COI] Tool: get_editor_history called for: %s",
        editor_name,
    )

    # ── A2A callback to LangGraph ──────────────────────────────────────────
    payload = {
        "id": f"history-{editor_name.replace(' ', '-').lower()}",
        "message": {
            "role": "user",
            "parts": [{"text": f"Get editor history for: {editor_name}"}],
        },
    }

    logger.info("[Strands COI] → A2A POST %s/tasks/send (editor history callback)", LANGGRAPH_URL)

    try:
        response = httpx.post(
            f"{LANGGRAPH_URL}/tasks/send",
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        result_text = data["artifacts"][0]["parts"][0]["text"]
        history = json.loads(result_text)
        logger.info(
            "[Strands COI] ← LangGraph returned history for %s — coauthors: %s",
            editor_name,
            history.get("coauthors", []),
        )
        return json.dumps(history)

    except Exception as e:
        logger.error("[Strands COI] Failed to fetch editor history: %s", e)
        return json.dumps({
            "editor": editor_name,
            "error": str(e),
            "publications": [],
            "coauthors": [],
        })


# ─── Build the Strands COI Agent ─────────────────────────────────────────────

def build_coi_agent() -> Agent:
    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=REGION,
    )
    agent = Agent(
        model=model,
        tools=[get_editor_history],
        system_prompt=SYSTEM_PROMPT,
    )
    logger.info("[Strands COI] Agent initialized with model: %s", MODEL_ID)
    return agent


def run_coi_check(message: str) -> str:
    """
    Run the COI agent synchronously.
    Returns the agent's response text (JSON string with approved/flagged).

    If MOCK_COI=true, bypasses Bedrock and uses rule-based logic instead.
    The A2A callback to LangGraph for editor history still runs in both modes.
    """
    if MOCK_COI:
        return _run_coi_check_mock(message)

    agent = build_coi_agent()
    logger.info("[Strands COI] Starting COI analysis")
    result = agent(message)
    # Strands returns an AgentResult — extract clean JSON from text
    raw_text = str(result)
    response_text = _extract_json_from_text(raw_text)
    logger.info("[Strands COI] COI analysis complete: %s", response_text[:200])
    return response_text


def _extract_json_from_text(text: str) -> str:
    """Strip <thinking> blocks and extract the first JSON object from text."""
    clean = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL).strip()
    clean = re.sub(r'```(?:json)?', '', clean).strip()
    match = re.search(r'(\{.*\})', clean, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass
    return clean or text


# ─── Mock COI logic (no Bedrock) ─────────────────────────────────────────────

def _run_coi_check_mock(message: str) -> str:
    """
    Rule-based COI check that still makes real A2A callbacks to LangGraph.
    Parses authors and editors from the message, fetches editor history via
    the tool, and flags any editor whose co-author list overlaps with authors.

    Expected message format (from callback_server check_coi_only):
        Check conflicts of interest.
        Manuscript authors: ["Name A", "Name B"]
        Candidate editors: ["Dr. X", "Dr. Y"]
        ...
    """
    logger.info("[Strands COI - MOCK] Starting mock COI analysis")

    authors: list[str] = []
    editors: list[str] = []

    for line in message.splitlines():
        stripped = line.strip()
        # "Manuscript authors: [...]"
        if stripped.lower().startswith("manuscript authors:"):
            raw = stripped.split(":", 1)[1].strip()
            try:
                authors = json.loads(raw)
            except json.JSONDecodeError:
                authors = [a.strip().strip('"') for a in raw.strip("[]").split(",") if a.strip()]
        # "Candidate editors: [...]"
        elif stripped.lower().startswith("candidate editors:"):
            raw = stripped.split(":", 1)[1].strip()
            try:
                editors = json.loads(raw)
            except json.JSONDecodeError:
                editors = [e.strip().strip('"') for e in raw.strip("[]").split(",") if e.strip()]

    logger.info("[Strands COI - MOCK] Manuscript authors: %s", authors)
    logger.info("[Strands COI - MOCK] Candidate editors: %s", editors)

    # ── Fetch history for each editor via A2A callback ────────────────────
    approved: list[str] = []
    flagged: list[dict] = []

    for editor in editors:
        history_json = get_editor_history(editor)
        try:
            history = json.loads(history_json)
        except json.JSONDecodeError:
            history = {}

        coauthors: list[str] = history.get("coauthors", [])
        logger.info(
            "[Strands COI - MOCK] %s coauthors: %s", editor, coauthors
        )

        # Overlap check (case-insensitive)
        coauthors_lower = {c.lower() for c in coauthors}
        conflicts = [
            a for a in authors if a.lower() in coauthors_lower
        ]

        if conflicts:
            reason = (
                f"Co-authorship conflict with manuscript author(s): "
                + ", ".join(conflicts)
            )
            flagged.append({"editor": editor, "reason": reason})
            logger.info("[Strands COI - MOCK] FLAGGED %s — %s", editor, reason)
        else:
            approved.append(editor)
            logger.info("[Strands COI - MOCK] APPROVED %s — no conflicts", editor)

    result = {"approved": approved, "flagged": flagged}
    logger.info("[Strands COI - MOCK] Result: %s", result)
    return json.dumps(result)
