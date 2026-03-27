"""
Tests for fake_data.py
───────────────────────
Covers:
  - Manuscript retrieval
  - Editor data structure integrity
  - Editor history lookup
  - Edge cases (missing data, partial matches)
"""

import pytest
from fake_data import (
    MANUSCRIPTS,
    EDITORS,
    EDITOR_HISTORY,
    get_manuscript,
    get_editors_summary,
    get_editor_history,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  get_manuscript
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetManuscript:

    def test_existing_manuscript(self):
        ms = get_manuscript("MS-999")
        assert ms["manuscript_number"] == "MS-999"
        assert "title" in ms
        assert "authors" in ms
        assert "topics" in ms
        assert "journal" in ms

    def test_missing_manuscript_raises(self):
        with pytest.raises(ValueError, match="not found"):
            get_manuscript("DOES-NOT-EXIST")

    def test_manuscript_has_authors(self):
        ms = get_manuscript("MS-999")
        assert len(ms["authors"]) > 0

    def test_manuscript_has_topics(self):
        ms = get_manuscript("MS-999")
        assert len(ms["topics"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  EDITORS data structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestEditorsData:

    def test_editors_not_empty(self):
        assert len(EDITORS) > 0

    def test_each_editor_has_required_fields(self):
        required = {"id", "name", "person_id", "expertise", "current_load", "max_load"}
        for key, editor in EDITORS.items():
            missing = required - set(editor.keys())
            assert not missing, f"Editor '{key}' missing fields: {missing}"

    def test_editor_load_within_bounds(self):
        for key, editor in EDITORS.items():
            assert editor["current_load"] >= 0
            assert editor["max_load"] > 0
            assert editor["current_load"] <= editor["max_load"]

    def test_editor_expertise_is_list(self):
        for key, editor in EDITORS.items():
            assert isinstance(editor["expertise"], list)
            assert len(editor["expertise"]) > 0

    def test_three_editors_exist(self):
        assert len(EDITORS) == 3


# ═══════════════════════════════════════════════════════════════════════════════
#  get_editor_history
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetEditorHistory:

    def test_exact_match(self):
        history = get_editor_history("Dr. Emily Jones")
        assert history["editor"] == "Dr. Emily Jones"
        assert len(history["publications"]) > 0
        assert len(history["coauthors"]) > 0

    def test_partial_match(self):
        history = get_editor_history("Emily Jones")
        assert "Dr. Emily Jones" in history["editor"]

    def test_case_insensitive(self):
        history = get_editor_history("dr. emily jones")
        assert history["editor"] == "Dr. Emily Jones"

    def test_unknown_editor_returns_empty(self):
        history = get_editor_history("Dr. Unknown Person")
        assert history["publications"] == []
        assert history["coauthors"] == []
        assert "note" in history

    def test_coi_editor_has_coauthor_john_smith(self):
        """Dr. Emily Jones co-authored with John Smith (manuscript author)."""
        history = get_editor_history("Dr. Emily Jones")
        assert "John Smith" in history["coauthors"]

    def test_clean_editor_no_author_overlap(self):
        """Dr. Kevin Lee should have no overlap with MS-999 authors."""
        history = get_editor_history("Dr. Kevin Lee")
        ms_authors = set(a.lower() for a in get_manuscript("MS-999")["authors"])
        coauthors = set(c.lower() for c in history["coauthors"])
        assert ms_authors & coauthors == set()


# ═══════════════════════════════════════════════════════════════════════════════
#  get_editors_summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetEditorsSummary:

    def test_returns_string(self):
        summary = get_editors_summary()
        assert isinstance(summary, str)

    def test_contains_all_editor_names(self):
        summary = get_editors_summary()
        for editor in EDITORS.values():
            assert editor["name"] in summary

    def test_contains_load_info(self):
        summary = get_editors_summary()
        assert "/" in summary  # load format: "3/5"


# ═══════════════════════════════════════════════════════════════════════════════
#  EDITOR_HISTORY data structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestEditorHistoryData:

    def test_all_editors_have_history(self):
        editor_names = {e["name"] for e in EDITORS.values()}
        history_names = set(EDITOR_HISTORY.keys())
        assert editor_names == history_names

    def test_history_has_required_fields(self):
        required = {"editor", "publications", "coauthors", "recent_manuscripts_handled"}
        for name, history in EDITOR_HISTORY.items():
            missing = required - set(history.keys())
            assert not missing, f"History for '{name}' missing: {missing}"
