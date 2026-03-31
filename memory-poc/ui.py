"""
Memory POC — Streamlit UI
Run: cd memory-poc && streamlit run ui.py --server.port 8501
"""

import asyncio
import json
import streamlit as st

st.set_page_config(page_title="Memory POC", page_icon="🧠", layout="wide")

# ── Init in-memory store (no Postgres needed for demo) ────────────────────────

from langgraph.store.memory import InMemoryStore
from agent import EditorAssignmentAgent, ManuscriptSubmission
from memory import save_assignment, search_assignments, format_for_prompt

import os
os.environ["MOCK_LLM_RESPONSE"] = "true"

if "store" not in st.session_state:
    st.session_state.store = InMemoryStore()
    st.session_state.history = []

store = st.session_state.store


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.mem-card { background:#1a1a2e; border-left:4px solid #7c3aed; padding:12px 16px; margin:6px 0; border-radius:6px; }
.save-card { background:#1a2e1a; border-left:4px solid #22c55e; padding:12px 16px; margin:6px 0; border-radius:6px; }
.result-card { background:#1a2e2e; border-left:4px solid #06b6d4; padding:12px 16px; margin:6px 0; border-radius:6px; }
.badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:0.7rem; font-weight:700; }
.b-read { background:#3a1e5f; color:#c4b5fd; }
.b-write { background:#1b4e2d; color:#86efac; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────

st.title("🧠 Memory POC — Editor Assignment")
st.caption("Strands Agent + Postgres L3 Memory · Each assignment makes the next one smarter")

tab1, tab2, tab3 = st.tabs(["🎯 Assign Editor", "📜 Memory Browser", "📊 Learning Demo"])

# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — Assign Editor
# ══════════════════════════════════════════════════════════════════════════════

with tab1:
    st.markdown("### Submit a Manuscript")

    col1, col2 = st.columns(2)
    with col1:
        ms_num = st.text_input("Manuscript Number", value="JACS-2026-001")
    with col2:
        journal = st.selectbox("Journal", ["JACS", "OC", "CI", "ACSAMI"])

    if st.button("🚀 Run Assignment", type="primary"):
        agent = EditorAssignmentAgent(store=store)

        # Step 1: Search L3 memory
        st.markdown("---")
        past = run_async(search_assignments(store, ms_num, journal_id=journal))
        if past:
            st.markdown(f'<div class="mem-card"><span class="badge b-read">L3 READ</span> '
                        f'Found **{len(past)} past assignment(s)** for {journal}</div>',
                        unsafe_allow_html=True)
            for item in past:
                v = item.value
                st.markdown(f"&nbsp;&nbsp;📄 **{v['manuscript_number']}** → Editor `{v['editor_person_id']}` — "
                            f"_{v.get('reasoning', '')[:80]}_")
        else:
            st.markdown(f'<div class="mem-card"><span class="badge b-read">L3 READ</span> '
                        f'No past assignments for {journal} — **cold start**</div>',
                        unsafe_allow_html=True)

        # Step 2: Run agent
        ms = ManuscriptSubmission(ms_num, journal)
        result = run_async(agent.execute(ms))

        # Step 3: Show result
        st.markdown(f'<div class="result-card">'
                    f'**✅ Assignment Complete**<br>'
                    f'Editor: `{result["editor_person_id"]}`<br>'
                    f'Reasoning: {result["reasoning"]}<br>'
                    f'Runner-up: {result.get("runner_up", "—")}'
                    f'</div>', unsafe_allow_html=True)

        # Step 4: Confirm L3 write
        st.markdown(f'<div class="save-card"><span class="badge b-write">L3 WRITE</span> '
                    f'Saved to memory: **{ms_num}** → `{result["editor_person_id"]}`</div>',
                    unsafe_allow_html=True)

        st.session_state.history.append({
            "manuscript": ms_num,
            "journal": journal,
            "editor": result["editor_person_id"],
            "reasoning": result["reasoning"],
        })

        st.info("💡 Submit another manuscript — the agent will now see this assignment in memory!")

# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — Memory Browser
# ══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.markdown("### 📜 L3 Memory — Stored Assignments")

    journals = ["JACS", "OC", "CI", "ACSAMI"]
    all_items = []
    for j in journals:
        items = run_async(store.asearch(("assignments", j)))
        all_items.extend([(j, item) for item in items])

    if all_items:
        st.metric("Total assignments in memory", len(all_items))
        for j, item in all_items:
            v = item.value
            with st.expander(f"📄 {v.get('manuscript_number', '?')} ({j}) → {v.get('editor_person_id', '?')}"):
                st.json(v)
    else:
        st.info("Memory is empty. Go to **Assign Editor** tab and run some assignments.")

    st.markdown("---")
    if st.button("🗑️ Clear All Memory"):
        st.session_state.store = InMemoryStore()
        st.session_state.history = []
        st.success("Memory cleared!")
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — Learning Demo
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.markdown("### 📊 Learning Loop Demo")
    st.caption("Run 3 assignments in sequence to see memory build up")

    if st.button("▶️ Run 3 Assignments", type="primary"):
        demo_store = InMemoryStore()
        agent = EditorAssignmentAgent(store=demo_store)

        manuscripts = [
            ("JACS-DEMO-001", "JACS", "Catalysis for organic synthesis"),
            ("JACS-DEMO-002", "JACS", "Novel catalyst design methods"),
            ("JACS-DEMO-003", "JACS", "Asymmetric catalysis advances"),
        ]

        for i, (num, journal, topic) in enumerate(manuscripts, 1):
            st.markdown(f"---")
            st.markdown(f"#### Assignment #{i}: {num}")
            st.caption(topic)

            # Search
            past = run_async(search_assignments(demo_store, topic, journal_id=journal))
            if past:
                st.markdown(f'<div class="mem-card"><span class="badge b-read">L3 READ</span> '
                            f'Found **{len(past)} past assignment(s)** — agent has context!</div>',
                            unsafe_allow_html=True)
                prompt_text = format_for_prompt(past)
                with st.expander("What the LLM sees from memory"):
                    st.code(prompt_text, language="markdown")
            else:
                st.markdown(f'<div class="mem-card"><span class="badge b-read">L3 READ</span> '
                            f'No history yet — cold start</div>', unsafe_allow_html=True)

            # Execute
            ms = ManuscriptSubmission(num, journal)
            result = run_async(agent.execute(ms))

            st.markdown(f'<div class="save-card"><span class="badge b-write">L3 WRITE</span> '
                        f'{num} → `{result["editor_person_id"]}` saved to memory</div>',
                        unsafe_allow_html=True)

        st.success("✅ Done! Assignment #2 and #3 had memory context that #1 didn't. That's the learning loop.")

    # Show session history
    if st.session_state.history:
        st.markdown("---")
        st.markdown("### Session History")
        for i, h in enumerate(st.session_state.history, 1):
            st.markdown(f"{i}. **{h['manuscript']}** ({h['journal']}) → `{h['editor']}` — _{h['reasoning']}_")

