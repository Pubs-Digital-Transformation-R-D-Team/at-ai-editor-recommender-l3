"""
Score-Based HITL — Composite Editor Scoring
─────────────────────────────────────────────
Each candidate editor gets a **composite score (0–100)** made of five
weighted dimensions.  The score drives a graduated HITL policy:

  Score gap > 20   →  auto-assign (AI confident)
  Score gap 10–20  →  soft review (quick confirm)
  Score gap < 10   →  full HITL (editor decides)
  Any flagged COI  →  always HITL

Dimensions & default weights:
  1. Topic Match    (30%)  — keyword overlap between editor expertise & MS topics
  2. Capacity       (20%)  — available manuscript slots
  3. COI Clear      (20%)  — 0 if flagged, 20 if clean
  4. Track Record   (15%)  — past acceptance/revision rates
  5. Turnaround     (15%)  — average review turnaround speed
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Weights (must sum to 1.0) ────────────────────────────────────────────────

WEIGHT_TOPIC = 0.30
WEIGHT_CAPACITY = 0.20
WEIGHT_COI = 0.20
WEIGHT_TRACK_RECORD = 0.15
WEIGHT_TURNAROUND = 0.15

# ── Thresholds ───────────────────────────────────────────────────────────────

THRESHOLD_AUTO_ASSIGN = 20   # gap between #1 and #2 to auto-assign
THRESHOLD_SOFT_REVIEW = 10   # gap for soft review (quick confirm)


@dataclass
class ScoreBreakdown:
    """Individual dimension scores (each 0–100) and the weighted composite."""

    topic_match: float = 0.0
    capacity: float = 0.0
    coi_clear: float = 0.0
    track_record: float = 0.0
    turnaround: float = 0.0
    composite: float = 0.0

    def to_dict(self) -> dict:
        return {
            "topic_match": round(self.topic_match, 1),
            "capacity": round(self.capacity, 1),
            "coi_clear": round(self.coi_clear, 1),
            "track_record": round(self.track_record, 1),
            "turnaround": round(self.turnaround, 1),
            "composite": round(self.composite, 1),
        }


# ── Dimension scorers ────────────────────────────────────────────────────────

def _score_topic_match(editor_expertise: list[str], manuscript_topics: list[str]) -> float:
    """0–100 based on Jaccard-like overlap, with boost for high overlap."""
    if not manuscript_topics:
        return 50.0  # neutral when no topics
    expertise_set = {e.lower() for e in editor_expertise}
    topic_set = {t.lower() for t in manuscript_topics}
    overlap = len(expertise_set & topic_set)
    union = len(expertise_set | topic_set)
    if union == 0:
        return 0.0
    jaccard = overlap / union
    # Also consider coverage: what fraction of manuscript topics are covered
    coverage = overlap / len(topic_set) if topic_set else 0
    # Blend: 60% coverage, 40% Jaccard
    raw = (0.6 * coverage + 0.4 * jaccard) * 100
    return min(raw, 100.0)


def _score_capacity(current_load: int, max_load: int) -> float:
    """0–100 based on available slots.  0 load → 100, at capacity → 0."""
    if max_load <= 0:
        return 0.0
    free_ratio = (max_load - current_load) / max_load
    return max(0.0, min(free_ratio * 100, 100.0))


def _score_coi(is_flagged: bool) -> float:
    """Binary: 0 if flagged, 100 if clean."""
    return 0.0 if is_flagged else 100.0


def _score_track_record(acceptance_rate: float, avg_revision_rounds: float) -> float:
    """0–100.  High acceptance rate + fewer revision rounds → better.
    acceptance_rate: 0.0–1.0 fraction
    avg_revision_rounds: typically 1–4
    """
    # acceptance component (60% of track record)
    acc_score = acceptance_rate * 100
    # revision efficiency (40%) — fewer rounds is better, capped at 4
    rev_score = max(0, (1 - (avg_revision_rounds - 1) / 3)) * 100
    return 0.6 * acc_score + 0.4 * rev_score


def _score_turnaround(avg_days: float, benchmark_days: float = 21.0) -> float:
    """0–100.  Faster than benchmark → higher score.
    avg_days: editor's average turnaround in days
    benchmark_days: journal's target turnaround (default 21 days)
    """
    if avg_days <= 0:
        return 100.0
    ratio = avg_days / benchmark_days
    if ratio <= 0.5:
        return 100.0
    if ratio >= 2.0:
        return 0.0
    # Linear interpolation: 0.5→100, 2.0→0
    return max(0.0, (2.0 - ratio) / 1.5 * 100)


# ── Main scoring function ────────────────────────────────────────────────────

def compute_editor_score(
    editor_expertise: list[str],
    manuscript_topics: list[str],
    current_load: int,
    max_load: int,
    is_coi_flagged: bool,
    acceptance_rate: float = 0.75,
    avg_revision_rounds: float = 2.0,
    avg_turnaround_days: float = 18.0,
    benchmark_days: float = 21.0,
) -> ScoreBreakdown:
    """Compute composite score for a candidate editor."""

    topic = _score_topic_match(editor_expertise, manuscript_topics)
    capacity = _score_capacity(current_load, max_load)
    coi = _score_coi(is_coi_flagged)
    track = _score_track_record(acceptance_rate, avg_revision_rounds)
    turnaround = _score_turnaround(avg_turnaround_days, benchmark_days)

    composite = (
        WEIGHT_TOPIC * topic
        + WEIGHT_CAPACITY * capacity
        + WEIGHT_COI * coi
        + WEIGHT_TRACK_RECORD * track
        + WEIGHT_TURNAROUND * turnaround
    )

    breakdown = ScoreBreakdown(
        topic_match=topic,
        capacity=capacity,
        coi_clear=coi,
        track_record=track,
        turnaround=turnaround,
        composite=composite,
    )

    logger.info(
        "Score for editor: composite=%.1f (topic=%.0f cap=%.0f coi=%.0f track=%.0f turn=%.0f)",
        composite, topic, capacity, coi, track, turnaround,
    )
    return breakdown


# ── HITL decision logic ──────────────────────────────────────────────────────

@dataclass
class HITLDecision:
    """Result of score-based routing: auto-assign, soft review, or full HITL."""

    mode: str          # "auto_assign" | "soft_review" | "full_hitl"
    reason: str        # human-readable explanation
    top_editor: str    # name of the highest-scoring editor
    top_score: float
    runner_up: str | None = None
    runner_up_score: float = 0.0
    gap: float = 0.0
    has_coi: bool = False

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "reason": self.reason,
            "top_editor": self.top_editor,
            "top_score": round(self.top_score, 1),
            "runner_up": self.runner_up,
            "runner_up_score": round(self.runner_up_score, 1),
            "gap": round(self.gap, 1),
            "has_coi": self.has_coi,
        }


def decide_hitl_mode(
    ranked_editors: list[tuple[str, ScoreBreakdown]],
    any_coi_flagged: bool = False,
) -> HITLDecision:
    """Given editors sorted by composite score, decide the HITL mode.

    Args:
        ranked_editors: list of (editor_name, ScoreBreakdown), highest first
        any_coi_flagged: True if any editor was COI-flagged

    Returns:
        HITLDecision with the routing mode and reasoning
    """
    if not ranked_editors:
        return HITLDecision(
            mode="full_hitl",
            reason="No candidate editors available",
            top_editor="NONE",
            top_score=0,
            has_coi=any_coi_flagged,
        )

    top_name, top_score = ranked_editors[0]
    runner_name = ranked_editors[1][0] if len(ranked_editors) > 1 else None
    runner_score_val = ranked_editors[1][1].composite if len(ranked_editors) > 1 else 0.0
    gap = top_score.composite - runner_score_val

    # Rule 1: any COI → always full HITL
    if any_coi_flagged:
        return HITLDecision(
            mode="full_hitl",
            reason=f"COI detected — human review required (gap: {gap:.0f} pts)",
            top_editor=top_name,
            top_score=top_score.composite,
            runner_up=runner_name,
            runner_up_score=runner_score_val,
            gap=gap,
            has_coi=True,
        )

    # Rule 2: large gap → auto-assign
    if gap >= THRESHOLD_AUTO_ASSIGN:
        return HITLDecision(
            mode="auto_assign",
            reason=f"Clear winner — score gap {gap:.0f} pts exceeds auto-assign threshold ({THRESHOLD_AUTO_ASSIGN})",
            top_editor=top_name,
            top_score=top_score.composite,
            runner_up=runner_name,
            runner_up_score=runner_score_val,
            gap=gap,
        )

    # Rule 3: moderate gap → soft review
    if gap >= THRESHOLD_SOFT_REVIEW:
        return HITLDecision(
            mode="soft_review",
            reason=f"Close scores — gap {gap:.0f} pts, quick confirmation recommended",
            top_editor=top_name,
            top_score=top_score.composite,
            runner_up=runner_name,
            runner_up_score=runner_score_val,
            gap=gap,
        )

    # Rule 4: narrow gap → full HITL
    return HITLDecision(
        mode="full_hitl",
        reason=f"Very close scores — gap only {gap:.0f} pts, full human review needed",
        top_editor=top_name,
        top_score=top_score.composite,
        runner_up=runner_name,
        runner_up_score=runner_score_val,
        gap=gap,
    )
