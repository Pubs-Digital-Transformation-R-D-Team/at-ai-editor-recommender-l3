"""
REST Route Handlers
───────────────────
Plain Starlette async handlers for every non-A2A endpoint:

Browse data:
  GET  /health                    → K8s liveness probe
  GET  /editors                   → List all candidate editors
  GET  /manuscript/{number}       → Fetch a single manuscript
  GET  /editor-history/{name}     → Fetch publication history for one editor

Workflow:
  POST /run-workflow              → Full end-to-end editor assignment (A2A + COI)

Streamlit UI (two-phase HITL):
  POST /check-coi                 → Phase 1: load manuscript, run COI via A2A
  POST /finalize                  → Phase 2: apply human decision, return assignment
"""

import json
import logging
import os
import re
import sys

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

# Allow importing fake_data from parent poc/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import fake_data  # noqa: E402

from langgraph_service.editor_utils import editor_details
from langgraph_service.scoring import (
    decide_hitl_mode,
    ScoreBreakdown,
)

logger = logging.getLogger(__name__)

STRANDS_URL = os.getenv("STRANDS_COI_URL", "http://localhost:8001")


# ─── Browse data endpoints ───────────────────────────────────────────────────

async def health(request: Request):
    """K8s liveness / readiness probe."""
    return JSONResponse({"status": "ok"})


async def list_editors(request: Request):
    """Return all candidate editors from fake_data."""
    return JSONResponse({"editors": list(fake_data.EDITORS.values())})


async def get_manuscript(request: Request):
    """Return a single manuscript by number (e.g. ``MS-999``)."""
    ms_num = request.path_params.get("manuscript_number", "MS-999")
    try:
        return JSONResponse(fake_data.get_manuscript(ms_num))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


async def get_editor_history(request: Request):
    """Return the publication history for a single editor."""
    name = request.path_params.get("editor_name", "Dr. Emily Jones")
    return JSONResponse(fake_data.get_editor_history(name))


# ─── Helper: parse COI response ──────────────────────────────────────────────

def _parse_coi_response(coi_text: str) -> dict:
    """Extract a JSON ``{"approved": [...], "flagged": [...]}`` from the
    potentially messy text returned by the Strands COI agent.

    Strips ``<thinking>`` blocks and markdown fences before attempting
    JSON parse.  Falls back to an empty result on failure.
    """
    try:
        clean = re.sub(r"<thinking>.*?</thinking>", "", coi_text, flags=re.DOTALL)
        match = re.search(r"(\{.*\})", clean, re.DOTALL)
        return json.loads(match.group(1)) if match else json.loads(coi_text)
    except (json.JSONDecodeError, AttributeError):
        return {"approved": [], "flagged": []}


# ─── Full workflow endpoint ───────────────────────────────────────────────────

async def run_workflow(request: Request):
    """End-to-end editor assignment: load manuscript → A2A COI check → assign.

    This is the "one-click" endpoint used for demos and automated tests.
    For the Streamlit UI the two-phase ``/check-coi`` + ``/finalize`` flow
    is used instead.
    """
    body = await request.json()
    ms_number = body.get("manuscript_number", "MS-999")
    auto_approve = body.get("auto_approve", True)

    try:
        ms = fake_data.get_manuscript(ms_number)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    authors = ms["authors"]
    editors = [e["name"] for e in fake_data.EDITORS.values()]
    logger.info("[Workflow] Loaded manuscript %s — authors: %s", ms_number, authors)

    # ── A2A call to Strands COI service ──────────────────────────────────────
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
            coi_resp = await client.post(
                f"{STRANDS_URL}/tasks/send", json=coi_payload
            )
            coi_resp.raise_for_status()
    except httpx.ConnectError:
        return JSONResponse(
            {"error": f"Strands COI service not running at {STRANDS_URL}"},
            status_code=503,
        )

    coi_text = coi_resp.json()["artifacts"][0]["parts"][0]["text"]
    coi_result = _parse_coi_response(coi_text)
    if "raw" not in coi_result and not coi_result.get("approved") and not coi_result.get("flagged"):
        coi_result.setdefault("raw", coi_text)

    logger.info("[Workflow] ← COI result: %s", coi_result)

    # ── Assignment decision ──────────────────────────────────────────────────
    approved = coi_result.get("approved", [])
    flagged = coi_result.get("flagged", [])
    hitl_triggered = len(flagged) > 0

    if hitl_triggered and auto_approve and approved:
        selected_editor_name = approved[0]
        hitl_decision = "option_1_auto_approved"
    elif hitl_triggered and not auto_approve:
        fe = flagged[0]
        selected_editor_name = fe if isinstance(fe, str) else fe.get("editor")
        hitl_decision = "option_2_override"
    elif approved:
        selected_editor_name = approved[0]
        hitl_decision = "no_conflict_auto"
    else:
        selected_editor_name = "ESCALATED"
        hitl_decision = "option_3_escalate"

    selected_editor = next(
        (e for e in fake_data.EDITORS.values() if e["name"] == selected_editor_name),
        {"name": selected_editor_name, "id": "N/A", "person_id": "N/A"},
    )
    runner_up = (
        approved[1]
        if len(approved) > 1
        else (
            approved[0]
            if approved and approved[0] != selected_editor_name
            else "N/A"
        )
    )

    return JSONResponse(
        {
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
            "hitl": {"triggered": hitl_triggered, "decision": hitl_decision},
            "final_assignment": {
                "editor_name": selected_editor["name"],
                "orcid": selected_editor.get("id", "N/A"),
                "person_id": selected_editor.get("person_id", "N/A"),
                "runner_up": runner_up,
            },
        }
    )


# ─── Streamlit UI endpoints (two-phase HITL) ─────────────────────────────────

async def check_coi_only(request: Request):
    """Phase 1 — Load manuscript, run COI check via A2A, compute scores.

    Returns all editor profiles with composite scores and the HITL mode
    decision.  The Streamlit UI uses this to render the review dashboard.
    """
    body = await request.json()
    ms_number = body.get("manuscript_number", "MS-999")

    try:
        ms = fake_data.get_manuscript(ms_number)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    authors = ms["authors"]
    editors = [e["name"] for e in fake_data.EDITORS.values()]

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
            coi_resp = await client.post(
                f"{STRANDS_URL}/tasks/send", json=coi_payload
            )
            coi_resp.raise_for_status()
    except httpx.ConnectError:
        return JSONResponse(
            {"error": f"Strands COI service not reachable at {STRANDS_URL}"},
            status_code=503,
        )

    coi_text = coi_resp.json()["artifacts"][0]["parts"][0]["text"]
    coi_result = _parse_coi_response(coi_text)

    logger.info("[check-coi] ← COI result: %s", coi_result)

    # ── Build enriched profiles for every editor ─────────────────────────────
    all_editor_names = (
        [
            a if isinstance(a, str) else a.get("editor")
            for a in coi_result.get("approved", [])
        ]
        + [
            f if isinstance(f, str) else f.get("editor")
            for f in coi_result.get("flagged", [])
        ]
    )
    editor_profiles = {
        name: editor_details(name, coi_result) for name in all_editor_names
    }

    # ── Score-based HITL decision ─────────────────────────────────────────
    any_flagged = len(coi_result.get("flagged", [])) > 0
    ranked = sorted(
        [
            (name, ScoreBreakdown(**profile["score"]))
            for name, profile in editor_profiles.items()
            if profile["coi_status"] != "flagged"
        ],
        key=lambda x: x[1].composite,
        reverse=True,
    )
    hitl_decision = decide_hitl_mode(ranked, any_coi_flagged=any_flagged)

    logger.info(
        "[check-coi] Complete — approved: %s | flagged: %s | HITL mode: %s (gap: %.0f)",
        [
            a if isinstance(a, str) else a.get("editor")
            for a in coi_result.get("approved", [])
        ],
        [
            f if isinstance(f, str) else f.get("editor")
            for f in coi_result.get("flagged", [])
        ],
        hitl_decision.mode,
        hitl_decision.gap,
    )

    return JSONResponse(
        {
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
            "hitl_decision": hitl_decision.to_dict(),
            "a2a_trace": [
                f"LangGraph → Strands COI:  POST {STRANDS_URL}/tasks/send",
                *[
                    f"  Strands → LangGraph:  POST :8000/tasks/send  [history for {name}]"
                    for name in all_editor_names
                ],
                "  Strands → LangGraph:  COI result returned",
                f"Score-based HITL: mode={hitl_decision.mode}, gap={hitl_decision.gap:.0f}pts",
            ],
        }
    )


async def finalize_assignment(request: Request):
    """Phase 2 — Apply human HITL decision and return the final assignment.

    The Streamlit UI sends the ``coi_result`` (from phase 1) along with
    the human's choice (``"1"``–``"4"``).  We look up the selected editor,
    enrich the profile, and return the assignment.
    """
    body = await request.json()
    coi_result = body.get("coi_result", {})
    decision = body.get("human_decision", "1")

    logger.info("[finalize] Human decision received: option %s", decision)

    approved = [
        a if isinstance(a, str) else a.get("editor")
        for a in coi_result.get("approved", [])
    ]
    flagged_raw = coi_result.get("flagged", [])
    flagged = [
        f if isinstance(f, str) else f.get("editor") for f in flagged_raw
    ]

    if decision == "1":
        selected_name = approved[0] if approved else "N/A"
        decision_label = "Approved — AI recommendation accepted"
    elif decision == "2":
        selected_name = (
            approved[1]
            if len(approved) > 1
            else (approved[0] if approved else "N/A")
        )
        decision_label = "Approved — runner-up selected"
    elif decision == "3":
        selected_name = flagged[0] if flagged else "N/A"
        decision_label = "Override — flagged editor assigned by human"
    else:
        selected_name = "ESCALATED"
        decision_label = "Escalated — referred to editor-in-chief"

    logger.info(
        "[finalize] Decision: %s → selected editor: %s",
        decision_label,
        selected_name,
    )

    selected = (
        editor_details(selected_name, coi_result)
        if selected_name != "ESCALATED"
        else {
            "name": "ESCALATED",
            "orcid": "N/A",
            "person_id": "N/A",
            "expertise": [],
            "reasoning": "Referred to editor-in-chief for manual assignment.",
        }
    )
    runner_up_name = next(
        (a for a in approved if a != selected_name), None
    )
    runner_up = (
        editor_details(runner_up_name, coi_result) if runner_up_name else None
    )

    logger.info(
        "[finalize] Final assignment: %s (runner-up: %s) | approved: %d, flagged: %d",
        selected_name,
        runner_up_name or "none",
        len(approved),
        len(flagged),
    )

    return JSONResponse(
        {
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
    )
