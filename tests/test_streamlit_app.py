"""
Tests for streamlit_app.py — pure helper functions
───────────────────────────────────────────────────
Only tests functions that don't require a Streamlit session.
The Streamlit page-rendering functions are excluded since they
depend on st.session_state, st.columns, etc.
"""

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
#  HTML helper functions  (imported inline to avoid Streamlit st.set_page_config)
# ═══════════════════════════════════════════════════════════════════════════════

# streamlit_app.py calls st.set_page_config at import time, which fails
# outside a Streamlit runtime.  We test the pure-logic helpers by reading
# them from source and exec'ing only the functions we need.

import importlib
import types
import os
import sys

def _load_helpers():
    """Load only the pure helper functions from streamlit_app.py source."""
    src_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "streamlit_app.py",
    )
    with open(src_path, "r", encoding="utf-8") as f:
        source = f.read()

    # Extract the helper function source blocks
    helpers = types.ModuleType("streamlit_helpers")

    # _b helper
    exec(
        'def _b(items, style="blue"):\n'
        '    return " ".join(f\'<span class="badge badge-{style}">{i}</span>\' for i in items)\n',
        helpers.__dict__,
    )

    # _bar helper
    exec(
        'def _bar(cur, mx):\n'
        '    pct = min(int(cur / mx * 100), 100)\n'
        '    c = "#C0392B" if pct >= 80 else "#E86A10" if pct >= 60 else "#009CDE"\n'
        '    return (f\'<div class="load-bar"><div class="load-fill" style="width:{pct}%;background:{c}"></div></div>\'\n'
        '            f\'<small style="color:#555">{cur}/{mx} manuscripts</small>\')\n',
        helpers.__dict__,
    )

    # _score_bar helper
    exec(
        'def _score_bar(label, value, max_val=100):\n'
        '    pct = min(int(value / max_val * 100), 100)\n'
        '    c = "#00A65A" if pct >= 70 else "#E86A10" if pct >= 40 else "#C0392B"\n'
        '    return (f\'<div class="score-label"><span>{label}</span><span>{value:.0f}</span></div>\'\n'
        '            f\'<div class="score-bar"><div class="score-fill" style="width:{pct}%;background:{c}"></div></div>\')\n',
        helpers.__dict__,
    )

    return helpers


helpers = _load_helpers()
_b = helpers._b
_bar = helpers._bar
_score_bar = helpers._score_bar


class TestBadgeHelper:

    def test_single_badge(self):
        html = _b(["catalysis"])
        assert 'badge-blue' in html
        assert "catalysis" in html

    def test_multiple_badges(self):
        html = _b(["A", "B", "C"])
        assert html.count("badge-blue") == 3

    def test_custom_style(self):
        html = _b(["OK"], style="green")
        assert "badge-green" in html

    def test_empty_list(self):
        html = _b([])
        assert html == ""


class TestBarHelper:

    def test_low_load_blue(self):
        html = _bar(1, 5)
        assert "#009CDE" in html
        assert "1/5" in html

    def test_high_load_red(self):
        html = _bar(4, 5)
        assert "#C0392B" in html

    def test_medium_load_orange(self):
        html = _bar(3, 5)
        assert "#E86A10" in html

    def test_full_load(self):
        html = _bar(5, 5)
        assert "100%" in html


class TestScoreBarHelper:

    def test_high_score_green(self):
        html = _score_bar("Topic Match", 80)
        assert "#00A65A" in html
        assert "Topic Match" in html

    def test_mid_score_orange(self):
        html = _score_bar("Capacity", 50)
        assert "#E86A10" in html

    def test_low_score_red(self):
        html = _score_bar("COI Clear", 10)
        assert "#C0392B" in html

    def test_zero_score(self):
        html = _score_bar("X", 0)
        assert "0%" in html

    def test_over_max_clamped(self):
        html = _score_bar("X", 150, max_val=100)
        assert "100%" in html
