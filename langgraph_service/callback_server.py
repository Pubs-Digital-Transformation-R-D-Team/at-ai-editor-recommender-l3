"""
LangGraph A2A Callback Server (port 8000)
─────────────────────────────────────────
Exposes two things:
  GET  /.well-known/agent.json  →  LangGraph Agent Card (A2A discovery)
  POST /tasks/send              →  Handles A2A tasks from Strands:
                                   - "Get editor history for <name>"
  POST /run-workflow            →  Full editor assignment demo (A2A + COI)

This server runs in the background so that the Strands COI agent can call
back to LangGraph mid-processing to fetch editor publication history.

The main editor assignment workflow is NOT served here — it is driven
directly by run_poc.py to allow HITL (interrupt/resume) in the terminal.
"""

import json
import logging
import os
import sys

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field
from typing import Optional

# Allow importing fake_data from parent poc/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import fake_data  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[LangGraph:8000] %(message)s",
)
logger = logging.getLogger(__name__)

STRANDS_URL = os.getenv("STRANDS_COI_URL", "http://localhost:8001")

app = FastAPI(
    title="LangGraph Editor Recommender",
    description=(
        "## L3 Multi-Agent Orchestration POC\n\n"
        "This service is the **LangGraph orchestrator** in a bidirectional A2A architecture:\n\n"
        "```\n"
        "  LangGraph (8000) ←──── A2A callback ────── Strands COI (8001)\n"
        "       │                                            ↑\n"
        "       └──────── A2A task (COI check) ─────────────┘\n"
        "```\n\n"
        "### Endpoints\n"
        "| Endpoint | Purpose |\n"
        "|----------|---------|\n"
        "| `GET /.well-known/agent.json` | A2A Agent Card discovery |\n"
        "| `POST /tasks/send` | A2A callback — serves editor history to Strands |\n"
        "| `POST /run-workflow` | Full demo: load manuscript → COI → recommendation |\n"
        "| `GET /editors` | List all available editors |\n"
        "| `GET /manuscript/{number}` | Get manuscript details |\n"
    ),
    version="1.0.0",
)


# ─── A2A data models ────────────────────────────────────────────────────────

class Part(BaseModel):
    text: str = Field(..., examples=["Get editor history for: Dr. Emily Jones"])


class Message(BaseModel):
    role: str = Field(default="user", examples=["user"])
    parts: list[Part]


class TaskRequest(BaseModel):
    id: str = Field(default="task-001", examples=["history-dr-jones"])
    message: Message

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Get editor history (A2A callback from Strands)",
                    "value": {
                        "id": "history-dr-jones",
                        "message": {
                            "role": "user",
                            "parts": [{"text": "Get editor history for: Dr. Emily Jones"}],
                        },
                    },
                }
            ]
        }
    }


class TaskStatus(BaseModel):
    state: str = "completed"


class ArtifactPart(BaseModel):
    text: str


class Artifact(BaseModel):
    parts: list[ArtifactPart]


class TaskResponse(BaseModel):
    id: str
    status: TaskStatus
    artifacts: list[Artifact]


# ─── Agent Card ─────────────────────────────────────────────────────────────

AGENT_CARD = {
    "name": "Editor Recommender (LangGraph)",
    "description": (
        "Assigns peer-review editors to manuscripts. "
        "Also provides editor publication history for COI checks."
    ),
    "url": "http://localhost:8000",
    "version": "1.0.0",
    "skills": [
        {
            "id": "assign_editor",
            "name": "Assign Editor",
            "description": "Full editor assignment workflow for a manuscript",
        },
        {
            "id": "editor_history",
            "name": "Editor Publication History",
            "description": (
                "Returns publications and co-authors for a given editor. "
                "Used by COI checker to detect conflicts."
            ),
        },
    ],
}


@app.get("/.well-known/agent.json")
async def agent_card():
    logger.info("Agent Card requested")
    return AGENT_CARD


# ─── Task handler ────────────────────────────────────────────────────────────

@app.post("/tasks/send", response_model=TaskResponse)
async def handle_task(request: TaskRequest):
    message_text = request.message.parts[0].text
    logger.info("Received task: %s", message_text[:120])

    # Strands COI agent calls this endpoint with:
    # "Get editor history for: Dr. Emily Jones"
    if "editor history" in message_text.lower() or "get history" in message_text.lower():
        editor_name = _extract_editor_name(message_text)
        logger.info("Serving editor history for: %s", editor_name)
        history = fake_data.get_editor_history(editor_name)
        result_text = json.dumps(history, indent=2)
        logger.info(
            "Editor history returned — coauthors: %s",
            history.get("coauthors", []),
        )
        return TaskResponse(
            id=request.id,
            status=TaskStatus(state="completed"),
            artifacts=[Artifact(parts=[ArtifactPart(text=result_text)])],
        )

    # Unknown task
    logger.warning("Unknown task type received: %s", message_text[:80])
    return TaskResponse(
        id=request.id,
        status=TaskStatus(state="failed"),
        artifacts=[Artifact(parts=[ArtifactPart(text="Unknown task type")])],
    )


def _extract_editor_name(text: str) -> str:
    """Parse 'Get editor history for: Dr. Emily Jones' → 'Dr. Emily Jones'"""
    for separator in ["for:", "for "]:
        if separator in text.lower():
            idx = text.lower().index(separator) + len(separator)
            return text[idx:].strip().strip('"').strip("'")
    return text.strip()


# ─── Browse data endpoints ────────────────────────────────────────────────────

@app.get(
    "/editors",
    summary="List all candidate editors",
    description="Returns all available editors with their expertise and current workload.",
    tags=["Browse Data"],
)
async def list_editors():
    return {"editors": list(fake_data.EDITORS.values())}


@app.get(
    "/manuscript/{manuscript_number}",
    summary="Get manuscript details",
    description=(
        "Returns full manuscript information.\n\n"
        "**Available manuscript:** `MS-999`"
    ),
    tags=["Browse Data"],
)
async def get_manuscript(manuscript_number: str = "MS-999"):
    try:
        return fake_data.get_manuscript(manuscript_number)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/editor-history/{editor_name}",
    summary="Get editor publication history",
    description=(
        "Returns publication history and co-authors for an editor.\n\n"
        "**Available editors:** `Dr. Emily Jones`, `Dr. Kevin Lee`, `Dr. Maria Smith`"
    ),
    tags=["Browse Data"],
)
async def get_editor_history(editor_name: str = "Dr. Emily Jones"):
    return fake_data.get_editor_history(editor_name)


# ─── Full workflow endpoint ───────────────────────────────────────────────────

class WorkflowRequest(BaseModel):
    manuscript_number: str = Field(
        default="MS-999",
        description="Manuscript number to process",
        examples=["MS-999"],
    )
    auto_approve: bool = Field(
        default=True,
        description=(
            "If True, auto-selects first approved editor when a conflict is found "
            "(simulates HITL 'option 1'). If False, forces assignment of flagged editor "
            "regardless (simulates override)."
        ),
        examples=[True],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Run full workflow for MS-999 (auto-approve)",
                    "value": {"manuscript_number": "MS-999", "auto_approve": True},
                }
            ]
        }
    }


@app.post(
    "/run-workflow",
    summary="▶ Run full editor assignment workflow (A2A + COI + HITL sim)",
    description=(
        "Runs the complete editor assignment pipeline:\n\n"
        "1. **Load manuscript** — fetches MS-999 from fake data\n"
        "2. **A2A COI check** — calls Strands COI service (`localhost:8001`) via A2A\n"
        "3. **Strands A2A callback** — Strands calls back to THIS server for each editor's history\n"
        "4. **HITL decision** — if conflict found, `auto_approve=true` selects an approved editor\n"
        "5. **Final assignment** — returns selected editor with reasoning\n\n"
        "This demonstrates the **bidirectional A2A flow** and **HITL simulation**.\n\n"
        "> ⚡ Requires the Strands COI server to be running on port 8001."
    ),
    tags=["Workflow"],
)
async def run_workflow(request: WorkflowRequest):
    ms_number = request.manuscript_number

    # ── Step 1: Load manuscript ───────────────────────────────────────────────
    try:
        ms = fake_data.get_manuscript(ms_number)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))

    authors = ms["authors"]
    editors = [e["name"] for e in fake_data.EDITORS.values()]
    logger.info("[Workflow] Loaded manuscript %s — authors: %s", ms_number, authors)

    # ── Step 2: A2A call to Strands COI service ───────────────────────────────
    coi_message = (
        f"Check conflicts of interest.\n"
        f"Manuscript authors: {json.dumps(authors)}\n"
        f"Candidate editors: {json.dumps(editors)}\n"
        f"For each editor, fetch their publication history and identify any co-authorship "
        f"or recent collaboration with the manuscript authors."
    )
    coi_payload = {
        "id": f"coi-{ms_number}",
        "message": {"role": "user", "parts": [{"text": coi_message}]},
    }

    logger.info("[Workflow] → A2A POST to Strands COI service")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            coi_resp = await client.post(f"{STRANDS_URL}/tasks/send", json=coi_payload)
            coi_resp.raise_for_status()
    except httpx.ConnectError:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail=f"Strands COI service is not running at {STRANDS_URL}. "
                   "Start it with: MOCK_COI=true python strands_service/server.py",
        )

    coi_data = coi_resp.json()
    coi_text = coi_data["artifacts"][0]["parts"][0]["text"]

    try:
        import re
        clean = re.sub(r'<thinking>.*?</thinking>', '', coi_text, flags=re.DOTALL)
        match = re.search(r'(\{.*\})', clean, re.DOTALL)
        coi_result = json.loads(match.group(1)) if match else json.loads(coi_text)
    except (json.JSONDecodeError, AttributeError):
        coi_result = {"raw": coi_text, "approved": [], "flagged": []}

    logger.info("[Workflow] ← COI result: %s", coi_result)

    # ── Step 3: HITL decision ─────────────────────────────────────────────────
    approved = coi_result.get("approved", [])
    flagged = coi_result.get("flagged", [])
    hitl_triggered = len(flagged) > 0

    if hitl_triggered and request.auto_approve and approved:
        selected_editor_name = approved[0]
        hitl_decision = "option_1_auto_approved"
    elif hitl_triggered and not request.auto_approve:
        fe = flagged[0]
        selected_editor_name = fe if isinstance(fe, str) else fe.get("editor")
        hitl_decision = "option_2_override"
    elif approved:
        selected_editor_name = approved[0]
        hitl_decision = "no_conflict_auto"
    else:
        selected_editor_name = "ESCALATED"
        hitl_decision = "option_3_escalate"

    # Look up full editor record
    selected_editor = next(
        (e for e in fake_data.EDITORS.values() if e["name"] == selected_editor_name),
        {"name": selected_editor_name, "id": "N/A", "person_id": "N/A"},
    )
    runner_up = approved[1] if len(approved) > 1 else (approved[0] if approved and approved[0] != selected_editor_name else "N/A")

    # ── Step 4: Build response ────────────────────────────────────────────────
    return {
        "manuscript": {
            "number": ms_number,
            "title": ms["title"],
            "authors": authors,
        },
        "coi_check": {
            "a2a_call": f"POST {STRANDS_URL}/tasks/send",
            "strands_callback": "POST http://localhost:8000/tasks/send (called by Strands for each editor)",
            "approved": approved,
            "flagged": flagged,
        },
        "hitl": {
            "triggered": hitl_triggered,
            "decision": hitl_decision,
            "note": (
                "In run_poc.py this pauses the graph and prompts the user. "
                "Here it is simulated automatically."
            ),
        },
        "final_assignment": {
            "editor_name": selected_editor["name"],
            "orcid": selected_editor.get("id", "N/A"),
            "person_id": selected_editor.get("person_id", "N/A"),
            "runner_up": runner_up,
        },
    }


# ─── Streamlit UI endpoints ──────────────────────────────────────────────────
# These split the workflow into two phases so the Streamlit UI can render
# the HITL decision panel between Phase 1 (COI check) and Phase 2 (finalize).


class COICheckOnlyRequest(BaseModel):
    manuscript_number: str = Field(
        default="MS-999",
        description="Manuscript number to run the COI check for",
        examples=["MS-999"],
    )


class FinalizeRequest(BaseModel):
    manuscript_number: str = Field(default="MS-999", examples=["MS-999"])
    human_decision: str = Field(
        description=(
            "'1' = assign first approved editor, "
            "'2' = assign second approved editor, "
            "'3' = override (assign flagged editor), "
            "'4' = escalate"
        ),
        examples=["1"],
    )
    coi_result: dict = Field(
        description="The coi_result object returned by /check-coi",
    )


def _editor_details(editor_name: str, coi_result: dict) -> dict:
    """Enrich an editor record with COI status and topic-match reasoning."""
    editor = next(
        (e for e in fake_data.EDITORS.values() if e["name"] == editor_name),
        {"name": editor_name, "expertise": [], "current_load": 0, "max_load": 5},
    )
    ms = fake_data.MANUSCRIPTS.get("MS-999", {})
    ms_topics = set(ms.get("topics", []))
    expertise_set = set(editor.get("expertise", []))
    matched = ms_topics & expertise_set

    flagged_names = {
        (f["editor"] if isinstance(f, dict) else f)
        for f in coi_result.get("flagged", [])
    }
    flag_entry = next(
        (f for f in coi_result.get("flagged", [])
         if (f if isinstance(f, str) else f.get("editor")) == editor_name),
        None,
    )

    return {
        "name": editor_name,
        "orcid": editor.get("id", "N/A"),
        "person_id": editor.get("person_id", "N/A"),
        "expertise": editor.get("expertise", []),
        "current_load": editor.get("current_load", 0),
        "max_load": editor.get("max_load", 5),
        "topic_match": sorted(matched),
        "topic_match_score": len(matched),
        "coi_status": "flagged" if editor_name in flagged_names else "approved",
        "coi_reason": (
            flag_entry.get("reason", "Conflict detected")
            if isinstance(flag_entry, dict)
            else str(flag_entry) if flag_entry else None
        ),
        "reasoning": (
            f"Expertise overlap with manuscript: {', '.join(sorted(matched)) or 'general match'}. "
            f"Current workload: {editor.get('current_load', 0)}/{editor.get('max_load', 5)} manuscripts."
        ),
    }


@app.post(
    "/check-coi",
    summary="Phase 1 — Load manuscript and run COI check",
    description=(
        "Runs Phase 1 of the Streamlit workflow:\n\n"
        "1. Load manuscript from fake data\n"
        "2. Call Strands COI service via A2A (`POST /tasks/send`)\n"
        "3. Strands callbacks to LangGraph for each editor's history\n"
        "4. Return manuscript info + full editor profiles + COI result\n\n"
        "Use the returned `coi_result` in the `/finalize` call."
    ),
    tags=["Streamlit UI"],
)
async def check_coi_only(request: COICheckOnlyRequest):
    ms_number = request.manuscript_number
    try:
        ms = fake_data.get_manuscript(ms_number)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))

    authors = ms["authors"]
    editors = [e["name"] for e in fake_data.EDITORS.values()]

    # A2A call to Strands COI
    coi_message = (
        f"Check conflicts of interest.\n"
        f"Manuscript authors: {json.dumps(authors)}\n"
        f"Candidate editors: {json.dumps(editors)}\n"
        f"For each editor, fetch their publication history and identify any co-authorship "
        f"or recent collaboration with the manuscript authors."
    )
    coi_payload = {
        "id": f"coi-{ms_number}",
        "message": {"role": "user", "parts": [{"text": coi_message}]},
    }

    logger.info("[check-coi] → A2A POST to Strands COI")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            coi_resp = await client.post(f"{STRANDS_URL}/tasks/send", json=coi_payload)
            coi_resp.raise_for_status()
    except httpx.ConnectError:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail=f"Strands COI service not reachable at {STRANDS_URL}",
        )

    coi_text = coi_resp.json()["artifacts"][0]["parts"][0]["text"]
    try:
        import re
        clean = re.sub(r"<thinking>.*?</thinking>", "", coi_text, flags=re.DOTALL)
        match = re.search(r"(\{.*\})", clean, re.DOTALL)
        coi_result = json.loads(match.group(1)) if match else json.loads(coi_text)
    except (json.JSONDecodeError, AttributeError):
        coi_result = {"approved": [], "flagged": []}

    logger.info("[check-coi] ← COI result: %s", coi_result)

    # Build rich editor profiles
    all_editor_names = (
        [a if isinstance(a, str) else a.get("editor") for a in coi_result.get("approved", [])]
        + [f if isinstance(f, str) else f.get("editor") for f in coi_result.get("flagged", [])]
    )
    editor_profiles = {name: _editor_details(name, coi_result) for name in all_editor_names}

    return {
        "manuscript": {
            "number": ms_number,
            "title": ms["title"],
            "authors": authors,
            "abstract": ms.get("abstract", ""),
            "topics": ms.get("topics", []),
            "journal": ms.get("journal", ""),
        },
        "coi_result": coi_result,
        "editor_profiles": editor_profiles,
        "a2a_trace": [
            f"LangGraph → Strands COI:  POST {STRANDS_URL}/tasks/send",
            *[
                f"  Strands → LangGraph:  POST :8000/tasks/send  [history for {name}]"
                for name in all_editor_names
            ],
            "  Strands → LangGraph:  COI result returned",
        ],
    }


@app.post(
    "/finalize",
    summary="Phase 2 — Apply human decision and return final assignment",
    description=(
        "Runs Phase 2 of the Streamlit workflow:\n\n"
        "Takes the COI result from `/check-coi` and the human's HITL decision, "
        "then returns the final editor assignment with full reasoning.\n\n"
        "**human_decision values:**\n"
        "- `'1'` — assign first approved editor\n"
        "- `'2'` — assign second approved editor\n"
        "- `'3'` — override (assign flagged editor anyway)\n"
        "- `'4'` — escalate to editor-in-chief"
    ),
    tags=["Streamlit UI"],
)
async def finalize_assignment(request: FinalizeRequest):
    coi_result = request.coi_result
    approved = [a if isinstance(a, str) else a.get("editor") for a in coi_result.get("approved", [])]
    flagged_raw = coi_result.get("flagged", [])
    flagged = [f if isinstance(f, str) else f.get("editor") for f in flagged_raw]
    decision = request.human_decision

    if decision == "1":
        selected_name = approved[0] if approved else "N/A"
        decision_label = "Approved — AI recommendation accepted"
    elif decision == "2":
        selected_name = approved[1] if len(approved) > 1 else (approved[0] if approved else "N/A")
        decision_label = "Approved — runner-up selected"
    elif decision == "3":
        selected_name = flagged[0] if flagged else "N/A"
        decision_label = "Override — flagged editor assigned by human"
    else:
        selected_name = "ESCALATED"
        decision_label = "Escalated — referred to editor-in-chief"

    selected = _editor_details(selected_name, coi_result) if selected_name != "ESCALATED" else {
        "name": "ESCALATED", "orcid": "N/A", "person_id": "N/A",
        "expertise": [], "reasoning": "Referred to editor-in-chief for manual assignment.",
    }
    runner_up_name = next((a for a in approved if a != selected_name), None)
    runner_up = _editor_details(runner_up_name, coi_result) if runner_up_name else None

    return {
        "selected_editor": selected,
        "runner_up": runner_up,
        "decision_label": decision_label,
        "human_decision": decision,
        "coi_summary": {
            "approved_count": len(approved),
            "flagged_count": len(flagged),
            "flagged_editors": flagged_raw,
        },
    }


# ─── Health check ────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting LangGraph A2A callback server on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
