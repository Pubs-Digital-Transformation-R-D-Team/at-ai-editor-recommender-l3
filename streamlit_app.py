"""
Streamlit POC UI — L3 Multi-Agent Editor Assignment (Minimalist)
"""

import os, time, httpx, streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="L3 Editor Assignment", page_icon="📄", layout="wide")

# ── Global CSS — force ALL text to black ──────────────────────────────────────

st.markdown("""
<style>
/* Cream background everywhere */
[data-testid="stApp"]       { background-color: #FFF8F0 !important; }
[data-testid="stSidebar"]   { background-color: #FFF3E6 !important; }
[data-testid="stHeader"]    { background-color: #FFF8F0 !important; }

/* Force black text everywhere */
div[data-testid="stMarkdownContainer"], div[data-testid="stMarkdownContainer"] *,
.card, .card *, .opt-card, .opt-card *,
p, span, li, label, small, strong, b, em, h1, h2, h3, h4 {
  color: #111 !important;
}

/* Buttons — white text on blue, white on hover */
button[kind="primary"], button[data-testid="stBaseButton-primary"] {
  background-color: #00479D !important;
  border-color: #00479D !important;
}
button[kind="primary"] p, button[data-testid="stBaseButton-primary"] p,
button[kind="primary"] span, button[data-testid="stBaseButton-primary"] span {
  color: white !important;
}
button[kind="primary"]:hover, button[data-testid="stBaseButton-primary"]:hover {
  background-color: #003570 !important;
  border-color: #003570 !important;
}
button[kind="primary"]:hover p, button[data-testid="stBaseButton-primary"]:hover p,
button[kind="primary"]:hover span, button[data-testid="stBaseButton-primary"]:hover span {
  color: white !important;
}
/* Secondary / default buttons — blue text */
button[kind="secondary"] p, button[data-testid="stBaseButton-secondary"] p,
button[kind="secondary"] span, button[data-testid="stBaseButton-secondary"] span {
  color: #00479D !important;
}
button[kind="secondary"]:hover p, button[data-testid="stBaseButton-secondary"]:hover p,
button[kind="secondary"]:hover span, button[data-testid="stBaseButton-secondary"]:hover span {
  color: #003570 !important;
}
/* Radio / checkbox labels — keep black */
div[data-testid="stRadio"] label span,
div[data-testid="stCheckbox"] label span {
  color: #111 !important;
}

/* Except elements with explicit color classes */
.badge-blue   { background: #E3F0FF !important; color: #00479D !important; }
.badge-green  { background: #E6F9F0 !important; color: #00A65A !important; }
.badge-red    { background: #FDECEA !important; color: #C0392B !important; }
.badge-orange { background: #FEF3E6 !important; color: #E86A10 !important; }
.badge-grey   { background: #F0EDE8 !important; color: #444 !important; }
.hdr { color: white !important; }
.hdr h2, .hdr p, .hdr span { color: white !important; }
.coi-warn { color: #C0392B !important; }

.badge {
  display: inline-block; padding: 0.2em 0.65em;
  border-radius: 999px; font-size: 0.78rem; font-weight: 600; margin: 0.1em 0.15em;
}
.card {
  background: #FFFDF8; border-radius: 8px; padding: 1rem 1.2rem;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06); margin-bottom: 0.6rem;
  color: #111;
}
.card-green  { border-left: 4px solid #00A65A; background: #FEFFF8; }
.card-red    { border-left: 4px solid #C0392B; background: #FFF8F5; }
.card-blue   { border-left: 4px solid #00479D; background: #F8FBFF; }
.card-grey   { border-left: 4px solid #ccc;    background: #FFFDF8; }
.opt-card {
  border: 2px solid #E0D8CC; border-radius: 8px; padding: 0.8rem 1rem;
  margin-bottom: 0.5rem; background: #FFFDF8; color: #111;
}
.opt-card.pick    { border-color: #00479D; background: #F5F9FF; }
.opt-card.runner  { border-color: #009CDE; background: #F5FBFF; }
.opt-card.flagged { border-color: #C0392B; background: #FFF5F3; }
.load-bar { background: #E8DFD4; border-radius: 4px; height: 7px; margin: 3px 0; }
.load-fill { border-radius: 4px; height: 7px; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

DEFAULTS = dict(stage="idle", manuscript=None, coi_result=None, editor_profiles={},
                a2a_trace=[], human_decision=None, final_result=None, error_msg=None)

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

def reset():
    for k in DEFAULTS:
        del st.session_state[k]
    for k, v in DEFAULTS.items():
        st.session_state[k] = v
    st.rerun()

# ── API helpers ───────────────────────────────────────────────────────────────

def _backend_ok():
    try: return httpx.get(f"{BACKEND_URL}/health", timeout=3).status_code == 200
    except: return False

def _check_coi(ms):
    r = httpx.post(f"{BACKEND_URL}/check-coi", json={"manuscript_number": ms}, timeout=180)
    r.raise_for_status(); return r.json()

def _finalize(ms, decision, coi):
    r = httpx.post(f"{BACKEND_URL}/finalize",
                   json={"manuscript_number": ms, "human_decision": decision, "coi_result": coi}, timeout=60)
    r.raise_for_status(); return r.json()

# ── Tiny helpers ──────────────────────────────────────────────────────────────

def _b(items, style="blue"):
    return " ".join(f'<span class="badge badge-{style}">{i}</span>' for i in items)

def _bar(cur, mx):
    pct = min(int(cur / mx * 100), 100)
    c = "#C0392B" if pct >= 80 else "#E86A10" if pct >= 60 else "#009CDE"
    return (f'<div class="load-bar"><div class="load-fill" style="width:{pct}%;background:{c}"></div></div>'
            f'<small style="color:#555">{cur}/{mx} manuscripts</small>')

def _editor_card(p, label="", highlight=False):
    flagged = p.get("coi_status") == "flagged"
    cls = "card-blue" if highlight else ("card-red" if flagged else "card-green")
    tag = '<span class="badge badge-red">⚠ Flagged</span>' if flagged else '<span class="badge badge-green">✓ OK</span>'
    lbl = ""
    if label == "ai_pick": lbl = '<span class="badge badge-blue">AI Pick</span>'
    elif label == "runner_up": lbl = '<span class="badge badge-grey">Runner-up</span>'
    match = p.get("topic_match", [])
    match_h = _b(match, "green") if match else '<small style="color:#888">no direct topic overlap</small>'
    coi_r = f'<div class="coi-warn" style="font-size:0.85rem;margin-top:0.3rem">⚠ {p["coi_reason"]}</div>' if p.get("coi_reason") else ""
    pts = p.get("reasoning_points", [])
    pts_h = "".join(f"<li style='margin:2px 0;font-size:0.84rem'>{x}</li>" for x in pts)
    pts_block = f"<ul style='margin:0.3rem 0 0;padding-left:1.1rem'>{pts_h}</ul>" if pts else ""
    return (
        f'<div class="card {cls}">'
        f'<div style="margin-bottom:0.4rem"><strong>{p.get("name","?")}</strong> {tag} {lbl}</div>'
        f'<div style="margin-bottom:0.3rem">{_b(p.get("expertise",[]))}</div>'
        f'<div style="margin-bottom:0.3rem">{match_h}</div>'
        f'{_bar(p.get("current_load",0), p.get("max_load",5))}'
        f'{coi_r}{pts_block}'
        f'</div>'
    )

# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar():
    st.sidebar.markdown("### Workflow")
    s = st.session_state.stage
    steps = [("idle","Manuscript loaded"), ("coi_running","COI check"),
             ("hitl","Human decision"), ("finalizing","Finalising"), ("done","Complete")]
    done_set = {"coi_running","hitl","finalizing","done"}
    for code, label in steps:
        if s == code:
            st.sidebar.markdown(f"⏳ **{label}**")
        elif s in done_set and list(dict(steps).keys()).index(code) < list(dict(steps).keys()).index(s):
            st.sidebar.markdown(f"✅ {label}")
        else:
            st.sidebar.markdown(f"○ {label}")
    st.sidebar.divider()
    if _backend_ok():
        st.sidebar.success("Backend online", icon="🟢")
    else:
        st.sidebar.error("Backend offline", icon="🔴")
    if s != "idle":
        if st.sidebar.button("🔄 Start Over"): reset()

# ── Page: idle ────────────────────────────────────────────────────────────────

def page_idle():
    st.markdown(
        '<div class="card hdr" style="background:linear-gradient(135deg,#00479D 60%,#009CDE 100%);padding:1.2rem 1.5rem;border-radius:10px;margin-bottom:1rem">'
        '<h2 style="margin:0">📄 L3 Editor Assignment POC</h2>'
        '<p style="margin:0.2rem 0 0;opacity:0.9;font-size:0.95rem">LangGraph + Strands COI + A2A Protocol + HITL</p></div>',
        unsafe_allow_html=True)

    c1, c2 = st.columns([1.4, 1])
    with c1:
        st.markdown("#### Manuscript MS-999")
        st.markdown(
            '<div class="card card-grey">'
            '<p><b>Title:</b> Deep learning approaches for early detection of immunotherapy resistance in cancer patients</p>'
            '<p><b>Authors:</b> John Smith, Jane Doe, Robert Chen</p>'
            f'<p><b>Topics:</b> {_b(["immunotherapy","deep learning","oncology","cancer"])}</p>'
            '</div>', unsafe_allow_html=True)

        st.markdown("#### Candidate Editors")
        for n, ex in [("Dr. Emily Jones",["oncology","immunotherapy","clinical trials"]),
                      ("Dr. Kevin Lee",["immunology","cancer biology","molecular biology"]),
                      ("Dr. Maria Smith",["deep learning","bioinformatics","genomics"])]:
            st.markdown(f'<div class="card card-grey"><b>{n}</b> {_b(ex,"grey")}</div>', unsafe_allow_html=True)

    with c2:
        st.markdown("#### How it works")
        st.markdown(
            "1. **LangGraph** loads manuscript → calls Strands COI\n"
            "2. **Strands** calls back for each editor's publication history\n"
            "3. COI result returned — flagged editors revealed\n"
            "4. **You** decide: approve, override, or escalate\n"
            "5. Final assignment produced")

    st.divider()
    if not _backend_ok():
        st.error(f"Cannot reach backend at `{BACKEND_URL}`. Start servers first.", icon="🔴")
        return
    if st.button("▶ Run COI Check", type="primary"):
        st.session_state.stage = "coi_running"; st.rerun()

# ── Page: coi_running ────────────────────────────────────────────────────────

def page_coi_running():
    st.markdown("### 🤖 Agents Working…")
    with st.status("Running multi-agent COI check…", expanded=True) as status:
        for msg in ["📡 LangGraph → Strands COI", "🔄 Requesting editor histories…",
                     "⚙️ Strands reasoning over data…"]:
            st.write(msg); time.sleep(0.3)
        try:
            res = _check_coi("MS-999")
            st.session_state.manuscript = res["manuscript"]
            st.session_state.coi_result = res["coi_result"]
            st.session_state.editor_profiles = res["editor_profiles"]
            st.session_state.a2a_trace = res.get("a2a_trace", [])
            status.update(label="✅ COI check complete", state="complete")
        except Exception as e:
            status.update(label="❌ Error", state="error")
            st.session_state.stage = "error"; st.session_state.error_msg = str(e)
            st.rerun(); return
    flagged = st.session_state.coi_result.get("flagged", [])
    st.session_state.stage = "hitl" if flagged else "done_no_conflict"
    st.rerun()

# ── Page: HITL ────────────────────────────────────────────────────────────────

def page_hitl():
    st.markdown(
        '<div class="card hdr" style="background:linear-gradient(135deg,#C0392B 60%,#E86A10 100%);padding:1rem 1.4rem;border-radius:10px;margin-bottom:1rem">'
        '<h2 style="margin:0">⚡ Human Decision Required</h2>'
        '<p style="margin:0.2rem 0 0;opacity:0.9;font-size:0.9rem">A conflict of interest was detected. Review the options and decide.</p></div>',
        unsafe_allow_html=True)

    coi = st.session_state.coi_result
    profiles = st.session_state.editor_profiles
    approved = [a if isinstance(a, str) else a.get("editor") for a in coi.get("approved", [])]
    flagged = [f if isinstance(f, str) else f.get("editor") for f in coi.get("flagged", [])]

    # ── Flagged ───────────────────────────────────────────────────────────────
    st.markdown("#### ⚠️ Flagged Editor")
    for name in flagged:
        p = profiles.get(name, {"name": name, "coi_status": "flagged"})
        st.markdown(_editor_card(p), unsafe_allow_html=True)

    # ── Approved ──────────────────────────────────────────────────────────────
    st.markdown("#### ✅ Approved Alternatives")
    cols = st.columns(max(len(approved), 1))
    for i, name in enumerate(approved):
        p = profiles.get(name, {"name": name, "coi_status": "approved"})
        with cols[i]:
            st.markdown(_editor_card(p, label="ai_pick" if i == 0 else "runner_up"), unsafe_allow_html=True)

    st.divider()

    # ── Decision options ──────────────────────────────────────────────────────
    st.markdown("#### 🗳️ Your Decision")

    option_keys = []
    radio_labels = []

    for i, name in enumerate(approved):
        p = profiles.get(name, {"name": name})
        pts = p.get("reasoning_points", [])
        score = p.get("topic_match_score")
        reasoning = p.get("reasoning", "")
        tag = "⭐ AI Pick" if i == 0 else "🥈 Runner-up"
        css = "pick" if i == 0 else "runner"
        score_txt = f" · Score: {score}%" if score else ""
        pts_html = "".join(f"<li>{x}</li>" for x in pts)
        st.markdown(
            f'<div class="opt-card {css}">'
            f'<b>Option {i+1}:</b> Assign <b>{name}</b> '
            f'<span class="badge badge-blue">{tag}</span>{score_txt}'
            f'<ul style="margin:0.3rem 0 0;padding-left:1.1rem;font-size:0.88rem">{pts_html}</ul>'
            f'<div style="font-size:0.82rem;color:#555;margin-top:0.2rem"><em>{reasoning}</em></div>'
            f'</div>', unsafe_allow_html=True)
        option_keys.append(str(i + 1))
        radio_labels.append(f"Option {i+1}: Assign {name}")

    if flagged:
        pf = profiles.get(flagged[0], {"name": flagged[0]})
        pts = pf.get("reasoning_points", [])
        reasoning = pf.get("reasoning", "")
        pts_html = "".join(f"<li>{x}</li>" for x in pts)
        st.markdown(
            f'<div class="opt-card flagged">'
            f'<b>Option 3:</b> Override — assign <b>{flagged[0]}</b> '
            f'<span class="badge badge-red">⚠️ COI</span>'
            f'<ul style="margin:0.3rem 0 0;padding-left:1.1rem;font-size:0.88rem">{pts_html}</ul>'
            f'<div style="font-size:0.82rem;color:#555;margin-top:0.2rem"><em>{reasoning}</em></div>'
            f'<div style="background:#FEF3E6;border:1px solid #E86A10;border-radius:4px;'
            f'padding:0.3rem 0.6rem;margin-top:0.4rem;font-size:0.82rem;color:#7D4011">'
            f'⚠️ This editor has a detected conflict of interest.</div>'
            f'</div>', unsafe_allow_html=True)
        option_keys.append("3")
        radio_labels.append(f"Option 3: Override — assign {flagged[0]}")

    st.markdown(
        '<div class="opt-card">'
        '<b>Option 4:</b> Escalate to Editor-in-Chief'
        '<div style="font-size:0.84rem;color:#555;margin-top:0.2rem">No suitable editor or COI needs senior review.</div>'
        '</div>', unsafe_allow_html=True)
    option_keys.append("4")
    radio_labels.append("Option 4: Escalate to Editor-in-Chief")

    choice = st.radio("Select:", radio_labels, index=0, key="hitl_radio", label_visibility="collapsed")
    chosen_key = option_keys[radio_labels.index(choice)]

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("✅ Submit Decision", type="primary"):
            st.session_state.human_decision = chosen_key
            st.session_state.stage = "finalizing"; st.rerun()
    with c2:
        st.caption("Simulates `interrupt()` — LangGraph pauses until human input.")

    # A2A trace (collapsed)
    with st.expander("🔗 A2A Trace", expanded=False):
        for line in st.session_state.a2a_trace:
            st.text(line)

# ── Page: finalizing ─────────────────────────────────────────────────────────

def page_finalizing():
    st.markdown("### ⚙️ Finalising…")
    with st.spinner("Applying decision…"):
        try:
            res = _finalize("MS-999", st.session_state.human_decision, st.session_state.coi_result)
            st.session_state.final_result = res; st.session_state.stage = "done"
        except Exception as e:
            st.session_state.stage = "error"; st.session_state.error_msg = str(e)
    st.rerun()

# ── Page: done ────────────────────────────────────────────────────────────────

def page_done():
    st.markdown(
        '<div class="card hdr" style="background:linear-gradient(135deg,#00479D 60%,#00A65A 100%);padding:1rem 1.4rem;border-radius:10px;margin-bottom:1rem">'
        '<h2 style="margin:0">✅ Assignment Complete</h2></div>',
        unsafe_allow_html=True)

    final = st.session_state.final_result or {}
    sel = final.get("selected_editor", {})
    ru = final.get("runner_up")

    c1, c2 = st.columns([1.5, 1])
    with c1:
        st.markdown("#### Assigned Editor")
        if sel.get("name") == "ESCALATED":
            st.error("Escalated to editor-in-chief — no automatic assignment.")
        else:
            st.markdown(_editor_card(sel, highlight=True), unsafe_allow_html=True)
        if ru:
            st.markdown("#### Runner-up")
            st.markdown(_editor_card(ru), unsafe_allow_html=True)

    with c2:
        st.markdown("#### Summary")
        ms = st.session_state.manuscript or {}
        st.markdown(f"**Manuscript:** {ms.get('number', 'MS-999')}")
        st.markdown(f"**Decision:** {final.get('decision_label', '—')}")
        if st.session_state.human_decision:
            labels = {"1":"AI pick","2":"Runner-up","3":"Override","4":"Escalate"}
            st.markdown(f"**Human input:** {labels.get(st.session_state.human_decision, '—')}")
        coi_sum = final.get("coi_summary", {})
        if coi_sum:
            st.markdown(f"**Approved:** {coi_sum.get('approved_count',0)} · **Flagged:** {coi_sum.get('flagged_count',0)}")

        with st.expander("🔗 A2A Trace"):
            for line in (st.session_state.a2a_trace or []):
                st.text(line)

    st.divider()
    if st.button("🔄 Run Again"): reset()

# ── Page: done_no_conflict ────────────────────────────────────────────────────

def page_done_no_conflict():
    coi = st.session_state.coi_result or {}
    approved = [a if isinstance(a, str) else a.get("editor") for a in coi.get("approved", [])]
    if approved:
        try:
            res = _finalize("MS-999", "1", coi)
            st.session_state.final_result = res; st.session_state.human_decision = None
            st.session_state.stage = "done"; st.rerun()
        except Exception as e:
            st.session_state.stage = "error"; st.session_state.error_msg = str(e); st.rerun()
    else:
        st.session_state.human_decision = "4"; st.session_state.stage = "finalizing"; st.rerun()

# ── Page: error ──────────────────────────────────────────────────────────────

def page_error():
    st.error(f"❌ {st.session_state.error_msg}")
    if st.button("🔄 Start Over"): reset()

# ── Router ────────────────────────────────────────────────────────────────────

sidebar()
s = st.session_state.stage
if   s == "idle":             page_idle()
elif s == "coi_running":      page_coi_running()
elif s == "hitl":             page_hitl()
elif s == "finalizing":       page_finalizing()
elif s == "done":             page_done()
elif s == "done_no_conflict": page_done_no_conflict()
elif s == "error":            page_error()
