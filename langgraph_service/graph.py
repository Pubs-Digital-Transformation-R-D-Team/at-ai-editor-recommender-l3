"""
LangGraph StateGraph — Editor Assignment Orchestrator
──────────────────────────────────────────────────────
Nodes:
  1. get_manuscript       — loads fake manuscript + editor data
  2. editor_assignment    — ReAct loop (LLM + check_conflicts tool → Strands A2A)
  3. coi_review           — HITL checkpoint: interrupt() if conflicts found
  4. assign_editor        — parse final recommendation, output result

The graph is the macro-level orchestrator.
The LLM inside editor_assignment is the micro-level reasoner.
"""

import json
import logging
import os
import sys
from typing import TypedDict, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

# Allow importing from parent poc/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import fake_data  # noqa: E402
from langgraph_service.react_agent import run_react_editor_assignment  # noqa: E402

logger = logging.getLogger(__name__)

# ─── State ──────────────────────────────────────────────────────────────────

class State(TypedDict):
    manuscript_number: str
    manuscript_info: Optional[str]
    available_editors: Optional[str]
    authors: Optional[list[str]]
    editor_names: Optional[list[str]]
    llm_recommendation: Optional[str]
    coi_result: Optional[dict]
    human_decision: Optional[str]
    final_assignment: Optional[dict]


# ─── Node 1: get_manuscript ──────────────────────────────────────────────────

async def get_manuscript(state: State) -> dict:
    ms_number = state["manuscript_number"]
    logger.info("[LangGraph Graph] Node: get_manuscript — %s", ms_number)

    ms = fake_data.get_manuscript(ms_number)

    manuscript_info = (
        f"Title: {ms['title']}\n"
        f"Authors: {', '.join(ms['authors'])}\n"
        f"Abstract: {ms['abstract']}\n"
        f"Topics: {', '.join(ms['topics'])}\n"
        f"Journal: {ms['journal']}"
    )

    available_editors = fake_data.get_editors_summary()

    logger.info("[LangGraph Graph] Manuscript loaded. %d candidate editors.", len(fake_data.EDITORS))

    return {
        "manuscript_info": manuscript_info,
        "available_editors": available_editors,
        "authors": ms["authors"],
        "editor_names": [e["name"] for e in fake_data.EDITORS.values()],
    }


# ─── Node 2: editor_assignment (ReAct loop) ──────────────────────────────────

async def editor_assignment(state: State) -> dict:
    logger.info("[LangGraph Graph] Node: editor_assignment — starting ReAct loop")

    llm_text, coi_result = await run_react_editor_assignment(
        manuscript_info=state["manuscript_info"],
        available_editors=state["available_editors"],
    )

    logger.info("[LangGraph Graph] ReAct loop complete")
    return {
        "llm_recommendation": llm_text,
        "coi_result": coi_result,
    }


# ─── Node 3: coi_review (HITL checkpoint) ────────────────────────────────────

async def coi_review(state: State) -> dict:
    coi = state.get("coi_result") or {}
    flagged = coi.get("flagged", [])

    if not flagged:
        logger.info("[LangGraph Graph] Node: coi_review — no conflicts, passing through")
        return {"human_decision": "auto-approved"}

    # ── HITL: pause graph and ask human ──────────────────────────────────────
    logger.info("[LangGraph Graph] Node: coi_review — CONFLICT DETECTED, raising interrupt()")

    flagged_summary = []
    for item in flagged:
        if isinstance(item, dict):
            flagged_summary.append(f"  • {item.get('editor', item)} — {item.get('reason', 'conflict detected')}")
        else:
            flagged_summary.append(f"  • {item}")

    approved = coi.get("approved", [])
    approved_names = [a if isinstance(a, str) else a.get("editor", str(a)) for a in approved]

    human_decision = interrupt({
        "message": "⚑ CONFLICT OF INTEREST DETECTED — HUMAN APPROVAL REQUIRED",
        "flagged_editors": "\n".join(flagged_summary),
        "approved_alternatives": approved_names,
        "options": {
            "1": f"Proceed with approved alternative: {approved_names[0] if approved_names else 'none'}",
            "2": "Override — assign flagged editor anyway",
            "3": "Reject — escalate to editor-in-chief",
        },
    })

    logger.info("[LangGraph Graph] coi_review resumed with human decision: %s", human_decision)
    return {"human_decision": human_decision}


# ─── Node 4: assign_editor ───────────────────────────────────────────────────

async def assign_editor(state: State) -> dict:
    logger.info("[LangGraph Graph] Node: assign_editor")

    human_decision = state.get("human_decision", "auto-approved")
    coi = state.get("coi_result") or {}
    flagged = coi.get("flagged", [])
    approved = coi.get("approved", [])

    llm_text = state.get("llm_recommendation", "")

    # Parse LLM JSON output
    try:
        # Strip markdown fences if present
        clean = llm_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        recommendation = json.loads(clean.strip())
    except (json.JSONDecodeError, IndexError):
        recommendation = {"raw_output": llm_text}

    # Apply human decision override if needed
    if human_decision == "2" and flagged:
        flagged_editor = flagged[0] if isinstance(flagged[0], str) else flagged[0].get("editor")
        recommendation["override_note"] = f"Human overrode COI flag — assigned: {flagged_editor}"
        logger.info("[LangGraph Graph] Human chose to override COI flag")
    elif human_decision == "3":
        recommendation = {
            "selectedEditorName": "ESCALATED",
            "reasoning": "Human chose to escalate to editor-in-chief",
        }
        logger.info("[LangGraph Graph] Human chose to escalate")
    else:
        logger.info("[LangGraph Graph] Proceeding with LLM recommendation (approved alternative)")

    final = {
        "manuscript_number": state["manuscript_number"],
        "recommendation": recommendation,
        "coi_result": coi,
        "human_decision": human_decision,
    }

    logger.info("[LangGraph Graph] Assignment complete: %s", recommendation.get("selectedEditorName", "unknown"))
    return {"final_assignment": final}


# ─── Build graph ─────────────────────────────────────────────────────────────

def build_graph() -> tuple:
    """Build and compile the LangGraph StateGraph. Returns (graph, config)."""
    memory = MemorySaver()

    builder = StateGraph(State)
    builder.add_node("get_manuscript", get_manuscript)
    builder.add_node("editor_assignment", editor_assignment)
    builder.add_node("coi_review", coi_review)
    builder.add_node("assign_editor", assign_editor)

    builder.add_edge(START, "get_manuscript")
    builder.add_edge("get_manuscript", "editor_assignment")
    builder.add_edge("editor_assignment", "coi_review")
    builder.add_edge("coi_review", "assign_editor")
    builder.add_edge("assign_editor", END)

    graph = builder.compile(checkpointer=memory)

    config = {"configurable": {"thread_id": "poc-thread-001"}}
    logger.info("[LangGraph Graph] Graph compiled with MemorySaver checkpointer")
    return graph, config
