"""
Streamlit POC UI — L3 Multi-Agent Editor Assignment
═════════════════════════════════════════════════════

Demonstrates:
  - Two-agent A2A communication (LangGraph ↔ Strands)
  - Real-time workflow visualization  
  - Human-in-the-Loop (HITL) decision interface

Usage:
  streamlit run streamlit_app.py

Backend must be running on port 8000:
  python langgraph_service/callback_server.py
  python strands_service/server.py

  OR — point at EKS cluster via kubectl port-forward:
  kubectl port-forward -n er svc/at-ai-editor-recommender-langgraph-service 8000:8000
"""

import json
import os
import time

import httpx
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="L3 Editor Assignment POC",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ACS color palette */
:root {
  --acs-blue:   #00479D;
  --acs-light:  #009CDE;
  --green:      #00A65A;
  --red:        #C0392B;
  --orange:     #E86A10;
  --grey-bg:    #F4F6F9;
  --card-bg:    #FFFFFF;
}

/* Header bar */
.acs-header {
  background: linear-gradient(135deg, #00479D 60%, #009CDE 100%);
  color: white;
  padding: 1.4rem 2rem;
  border-radius: 12px;
  margin-bottom: 1.5rem;
}
.acs-header h1 { margin: 0; font-size: 1.8rem; font-weight: 700; }
.acs-header p  { margin: 0.3rem 0 0; opacity: 0.85; font-size: 1rem; }

/* Cards */
.card {
  background: var(--card-bg);
  border-radius: 10px;
  padding: 1.2rem 1.4rem;
  box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  margin-bottom: 0.8rem;
}
.card-approved  { border-left: 5px solid var(--green); }
.card-flagged   { border-left: 5px solid var(--red); }
.card-selected  { border-left: 5px solid var(--acs-blue); background: #F0F7FF; }
.card-neutral   { border-left: 5px solid var(--acs-light); }

/* Badges */
.badge {
  display: inline-block;
  padding: 0.2em 0.7em;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  margin: 0.1em 0.2em;
}
.badge-blue   { background: #E3F0FF; color: var(--acs-blue); }
.badge-green  { background: #E6F9F0; color: var(--green); }
.badge-red    { background: #FDECEA; color: var(--red); }
.badge-orange { background: #FEF3E6; color: var(--orange); }
.badge-grey   { background: #EAEAEA; color: #555; }

/* A2A trace */
.trace-line {
  font-family: monospace;
  font-size: 0.85rem;
  padding: 0.2rem 0;
  color: #444;
}
.trace-main   { color: var(--acs-blue); font-weight: 600; }
.trace-cb     { color: var(--orange); padding-left: 1.5rem; }
.trace-result { color: var(--green); padding-left: 1.5rem; }

/* Progress steps */
.step { padding: 0.3rem 0; font-size: 0.92rem; }
.step-done    { color: var(--green); }
.step-current { color: var(--acs-blue); font-weight: 700; }
.step-pending { color: #AAAAAA; }

/* Workload bar */
.load-bar-bg { background: #E0E0E0; border-radius: 4px; height: 8px; margin: 4px 0; }
.load-bar-fg { background: var(--acs-light); border-radius: 4px; height: 8px; }
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────

def _init():
    defaults = {
        "stage": "idle",           # idle | coi_running | hitl | finalizing | done | error
        "manuscript": None,
        "coi_result": None,
        "editor_profiles": {},
        "a2a_trace": [],
        "human_decision": None,
        "final_result": None,
        "error_msg": None,
        "hitl_choice": "1",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init()


def reset():
    for k in ["stage", "manuscript", "coi_result", "editor_profiles", "a2a_trace",
              "human_decision", "final_result", "error_msg", "hitl_choice"]:
        del st.session_state[k]
    _init()
    st.rerun()


# ── API helpers ───────────────────────────────────────────────────────────────

def _check_backend() -> bool:
    try:
        r = httpx.get(f"{BACKEND_URL}/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _check_coi(ms_number: str) -> dict:
    r = httpx.post(
        f"{BACKEND_URL}/check-coi",
        json={"manuscript_number": ms_number},
        timeout=180.0,
    )
    r.raise_for_status()
    return r.json()


def _finalize(ms_number: str, decision: str, coi_result: dict) -> dict:
    r = httpx.post(
        f"{BACKEND_URL}/finalize",
        json={
            "manuscript_number": ms_number,
            "human_decision": decision,
            "coi_result": coi_result,
        },
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()


# ── UI helpers ────────────────────────────────────────────────────────────────

def _badges(items: list[str], style: str = "blue") -> str:
    return " ".join(f'<span class="badge badge-{style}">{i}</span>' for i in items)


def _load_bar(current: int, max_load: int) -> str:
    pct = min(int(current / max_load * 100), 100)
    color = "#C0392B" if pct >= 80 else "#E86A10" if pct >= 60 else "#009CDE"
    return (
        f'<div class="load-bar-bg">'
        f'<div class="load-bar-fg" style="width:{pct}%; background:{color};"></div>'
        f'</div>'
        f'<small>{current}/{max_load} manuscripts</small>'
    )


def _editor_card(profile: dict, label: str = "", highlight: bool = False) -> str:
    status   = profile.get("coi_status", "approved")
    cls      = "card-selected" if highlight else ("card-flagged" if status == "flagged" else "card-approved")
    tag      = f'<span class="badge badge-red">⚠ Flagged</span>' if status == "flagged" else \
               f'<span class="badge badge-green">✓ Approved</span>'
    exp_html = _badges(profile.get("expertise", []), "blue")
    match    = profile.get("topic_match", [])
    match_html = (
        _badges(match, "green") + " &nbsp;<small style='color:#888'>topic match</small>"
        if match else "<small style='color:#888'>no direct topic overlap</small>"
    )
    load_html = _load_bar(profile.get("current_load", 0), profile.get("max_load", 5))
    reason_html = (
        f'<p style="color:#C0392B; font-size:0.85rem; margin:0.4rem 0">⚠ {profile["coi_reason"]}</p>'
        if profile.get("coi_reason") else ""
    )
    reasoning = profile.get("reasoning", "")

    return f"""
<div class="card {cls}" style="color:#1a1a1a">
  <div style="display:flex; align-items:center; gap:0.6rem; margin-bottom:0.5rem">
    <strong style="font-size:1.05rem; color:#1a1a1a">{profile['name']}</strong>
    {tag}
    {"<span class='badge badge-blue'>AI Pick #1</span>" if label == "ai_pick" else ""}
    {"<span class='badge badge-grey'>Runner-up</span>" if label == "runner_up" else ""}
  </div>
  <div style="margin-bottom:0.4rem">{exp_html}</div>
  <div style="margin-bottom:0.4rem">{match_html}</div>
  <div style="margin-bottom:0.4rem">{load_html}</div>
  {reason_html}
  <p style="font-size:0.82rem; color:#555; margin:0.4rem 0 0">{reasoning}</p>
</div>
"""


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar():
    st.sidebar.markdown("## 🔄 Workflow")

    stage = st.session_state.stage

    steps = [
        ("idle",       "1. Manuscript loaded",         "coi_running finalizing hitl done"),
        ("coi_running","2. COI check in progress…",   ""),
        ("hitl",       "3. Human decision required",  "finalizing done"),
        ("finalizing", "4. Finalising assignment…",   ""),
        ("done",       "5. Assignment complete",       "done"),
    ]

    for s, label, done_stages in steps:
        if stage in done_stages or (s == "coi_running" and stage in ("hitl", "finalizing", "done")):
            st.sidebar.markdown(f'<div class="step step-done">✅ {label}</div>', unsafe_allow_html=True)
        elif stage == s:
            st.sidebar.markdown(f'<div class="step step-current">⏳ {label}</div>', unsafe_allow_html=True)
        else:
            st.sidebar.markdown(f'<div class="step step-pending">○ {label}</div>', unsafe_allow_html=True)

    st.sidebar.divider()
    st.sidebar.markdown(f"**Backend:** `{BACKEND_URL}`")
    backend_ok = _check_backend()
    if backend_ok:
        st.sidebar.success("Backend online ✓", icon="🟢")
    else:
        st.sidebar.error("Backend offline", icon="🔴")
        st.sidebar.caption(
            "Start backend:\n```\npython langgraph_service/callback_server.py\n"
            "python strands_service/server.py\n```\n\n"
            "Or set `BACKEND_URL` env var to point at EKS port-forward."
        )

    if stage != "idle":
        st.sidebar.divider()
        if st.sidebar.button("🔄 Start Over"):
            reset()


# ── Stage: idle ───────────────────────────────────────────────────────────────

def render_idle():
    st.markdown("""
<div class="acs-header">
  <h1>📄 L3 Editor Assignment POC</h1>
  <p>LangGraph Orchestrator + Strands COI Specialist + A2A Protocol + Human-in-the-Loop</p>
</div>
""", unsafe_allow_html=True)

    col1, col2 = st.columns([1.4, 1])

    with col1:
        st.subheader("Manuscript MS-999")
        st.markdown("""
<div class="card card-neutral">
  <p><strong>Title:</strong> Deep learning approaches for early detection of immunotherapy
  resistance in cancer patients</p>
  <p><strong>Authors:</strong> John Smith, Jane Doe, Robert Chen</p>
  <p><strong>Journal:</strong> CI &nbsp;|&nbsp; <strong>Topics:</strong>
  <span class="badge badge-blue">immunotherapy</span>
  <span class="badge badge-blue">deep learning</span>
  <span class="badge badge-blue">oncology</span>
  <span class="badge badge-blue">cancer</span>
  </p>
</div>
""", unsafe_allow_html=True)

        st.subheader("Candidate Editors")
        for name, exp in [
            ("Dr. Emily Jones",  ["oncology", "immunotherapy", "clinical trials"]),
            ("Dr. Kevin Lee",    ["immunology", "cancer biology", "molecular biology"]),
            ("Dr. Maria Smith",  ["deep learning", "bioinformatics", "genomics"]),
        ]:
            badge_html = _badges(exp, "grey")
            st.markdown(
                f'<div class="card" style="margin-bottom:0.5rem">'
                f'<strong>{name}</strong> &nbsp; {badge_html}</div>',
                unsafe_allow_html=True,
            )

    with col2:
        st.subheader("How it works")
        st.markdown("""
1. **LangGraph** loads the manuscript and asks the COI specialist to check for conflicts
2. **Strands COI** (Agent 2) calls back to LangGraph for each editor's publication history
3. COI result returned — flagged editors revealed
4. **You** decide: approve, override, or escalate
5. Final assignment produced
""")
        st.markdown("""
<div class="card card-neutral">
  <b>A2A flow</b><br>
  <code style="font-size:0.82rem">
  LangGraph → Strands COI<br>
  &nbsp;&nbsp;Strands → LangGraph (history)<br>
  &nbsp;&nbsp;Strands → LangGraph (history)<br>
  &nbsp;&nbsp;Strands → LangGraph (history)<br>
  Strands → LangGraph (result)<br>
  Human decision ⚡<br>
  Final assignment ✅
  </code>
</div>
""", unsafe_allow_html=True)

    st.divider()
    if not _check_backend():
        st.error(
            f"⚠️ Cannot reach backend at `{BACKEND_URL}`. "
            "Start the servers or set `BACKEND_URL` to a running instance.",
            icon="🔴",
        )
        return

    if st.button("▶ Run COI Check", type="primary", use_container_width=False):
        st.session_state.stage = "coi_running"
        st.rerun()


# ── Stage: coi_running ────────────────────────────────────────────────────────

def render_coi_running():
    st.markdown("""
<div class="acs-header">
  <h1>🤖 Agents Working…</h1>
  <p>LangGraph is calling Strands COI via A2A. Strands is calling back for editor histories.</p>
</div>
""", unsafe_allow_html=True)

    with st.status("Running multi-agent COI check…", expanded=True) as status:
        st.write("📡 LangGraph → Strands COI: `POST /tasks/send`")
        time.sleep(0.3)
        st.write("🔄 Strands → LangGraph: requesting Dr. Emily Jones history…")
        time.sleep(0.3)
        st.write("🔄 Strands → LangGraph: requesting Dr. Kevin Lee history…")
        time.sleep(0.3)
        st.write("🔄 Strands → LangGraph: requesting Dr. Maria Smith history…")
        time.sleep(0.3)
        st.write("⚙️  Strands LLM reasoning over publication data…")

        try:
            result = _check_coi("MS-999")
            st.session_state.manuscript     = result["manuscript"]
            st.session_state.coi_result     = result["coi_result"]
            st.session_state.editor_profiles = result["editor_profiles"]
            st.session_state.a2a_trace      = result.get("a2a_trace", [])
            status.update(label="✅ COI check complete", state="complete")
        except httpx.HTTPStatusError as e:
            status.update(label="❌ Backend error", state="error")
            st.session_state.stage     = "error"
            st.session_state.error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            st.rerun()
            return
        except Exception as e:
            status.update(label="❌ Error", state="error")
            st.session_state.stage     = "error"
            st.session_state.error_msg = str(e)
            st.rerun()
            return

    flagged = st.session_state.coi_result.get("flagged", [])
    st.session_state.stage = "hitl" if flagged else "done_no_conflict"
    st.rerun()


def _render_ai_recommendation_summary(approved: list, flagged: list, profiles: dict):
    """Blue summary box showing AI's ranked suggestions with justification before the HITL form."""
    if not approved:
        return

    rows = []
    for i, name in enumerate(approved):
        p = profiles.get(name, {"name": name})
        rank_label = "🥇 AI Recommendation #1" if i == 0 else f"🥈 Alternative #{i+1}"
        points = p.get("reasoning_points", [])
        points_html = "".join(
            f"<li style='margin:2px 0; font-size:0.85rem; color:#333'>{pt}</li>"
            for pt in points
        )
        exp_html = _badges(p.get("expertise", []), "blue")
        score = p.get("topic_match_score", 0)
        score_label = f"{score}% topic match" if score else "low topic match"
        rows.append(
            f"<div style='flex:1; min-width:220px; background:#EBF5FB; border-radius:8px; "
            f"padding:0.9rem 1rem; border-left:4px solid {'#00479D' if i==0 else '#009CDE'}; color:#1a1a1a'>"
            f"<div style='font-weight:700; color:#00479D; margin-bottom:0.3rem'>{rank_label}</div>"
            f"<div style='font-size:1rem; font-weight:600; color:#1a1a1a; margin-bottom:0.3rem'>{name}</div>"
            f"<div style='font-size:0.78rem; color:#555; margin-bottom:0.4rem'>Score: {score_label}</div>"
            f"<div style='margin-bottom:0.4rem'>{exp_html}</div>"
            f"<ul style='margin:0.3rem 0 0 0; padding-left:1.1rem'>{points_html}</ul>"
            f"</div>"
        )

    # Flagged summary
    flagged_items = ""
    for name in flagged:
        p = profiles.get(name, {"name": name})
        reason = p.get("coi_reason", "Conflict detected")
        pts = p.get("reasoning_points", [])
        pts_html = "".join(
            f"<li style='margin:2px 0; font-size:0.82rem; color:#7B241C'>{pt}</li>"
            for pt in pts
        )
        flagged_items += (
            f"<div style='margin-bottom:0.3rem; color:#7B241C'>"
            f"<strong style='color:#C0392B'>{name}</strong> — {reason}</div>"
            f"<ul style='margin:0; padding-left:1.1rem'>{pts_html}</ul>"
        )

    flagged_section = (
        f"<div style='background:#FDECEA; border-radius:8px; padding:0.8rem 1rem; "
        f"border-left:4px solid #C0392B; min-width:200px; color:#7B241C'>"
        f"<div style='font-weight:700; color:#C0392B; margin-bottom:0.5rem'>⛔ Excluded (COI)</div>"
        f"{flagged_items}"
        f"</div>"
        if flagged_items else ""
    )

    cards_html = "".join(rows)
    st.markdown(
        f"<div style='background:#D6EAF8; border-radius:10px; padding:1rem 1.2rem; margin-bottom:1rem; color:#1a1a1a'>"
        f"<div style='font-weight:700; color:#00479D; font-size:1rem; margin-bottom:0.7rem'>"
        f"🤖 AI Recommendation Summary"
        f"</div>"
        f"<div style='display:flex; gap:0.8rem; flex-wrap:wrap; align-items:flex-start'>"
        f"{cards_html}{flagged_section}"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _decision_option_card(
    number: str,
    action: str,
    tag: str,
    tag_bg: str,
    tag_color: str,
    border_color: str,
    bg_color: str,
    points: list[str],
    reasoning: str,
    score: int | None = None,
    warn: str = "",
) -> str:
    """Render a rich decision-option card (HTML) for the HITL panel."""
    pts_html = "".join(
        f"<li style='margin:3px 0; font-size:0.85rem; color:#333'>{p}</li>"
        for p in points
    )
    score_html = (
        f"<span style='font-size:0.78rem; color:#555; margin-left:0.5rem'>Topic match score: {score}%</span>"
        if score is not None else ""
    )
    warn_html = (
        f"<div style='background:#FEF3E6; border:1px solid #E86A10; border-radius:5px; "
        f"padding:0.4rem 0.7rem; margin-top:0.5rem; color:#7D4011; font-size:0.83rem'>⚠️ {warn}</div>"
        if warn else ""
    )
    reasoning_html = (
        f"<p style='font-size:0.82rem; color:#555; margin:0.5rem 0 0'><em>{reasoning}</em></p>"
        if reasoning else ""
    )
    return (
        f"<div style='border:2px solid {border_color}; border-radius:10px; padding:0.9rem 1.1rem; "
        f"margin-bottom:0.7rem; background:{bg_color}; color:#1a1a1a'>"
        f"  <div style='display:flex; align-items:center; gap:0.6rem; margin-bottom:0.5rem'>"
        f"    <span style='font-weight:800; font-size:1.05rem; color:{border_color}'>Option {number}</span>"
        f"    <span style='font-size:0.97rem; font-weight:600; color:#1a1a1a'>{action}</span>"
        f"    <span style='background:{tag_bg}; color:{tag_color}; border-radius:4px; "
        f"    padding:0.15em 0.6em; font-size:0.76rem; font-weight:700'>{tag}</span>"
        f"    {score_html}"
        f"  </div>"
        f"  <ul style='margin:0.3rem 0 0; padding-left:1.2rem'>{pts_html}</ul>"
        f"  {reasoning_html}"
        f"  {warn_html}"
        f"</div>"
    )


# ── Stage: hitl ───────────────────────────────────────────────────────────────

def render_hitl():
    st.markdown("""
<div class="acs-header" style="background: linear-gradient(135deg, #C0392B 60%, #E86A10 100%);">
  <h1>⚡ Human Decision Required</h1>
  <p>A conflict of interest was detected. Please review and make a decision.</p>
</div>
""", unsafe_allow_html=True)

    coi     = st.session_state.coi_result
    profiles = st.session_state.editor_profiles
    approved = [a if isinstance(a, str) else a.get("editor") for a in coi.get("approved", [])]
    flagged_raw = coi.get("flagged", [])
    flagged  = [f if isinstance(f, str) else f.get("editor") for f in flagged_raw]

    # ── AI Recommendation Summary ──────────────────────────────────────────────
    _render_ai_recommendation_summary(approved, flagged, profiles)

    # ── A2A trace ─────────────────────────────────────────────────────────────
    with st.expander("🔗 Agent Communication Trace", expanded=False):
        for line in st.session_state.a2a_trace:
            if line.startswith("  ") and "callback" not in line.lower() and "returned" not in line.lower():
                st.markdown(
                    f'<div class="trace-line trace-cb">{line}</div>',
                    unsafe_allow_html=True,
                )
            elif "returned" in line.lower() or "result" in line.lower():
                st.markdown(
                    f'<div class="trace-line trace-result">{line}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="trace-line trace-main">{line}</div>',
                    unsafe_allow_html=True,
                )

    st.divider()

    # ── Flagged editor ────────────────────────────────────────────────────────
    st.subheader("⚠️ Flagged Editor")
    for name in flagged:
        p = profiles.get(name, {"name": name, "coi_status": "flagged"})
        st.markdown(_editor_card(p), unsafe_allow_html=True)

    st.divider()

    # ── Approved alternatives ─────────────────────────────────────────────────
    st.subheader("✅ Approved Alternatives")
    if not approved:
        st.warning("No clean alternatives available — escalation is recommended.")
    else:
        cols = st.columns(min(len(approved), 3))
        for i, name in enumerate(approved):
            p = profiles.get(name, {"name": name, "coi_status": "approved"})
            label = "ai_pick" if i == 0 else "runner_up"
            with cols[i]:
                st.markdown(_editor_card(p, label=label), unsafe_allow_html=True)

    st.divider()

    # ── Decision panel ────────────────────────────────────────────────────────
    st.subheader("🗳️  Your Decision")
    st.caption(
        "Each option below shows the AI's reasoning. Review, then select and submit."
    )

    # Build structured option list
    option_keys   = []
    radio_labels  = []
    cards_html    = []

    if len(approved) >= 1:
        p1   = profiles.get(approved[0], {"name": approved[0]})
        cards_html.append(_decision_option_card(
            number="1",
            action=f"Assign {approved[0]}",
            tag="⭐ AI Recommendation",
            tag_bg="#00479D",
            tag_color="#FFFFFF",
            border_color="#00479D",
            bg_color="#EBF5FB",
            points=p1.get("reasoning_points", []),
            reasoning=p1.get("reasoning", ""),
            score=p1.get("topic_match_score"),
        ))
        option_keys.append("1")
        radio_labels.append(f"1 · Assign {approved[0]} (AI recommendation)")

    if len(approved) >= 2:
        p2 = profiles.get(approved[1], {"name": approved[1]})
        cards_html.append(_decision_option_card(
            number="2",
            action=f"Assign {approved[1]}",
            tag="🥈 Runner-up",
            tag_bg="#009CDE",
            tag_color="#FFFFFF",
            border_color="#009CDE",
            bg_color="#EBF8FF",
            points=p2.get("reasoning_points", []),
            reasoning=p2.get("reasoning", ""),
            score=p2.get("topic_match_score"),
        ))
        option_keys.append("2")
        radio_labels.append(f"2 · Assign {approved[1]} (runner-up)")

    if flagged:
        pf = profiles.get(flagged[0], {"name": flagged[0]})
        cards_html.append(_decision_option_card(
            number="3",
            action=f"Override — assign {flagged[0]}",
            tag="⚠️ COI Flagged",
            tag_bg="#FDECEA",
            tag_color="#C0392B",
            border_color="#C0392B",
            bg_color="#FDF6F6",
            points=pf.get("reasoning_points", []),
            reasoning=pf.get("reasoning", ""),
            score=pf.get("topic_match_score"),
            warn="This editor has a detected conflict of interest. Override only if justified.",
        ))
        option_keys.append("3")
        radio_labels.append(f"3 · Override — assign {flagged[0]} (COI flagged)")

    # Escalate option
    cards_html.append(
        f"<div style='border:2px solid #888; border-radius:10px; padding:0.9rem 1.1rem; "
        f"margin-bottom:0.7rem; background:#F8F8F8; color:#1a1a1a'>"
        f"  <div style='display:flex; align-items:center; gap:0.6rem; margin-bottom:0.3rem'>"
        f"    <span style='font-weight:800; font-size:1.05rem; color:#555'>Option 4</span>"
        f"    <span style='font-size:0.97rem; font-weight:600; color:#1a1a1a'>Escalate to Editor-in-Chief</span>"
        f"    <span style='background:#EAEAEA; color:#555; border-radius:4px; "
        f"    padding:0.15em 0.6em; font-size:0.76rem; font-weight:700'>🔺 Escalate</span>"
        f"  </div>"
        f"  <p style='font-size:0.85rem; color:#555; margin:0.3rem 0 0'>"
        f"  Use when no suitable editor is available or the COI situation requires senior review."
        f"  </p>"
        f"</div>"
    )
    option_keys.append("4")
    radio_labels.append("4 · Escalate to Editor-in-Chief")

    # Render option cards
    st.markdown("".join(cards_html), unsafe_allow_html=True)

    st.markdown(
        "<div style='font-weight:600; color:#1a1a1a; margin-bottom:0.3rem'>Select your decision:</div>",
        unsafe_allow_html=True,
    )
    choice_label = st.radio(
        "Select your decision:",
        radio_labels,
        index=0,
        key="hitl_radio",
        label_visibility="collapsed",
    )
    chosen_key = option_keys[radio_labels.index(choice_label)]

    col_btn, col_note = st.columns([1, 3])
    with col_btn:
        if st.button("✅ Submit Decision", type="primary"):
            st.session_state.human_decision = chosen_key
            st.session_state.stage = "finalizing"
            st.rerun()
    with col_note:
        st.caption(
            "This simulates the HITL step where the LangGraph graph pauses at an "
            "`interrupt()` node and waits for human input before resuming."
        )


# ── Stage: finalizing ────────────────────────────────────────────────────────

def render_finalizing():
    st.markdown("""
<div class="acs-header">
  <h1>⚙️ Finalising…</h1>
  <p>Applying your decision and completing the assignment.</p>
</div>
""", unsafe_allow_html=True)

    with st.spinner("Finalising assignment…"):
        try:
            result = _finalize(
                "MS-999",
                st.session_state.human_decision,
                st.session_state.coi_result,
            )
            st.session_state.final_result = result
            st.session_state.stage = "done"
        except Exception as e:
            st.session_state.stage = "error"
            st.session_state.error_msg = str(e)

    st.rerun()


# ── Stage: done (with or without conflict) ────────────────────────────────────

def render_done(had_hitl: bool = True):
    st.markdown("""
<div class="acs-header" style="background: linear-gradient(135deg, #00479D 60%, #00A65A 100%);">
  <h1>✅ Assignment Complete</h1>
  <p>The editor assignment workflow has finished.</p>
</div>
""", unsafe_allow_html=True)

    final   = st.session_state.final_result or {}
    sel     = final.get("selected_editor", {})
    ru      = final.get("runner_up")
    coi     = st.session_state.coi_result or {}
    ms      = st.session_state.manuscript or {}

    # ── Selected editor card ──────────────────────────────────────────────────
    col_main, col_side = st.columns([1.5, 1])

    with col_main:
        st.subheader("📌 Assigned Editor")
        if sel.get("name") == "ESCALATED":
            st.error("Escalated to editor-in-chief — no automatic assignment made.")
        else:
            st.markdown(_editor_card(sel, highlight=True), unsafe_allow_html=True)

        if ru:
            st.subheader("🥈 Runner-up")
            st.markdown(_editor_card(ru), unsafe_allow_html=True)

    with col_side:
        st.subheader("📋 Workflow Summary")

        summary_rows = [
            ("Manuscript",     ms.get("number", "MS-999")),
            ("Decision",       final.get("decision_label", "—")),
        ]
        if had_hitl and st.session_state.human_decision:
            labels = {"1": "Option 1 — AI pick", "2": "Option 2 — Runner-up",
                      "3": "Option 3 — Override", "4": "Option 4 — Escalate"}
            summary_rows.append(("Human input", labels.get(st.session_state.human_decision, "—")))

        coi_sum = final.get("coi_summary", {})
        if coi_sum:
            summary_rows.append(("Approved editors", str(coi_sum.get("approved_count", 0))))
            summary_rows.append(("Flagged editors",  str(coi_sum.get("flagged_count",  0))))

        for k, v in summary_rows:
            c1, c2 = st.columns([1, 1.5])
            c1.markdown(f"**{k}**")
            c2.markdown(v)

        st.divider()
        st.subheader("🔗 A2A Trace")
        for line in (st.session_state.a2a_trace or []):
            style = "trace-cb" if line.startswith("  ") else "trace-main"
            if "result" in line.lower() or "returned" in line.lower():
                style = "trace-result"
            st.markdown(
                f'<div class="trace-line {style}">{line}</div>',
                unsafe_allow_html=True,
            )

    st.divider()
    if st.button("🔄 Run Again"):
        reset()


# ── Stage: done_no_conflict ───────────────────────────────────────────────────

def render_done_no_conflict():
    """No conflicts found — auto-assign and skip HITL."""
    coi = st.session_state.coi_result or {}
    approved = [a if isinstance(a, str) else a.get("editor") for a in coi.get("approved", [])]

    if approved:
        try:
            result = _finalize("MS-999", "1", coi)
            st.session_state.final_result = result
            st.session_state.human_decision = None
            st.session_state.stage = "done"
            st.rerun()
        except Exception as e:
            st.session_state.stage = "error"
            st.session_state.error_msg = str(e)
            st.rerun()
    else:
        st.session_state.human_decision = "4"
        st.session_state.stage = "finalizing"
        st.rerun()


# ── Stage: error ─────────────────────────────────────────────────────────────

def render_error():
    st.error(f"❌ An error occurred: {st.session_state.error_msg}")
    st.caption("Is the backend running? Check the sidebar for status.")
    if st.button("🔄 Start Over"):
        reset()


# ── Router ────────────────────────────────────────────────────────────────────

render_sidebar()

stage = st.session_state.stage

if   stage == "idle":             render_idle()
elif stage == "coi_running":      render_coi_running()
elif stage == "hitl":             render_hitl()
elif stage == "finalizing":       render_finalizing()
elif stage == "done":             render_done(had_hitl=st.session_state.human_decision is not None)
elif stage == "done_no_conflict": render_done_no_conflict()
elif stage == "error":            render_error()
