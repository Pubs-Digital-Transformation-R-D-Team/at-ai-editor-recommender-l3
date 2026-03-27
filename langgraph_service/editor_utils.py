"""
Editor Utility Functions
────────────────────────
Pure helper functions for:

* Parsing editor names from A2A messages
* Building human-readable reasoning (bullet points + one-liner)
* Enriching an editor record with COI status, topic overlap, and composite score

These are used by the REST route handlers (``routes.py``) and are
independently testable — they have no HTTP / framework dependencies.
"""

import os
import sys

# Allow importing fake_data from parent poc/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import fake_data  # noqa: E402

from langgraph_service.scoring import compute_editor_score


# ─── Name extraction ─────────────────────────────────────────────────────────

def extract_editor_name(text: str) -> str:
    """Parse 'Get editor history for: Dr. Emily Jones' → 'Dr. Emily Jones'.

    Handles both ``for:`` (with colon) and ``for `` (space) separators,
    strips surrounding quotes, and falls back to the raw text.
    """
    for separator in ["for:", "for "]:
        if separator in text.lower():
            idx = text.lower().index(separator) + len(separator)
            return text[idx:].strip().strip('"').strip("'")
    return text.strip()


# ─── Reasoning helpers ───────────────────────────────────────────────────────

def build_reasoning_points(
    editor_name: str,
    editor: dict,
    matched: set,
    flagged_names: set,
) -> list[str]:
    """Return a list of concise bullet-point reasons for/against this editor.

    Each point starts with a ✅ / ⚠️ / ❌ emoji for quick scanning in the
    Streamlit dashboard.
    """
    points = []
    load = editor.get("current_load", 0)
    max_load = editor.get("max_load", 5)
    capacity = max_load - load
    expertise = editor.get("expertise", [])

    # Topic match
    if matched:
        points.append(
            f"✅ Expertise directly matches manuscript topics: {', '.join(sorted(matched))}"
        )
    else:
        other = [e for e in expertise if e not in matched]
        points.append(
            f"⚠️ No direct topic overlap (expertise: {', '.join(other[:3]) or 'general'})"
        )

    # Workload / capacity
    if capacity >= 3:
        points.append(
            f"✅ Good capacity — {load}/{max_load} manuscripts assigned, {capacity} slots free"
        )
    elif capacity == 2:
        points.append(
            f"✅ Available — {load}/{max_load} manuscripts assigned, {capacity} slots free"
        )
    elif capacity == 1:
        points.append(
            f"⚠️ Nearly full — only 1 slot remaining ({load}/{max_load} manuscripts)"
        )
    else:
        points.append(
            f"❌ At capacity — {load}/{max_load} manuscripts (no slots free)"
        )

    # COI status
    if editor_name not in flagged_names:
        points.append("✅ No conflict of interest detected with manuscript authors")
    else:
        points.append(
            "❌ Conflict of interest — co-authorship or relationship with an author detected"
        )

    return points


def build_reasoning(
    editor_name: str,
    editor: dict,
    matched: set,
    flagged_names: set,
) -> str:
    """Return a single-sentence summary suitable for the editor card."""
    load = editor.get("current_load", 0)
    max_load = editor.get("max_load", 5)
    capacity = max_load - load
    topic_str = ", ".join(sorted(matched)) if matched else "general relevance"
    coi_str = "No COI detected" if editor_name not in flagged_names else "COI flagged"
    cap_str = f"{capacity} slot{'s' if capacity != 1 else ''} free"
    return f"Topic match: {topic_str}. Capacity: {load}/{max_load} ({cap_str}). {coi_str}."


# ─── Editor profile enrichment ───────────────────────────────────────────────

def editor_details(editor_name: str, coi_result: dict) -> dict:
    """Enrich an editor record with COI status, topic match, and composite score.

    Looks up the editor in ``fake_data.EDITORS``, cross-references the
    manuscript topics from ``MS-999``, computes the five-dimension composite
    score, and returns a dict ready to be serialised as JSON for the
    Streamlit frontend.
    """
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
        (
            f
            for f in coi_result.get("flagged", [])
            if (f if isinstance(f, str) else f.get("editor")) == editor_name
        ),
        None,
    )

    # ── Compute composite score ─────────────────────────────────────────────
    is_flagged = editor_name in flagged_names
    score = compute_editor_score(
        editor_expertise=editor.get("expertise", []),
        manuscript_topics=list(ms_topics),
        current_load=editor.get("current_load", 0),
        max_load=editor.get("max_load", 5),
        is_coi_flagged=is_flagged,
        acceptance_rate=editor.get("acceptance_rate", 0.75),
        avg_revision_rounds=editor.get("avg_revision_rounds", 2.0),
        avg_turnaround_days=editor.get("avg_turnaround_days", 18.0),
    )

    return {
        "name": editor_name,
        "orcid": editor.get("id", "N/A"),
        "person_id": editor.get("person_id", "N/A"),
        "expertise": editor.get("expertise", []),
        "current_load": editor.get("current_load", 0),
        "max_load": editor.get("max_load", 5),
        "acceptance_rate": editor.get("acceptance_rate", 0.75),
        "avg_revision_rounds": editor.get("avg_revision_rounds", 2.0),
        "avg_turnaround_days": editor.get("avg_turnaround_days", 18.0),
        "topic_match": sorted(matched),
        "topic_match_score": len(matched),
        "coi_status": "flagged" if is_flagged else "approved",
        "coi_reason": (
            flag_entry.get("reason", "Conflict detected")
            if isinstance(flag_entry, dict)
            else str(flag_entry) if flag_entry else None
        ),
        "score": score.to_dict(),
        "composite_score": round(score.composite, 1),
        "reasoning": build_reasoning(editor_name, editor, matched, flagged_names),
        "reasoning_points": build_reasoning_points(
            editor_name, editor, matched, flagged_names
        ),
    }
