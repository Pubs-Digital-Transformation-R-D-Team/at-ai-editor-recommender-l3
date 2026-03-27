"""
Tests for langgraph_service/scoring.py
───────────────────────────────────────
Covers:
  - Individual dimension scorers
  - Composite score computation
  - HITL decision logic (auto_assign / soft_review / full_hitl)
  - Edge cases and boundary conditions
"""

import pytest
from langgraph_service.scoring import (
    _score_topic_match,
    _score_capacity,
    _score_coi,
    _score_track_record,
    _score_turnaround,
    compute_editor_score,
    decide_hitl_mode,
    ScoreBreakdown,
    HITLDecision,
    THRESHOLD_AUTO_ASSIGN,
    THRESHOLD_SOFT_REVIEW,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  _score_topic_match
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreTopicMatch:
    """Tests for Jaccard-like topic match scoring."""

    def test_perfect_overlap(self):
        score = _score_topic_match(["oncology", "cancer"], ["oncology", "cancer"])
        assert score == 100.0

    def test_no_overlap(self):
        score = _score_topic_match(["physics", "math"], ["oncology", "cancer"])
        assert score == 0.0

    def test_partial_overlap(self):
        score = _score_topic_match(
            ["oncology", "immunotherapy", "clinical trials"],
            ["immunotherapy", "deep learning", "oncology", "cancer"],
        )
        assert 30.0 < score < 80.0  # partial match should be moderate

    def test_empty_manuscript_topics_returns_neutral(self):
        score = _score_topic_match(["oncology"], [])
        assert score == 50.0

    def test_empty_editor_expertise(self):
        score = _score_topic_match([], ["oncology", "cancer"])
        assert score == 0.0

    def test_both_empty(self):
        score = _score_topic_match([], [])
        assert score == 50.0  # no topics → neutral

    def test_case_insensitive(self):
        score = _score_topic_match(["Oncology", "CANCER"], ["oncology", "cancer"])
        assert score == 100.0

    def test_score_never_exceeds_100(self):
        score = _score_topic_match(
            ["a", "b", "c", "d"],
            ["a", "b", "c", "d"],
        )
        assert score <= 100.0

    def test_single_topic_match(self):
        score = _score_topic_match(["oncology"], ["oncology"])
        assert score == 100.0


# ═══════════════════════════════════════════════════════════════════════════════
#  _score_capacity
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreCapacity:
    """Tests for workload capacity scoring."""

    def test_fully_free(self):
        assert _score_capacity(0, 5) == 100.0

    def test_fully_loaded(self):
        assert _score_capacity(5, 5) == 0.0

    def test_half_loaded(self):
        score = _score_capacity(2, 4)
        assert score == 50.0

    def test_one_slot_free(self):
        score = _score_capacity(4, 5)
        assert score == 20.0

    def test_zero_max_load(self):
        assert _score_capacity(0, 0) == 0.0

    def test_over_capacity(self):
        score = _score_capacity(6, 5)
        assert score == 0.0  # clamped to 0


# ═══════════════════════════════════════════════════════════════════════════════
#  _score_coi
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreCOI:
    """Tests for binary COI scoring."""

    def test_no_conflict(self):
        assert _score_coi(False) == 100.0

    def test_conflict_flagged(self):
        assert _score_coi(True) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
#  _score_track_record
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreTrackRecord:
    """Tests for track record scoring (acceptance rate + revision rounds)."""

    def test_perfect_record(self):
        score = _score_track_record(1.0, 1.0)
        assert score == 100.0  # 100% acceptance + 1 revision round

    def test_poor_record(self):
        score = _score_track_record(0.0, 4.0)
        assert score == 0.0  # 0% acceptance + 4 revision rounds

    def test_average_record(self):
        score = _score_track_record(0.75, 2.0)
        assert 40.0 < score < 80.0

    def test_high_acceptance_many_revisions(self):
        score = _score_track_record(0.9, 3.5)
        assert 40.0 < score < 80.0

    def test_low_acceptance_few_revisions(self):
        score = _score_track_record(0.3, 1.0)
        assert 30.0 < score < 70.0


# ═══════════════════════════════════════════════════════════════════════════════
#  _score_turnaround
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreTurnaround:
    """Tests for turnaround time scoring."""

    def test_very_fast(self):
        score = _score_turnaround(5.0, 21.0)
        assert score == 100.0

    def test_at_benchmark(self):
        score = _score_turnaround(21.0, 21.0)
        assert 60.0 < score < 70.0  # slightly above midpoint

    def test_very_slow(self):
        score = _score_turnaround(42.0, 21.0)
        assert score == 0.0

    def test_extremely_slow(self):
        score = _score_turnaround(100.0, 21.0)
        assert score == 0.0

    def test_zero_days(self):
        assert _score_turnaround(0.0, 21.0) == 100.0

    def test_half_benchmark(self):
        score = _score_turnaround(10.5, 21.0)
        assert score == 100.0


# ═══════════════════════════════════════════════════════════════════════════════
#  compute_editor_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeEditorScore:
    """Tests for the composite score computation."""

    def test_returns_score_breakdown(self):
        result = compute_editor_score(
            editor_expertise=["oncology"],
            manuscript_topics=["oncology"],
            current_load=2,
            max_load=5,
            is_coi_flagged=False,
        )
        assert isinstance(result, ScoreBreakdown)

    def test_composite_range(self):
        result = compute_editor_score(
            editor_expertise=["oncology", "cancer"],
            manuscript_topics=["oncology", "cancer"],
            current_load=0,
            max_load=5,
            is_coi_flagged=False,
        )
        assert 0.0 <= result.composite <= 100.0

    def test_flagged_coi_reduces_score(self):
        clean = compute_editor_score(
            editor_expertise=["oncology"],
            manuscript_topics=["oncology"],
            current_load=2,
            max_load=5,
            is_coi_flagged=False,
        )
        flagged = compute_editor_score(
            editor_expertise=["oncology"],
            manuscript_topics=["oncology"],
            current_load=2,
            max_load=5,
            is_coi_flagged=True,
        )
        assert flagged.composite < clean.composite
        assert flagged.coi_clear == 0.0
        assert clean.coi_clear == 100.0

    def test_high_load_reduces_score(self):
        low_load = compute_editor_score(
            editor_expertise=["oncology"],
            manuscript_topics=["oncology"],
            current_load=1,
            max_load=5,
            is_coi_flagged=False,
        )
        high_load = compute_editor_score(
            editor_expertise=["oncology"],
            manuscript_topics=["oncology"],
            current_load=5,
            max_load=5,
            is_coi_flagged=False,
        )
        assert high_load.composite < low_load.composite

    def test_to_dict(self):
        result = compute_editor_score(
            editor_expertise=["oncology"],
            manuscript_topics=["oncology"],
            current_load=2,
            max_load=5,
            is_coi_flagged=False,
        )
        d = result.to_dict()
        assert "composite" in d
        assert "topic_match" in d
        assert "capacity" in d
        assert "coi_clear" in d
        assert "track_record" in d
        assert "turnaround" in d
        # All values should be rounded
        for v in d.values():
            assert isinstance(v, float)

    def test_default_parameters(self):
        """Test that default acceptance_rate, avg_revision_rounds etc. work."""
        result = compute_editor_score(
            editor_expertise=["ai"],
            manuscript_topics=["ai"],
            current_load=0,
            max_load=5,
            is_coi_flagged=False,
        )
        assert result.composite > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  decide_hitl_mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecideHITLMode:
    """Tests for HITL routing decisions."""

    def _make_breakdown(self, composite: float) -> ScoreBreakdown:
        return ScoreBreakdown(composite=composite)

    def test_no_editors_returns_full_hitl(self):
        decision = decide_hitl_mode([])
        assert decision.mode == "full_hitl"
        assert decision.top_editor == "NONE"

    def test_coi_flagged_forces_full_hitl(self):
        editors = [
            ("Dr. A", self._make_breakdown(90)),
            ("Dr. B", self._make_breakdown(30)),
        ]
        decision = decide_hitl_mode(editors, any_coi_flagged=True)
        assert decision.mode == "full_hitl"
        assert decision.has_coi is True

    def test_large_gap_auto_assign(self):
        editors = [
            ("Dr. A", self._make_breakdown(85)),
            ("Dr. B", self._make_breakdown(60)),
        ]
        decision = decide_hitl_mode(editors)
        assert decision.mode == "auto_assign"
        assert decision.gap == 25.0
        assert decision.top_editor == "Dr. A"

    def test_moderate_gap_soft_review(self):
        editors = [
            ("Dr. A", self._make_breakdown(75)),
            ("Dr. B", self._make_breakdown(60)),
        ]
        decision = decide_hitl_mode(editors)
        assert decision.mode == "soft_review"
        assert decision.gap == 15.0

    def test_narrow_gap_full_hitl(self):
        editors = [
            ("Dr. A", self._make_breakdown(72)),
            ("Dr. B", self._make_breakdown(68)),
        ]
        decision = decide_hitl_mode(editors)
        assert decision.mode == "full_hitl"
        assert decision.gap == 4.0

    def test_exact_threshold_auto_assign(self):
        editors = [
            ("Dr. A", self._make_breakdown(80)),
            ("Dr. B", self._make_breakdown(80 - THRESHOLD_AUTO_ASSIGN)),
        ]
        decision = decide_hitl_mode(editors)
        assert decision.mode == "auto_assign"

    def test_exact_threshold_soft_review(self):
        editors = [
            ("Dr. A", self._make_breakdown(70)),
            ("Dr. B", self._make_breakdown(70 - THRESHOLD_SOFT_REVIEW)),
        ]
        decision = decide_hitl_mode(editors)
        assert decision.mode == "soft_review"

    def test_single_editor_auto_assign(self):
        """With only one editor, gap to runner-up is the full composite."""
        editors = [("Dr. A", self._make_breakdown(50))]
        decision = decide_hitl_mode(editors)
        assert decision.mode == "auto_assign"  # gap=50, well above threshold
        assert decision.runner_up is None

    def test_coi_overrides_large_gap(self):
        """COI always forces full HITL even with a large gap."""
        editors = [
            ("Dr. A", self._make_breakdown(95)),
            ("Dr. B", self._make_breakdown(20)),
        ]
        decision = decide_hitl_mode(editors, any_coi_flagged=True)
        assert decision.mode == "full_hitl"

    def test_decision_to_dict(self):
        editors = [
            ("Dr. A", self._make_breakdown(80)),
            ("Dr. B", self._make_breakdown(55)),
        ]
        decision = decide_hitl_mode(editors)
        d = decision.to_dict()
        assert "mode" in d
        assert "reason" in d
        assert "top_editor" in d
        assert "gap" in d
        assert isinstance(d["gap"], (int, float))

    def test_reason_text_includes_gap(self):
        editors = [
            ("Dr. A", self._make_breakdown(80)),
            ("Dr. B", self._make_breakdown(60)),
        ]
        decision = decide_hitl_mode(editors)
        assert "20" in decision.reason  # gap of 20 should appear in the reason
