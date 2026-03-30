"""
Travel Planner Memory POC — Streamlit UI
═════════════════════════════════════════
5 tabs:
  1. 🗺️  Plan a Trip       — Step-by-step guided planner (L2+L3 visible)
  2. 📜 Past Trips         — Browse L3 trip_history
  3. 🧠 Memory Browser     — Raw view of all 3 Postgres tables
  4. 💥 Crash Recovery     — L2 session checkpoint demo
  5. 📊 Preferences        — L3 travel_preferences dashboard
"""

import json
import uuid
import time

import streamlit as st

# ── must happen before any other st calls ────────────────────────────
st.set_page_config(page_title="🌍 Travel Planner — Memory POC", page_icon="🌍", layout="wide")

from db import init_db, execute_query
import memory as mem
from mock_data import MOCK_HOTELS, MOCK_ACTIVITIES, MOCK_FLIGHTS, MOCK_WEATHER, DESTINATION_COUNTRY


# ── Initialise DB ────────────────────────────────────────────────────────────

@st.cache_resource
def _init():
    init_db()

_init()

DESTINATIONS = list(MOCK_HOTELS.keys())

DEPARTURE_CITIES = [
    "Washington, D.C.", "New York", "Chicago", "Los Angeles",
    "San Francisco", "Boston", "London", "Berlin",
]


def _sid():
    """Get or create a session_id for L2 checkpoints."""
    if "session_id" not in st.session_state:
        st.session_state.session_id = f"session-{uuid.uuid4().hex[:8]}"
    return st.session_state.session_id


def _l2_save(step: int, state: dict, node: str):
    """Save L2 checkpoint only if we haven't saved this step in this session yet."""
    key = f"_l2_saved_{_sid()}_{step}"
    if key not in st.session_state:
        mem.save_checkpoint(_sid(), step, state, node)
        st.session_state[key] = True


# ── Cached DB reads (avoids hitting Postgres on every widget interaction) ────

@st.cache_data(ttl=10)
def _cached_prefs():
    return mem.get_all_preferences()

@st.cache_data(ttl=10)
def _cached_trips(query: str):
    return mem.search_trips(query)

@st.cache_data(ttl=10)
def _cached_all_trips():
    return mem.get_all_trips()


# ═══════════════════════════════════════════════════════════════════════════════
#  CSS
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
.tier-badge {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 0.75rem; font-weight: 700; margin-right: 6px;
}
.tier2 { background: #1e3a5f; color: #7ec8e3; }
.tier3 { background: #3a1e5f; color: #c87ee3; }
.card {
    background: #1a1a2e; border-left: 4px solid #00d4aa;
    padding: 14px 18px; margin: 8px 0; border-radius: 6px;
}
.card-mem {
    background: #1a1a2e; border-left: 4px solid #c87ee3;
    padding: 14px 18px; margin: 8px 0; border-radius: 6px;
}
.card-warn {
    background: #2e2a1a; border-left: 4px solid #e3c07e;
    padding: 14px 18px; margin: 8px 0; border-radius: 6px;
}
.card-result {
    background: #1a2e1a; border-left: 4px solid #4ae34a;
    padding: 14px 18px; margin: 8px 0; border-radius: 6px;
}
.pref-bar {
    height: 10px; border-radius: 5px; margin-top: 4px;
}
.step-header {
    font-size: 1.1rem; font-weight: 700; margin: 20px 0 8px 0;
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS — filter mock data using L3 preferences
# ═══════════════════════════════════════════════════════════════════════════════

def _load_prefs_as_dict() -> dict:
    """Load L3 preferences into a simple {key: value} dict."""
    prefs = _cached_prefs()
    return {p["pref_key"]: p["pref_value"] for p in prefs}


def _get_filtered_hotels(destination: str, pref: dict) -> tuple[list, list, str]:
    """
    Return (filtered_hotels, all_hotels, explanation) using L3 prefs.
    Shows the difference memory makes.
    """
    all_hotels = MOCK_HOTELS.get(destination, [])
    if not pref:
        return all_hotels, all_hotels, "No preferences in memory — showing ALL hotels."

    filtered = list(all_hotels)
    reasons = []

    # Filter by accom_style
    style = pref.get("accom_style")
    if style:
        filtered = [h for h in filtered if h["type"] == style]
        reasons.append(f"type=**{style}** (from L3 memory)")

    # Filter by budget
    budget = pref.get("budget_per_night")
    if budget:
        try:
            max_price = float(budget.replace("$", ""))
            filtered = [h for h in filtered if h["price"] <= max_price]
            reasons.append(f"price ≤ **${max_price:.0f}** (from L3 memory)")
        except ValueError:
            pass

    explanation = "Filtered by: " + ", ".join(reasons) if reasons else "No applicable filters."
    return filtered, all_hotels, explanation


def _get_filtered_activities(destination: str, pref: dict) -> tuple[list, list, str]:
    """Return (filtered_activities, all_activities, explanation) using L3 prefs."""
    all_acts = MOCK_ACTIVITIES.get(destination, [])
    if not pref:
        return all_acts, all_acts, "No preferences in memory — showing ALL activities."

    filtered = list(all_acts)
    reasons = []

    # Filter by activity type
    act_pref = pref.get("activity_preference", "")
    if act_pref:
        keywords = [w.strip().lower() for w in act_pref.replace("+", ",").split(",")]
        filtered = [a for a in filtered if a["type"].lower() in keywords]
        reasons.append(f"type in **{act_pref}** (from L3 memory)")

    # Filter by crowd level
    if pref.get("avoid_crowds", "").lower() in ("true", "yes"):
        crowd_ok = ["low", "moderate"]
        filtered = [a for a in filtered if a["crowd_level"] in crowd_ok]
        reasons.append("crowd ≤ **moderate** (avoid_crowds=true from L3 memory)")

    explanation = "Filtered by: " + ", ".join(reasons) if reasons else "No applicable filters."
    return filtered, all_acts, explanation


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — Plan a Trip  (step-by-step guided flow)
# ═══════════════════════════════════════════════════════════════════════════════

def tab_plan_trip():
    st.markdown("### 🗺️ Plan a Trip")
    st.caption(f"Session: `{_sid()}`")

    # ── Initialise planning state ─────────────────────────────────────
    if "plan_step" not in st.session_state:
        st.session_state.plan_step = 0
    if "plan" not in st.session_state:
        st.session_state.plan = {}

    step = st.session_state.plan_step
    plan = st.session_state.plan

    # ── STEP 1: Select departure + destination ────────────────────────
    st.markdown('<p class="step-header">Step 1 — Choose Departure & Destination</p>', unsafe_allow_html=True)

    col_dep, col_dest = st.columns(2)
    with col_dep:
        departure = st.selectbox("✈️ Departing from:", ["-- Select --"] + DEPARTURE_CITIES,
                                 index=0 if "departure" not in plan else DEPARTURE_CITIES.index(plan["departure"]) + 1,
                                 key="departure_select")
    with col_dest:
        dest = st.selectbox("🌍 Going to:", ["-- Select --"] + DESTINATIONS,
                            index=0 if "destination" not in plan else DESTINATIONS.index(plan["destination"]) + 1,
                            key="dest_select")

    if departure == "-- Select --" or dest == "-- Select --":
        st.info("👆 Pick your departure city and destination above to start planning.")
        return

    # If destination changed, reset downstream
    if plan.get("destination") != dest or plan.get("departure") != departure:
        st.session_state.plan = {"destination": dest, "departure": departure}
        st.session_state.plan_step = 1
        # Clear L2 save flags for this session
        for k in list(st.session_state.keys()):
            if k.startswith("_l2_saved_"):
                del st.session_state[k]
        plan = st.session_state.plan
        step = 1

    # ══════════════════════════════════════════════════════════════════
    #  STEP 2: Load L3 memory (THE KEY MOMENT)
    # ══════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown('<p class="step-header">Step 2 — Loading Your Memory (L3)</p>', unsafe_allow_html=True)

    prefs = _load_prefs_as_dict()
    all_prefs = _cached_prefs()
    past_trips = _cached_trips(dest)
    region_trips = _cached_trips(DESTINATION_COUNTRY.get(dest, dest))

    # Show what L3 memory returned
    if all_prefs:
        st.markdown('<div class="card-mem">'
                    '<span class="tier-badge tier3">L3 READ</span>'
                    '<strong>Preferences loaded from Postgres</strong></div>',
                    unsafe_allow_html=True)
        pref_cols = st.columns(min(len(all_prefs), 4))
        for i, p in enumerate(all_prefs[:4]):
            conf = float(p.get("confidence", 0))
            pref_cols[i % 4].metric(p["pref_key"], p["pref_value"], f"{conf:.0%} confidence")
        if len(all_prefs) > 4:
            with st.expander(f"+ {len(all_prefs) - 4} more preferences"):
                for p in all_prefs[4:]:
                    st.markdown(f"• **{p['pref_key']}** = {p['pref_value']} ({float(p.get('confidence',0)):.0%})")
    else:
        st.markdown('<div class="card-warn">'
                    '<span class="tier-badge tier3">L3 READ</span>'
                    '<strong>No preferences found — this is a cold start!</strong>'
                    '<p style="color:#c8a07e;font-size:0.85rem;">Agent has no idea about your taste. '
                    'Results will be generic.</p></div>',
                    unsafe_allow_html=True)

    # Past trips for this destination/region
    combined_trips = list({t["trip_id"]: t for t in past_trips + region_trips}.values())
    if combined_trips:
        st.markdown('<div class="card-mem">'
                    '<span class="tier-badge tier3">L3 READ</span>'
                    f'<strong>Found {len(combined_trips)} past trip(s) in this region</strong></div>',
                    unsafe_allow_html=True)
        for t in combined_trips:
            stars = "⭐" * (t.get("overall_rating") or 0)
            st.markdown(f"&nbsp;&nbsp;• **{t['destination']}** {stars} — "
                        f"✨ {(t.get('highlights') or 'N/A')[:100]}  •  "
                        f"👎 {(t.get('lowlights') or 'N/A')[:100]}")
    else:
        st.caption(f"No past trips to {dest} or {DESTINATION_COUNTRY.get(dest, '?')}.")

    # L2: Save checkpoint (gated — only once per session)
    state_1 = {"departure": departure, "destination": dest,
               "preferences_loaded": bool(all_prefs),
               "past_trips_found": len(combined_trips),
               "step": "memory_loaded"}
    _l2_save(1, state_1, "load_memory")
    st.caption("💾 L2 checkpoint 1 saved → memory loaded")

    # ══════════════════════════════════════════════════════════════════
    #  STEP 3: Hotels  (filtered vs unfiltered comparison)
    # ══════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown('<p class="step-header">Step 3 — Hotel Recommendations</p>', unsafe_allow_html=True)

    filtered_hotels, all_hotels, hotel_explanation = _get_filtered_hotels(dest, prefs)

    # Side-by-side: with memory vs without
    col_with, col_without = st.columns(2)

    with col_with:
        st.markdown(f"##### ✅ WITH Memory ({len(filtered_hotels)} results)")
        st.caption(hotel_explanation)
        if filtered_hotels:
            for h in sorted(filtered_hotels, key=lambda x: x["rating"], reverse=True):
                st.markdown(f"🏨 **{h['name']}** — ${h['price']}/night, ⭐{h['rating']}, "
                            f"{h['neighborhood']} ({h['noise_level']})")
        else:
            st.warning("No hotels match your preferences. Try adjusting in the Preferences tab.")

    with col_without:
        st.markdown(f"##### ❌ WITHOUT Memory ({len(all_hotels)} results)")
        st.caption("No filtering — generic results for everyone.")
        for h in sorted(all_hotels, key=lambda x: x["rating"], reverse=True):
            st.markdown(f"🏨 {h['name']} — ${h['price']}/night, ⭐{h['rating']}, "
                        f"{h['neighborhood']} ({h['type']})")

    # User picks a hotel
    hotel_options = [f"{h['name']} (${h['price']}/night, {h['type']})" for h in filtered_hotels] if filtered_hotels else \
                    [f"{h['name']} (${h['price']}/night, {h['type']})" for h in all_hotels]
    chosen_hotel_str = st.selectbox("Pick a hotel:", ["-- Select --"] + hotel_options, key="hotel_select")

    if chosen_hotel_str == "-- Select --":
        return

    chosen_hotel_name = chosen_hotel_str.split(" ($")[0]
    all_pool = filtered_hotels if filtered_hotels else all_hotels
    chosen_hotel = next((h for h in all_pool if h["name"] == chosen_hotel_name), all_pool[0])
    plan["chosen_hotel"] = chosen_hotel

    # L2: Save checkpoint
    state_2 = {**state_1, "chosen_hotel": chosen_hotel, "step": "hotel_selected"}
    _l2_save(2, state_2, "hotel_selection")
    st.caption("💾 L2 checkpoint 2 saved → hotel selected")

    # ══════════════════════════════════════════════════════════════════
    #  STEP 4: Activities (filtered vs unfiltered comparison)
    # ══════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown('<p class="step-header">Step 4 — Activity Recommendations</p>', unsafe_allow_html=True)

    filtered_acts, all_acts, act_explanation = _get_filtered_activities(dest, prefs)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"##### ✅ WITH Memory ({len(filtered_acts)} results)")
        st.caption(act_explanation)
        for a in filtered_acts:
            st.markdown(f"🎯 **{a['name']}** — {a['type']}, {a['duration']}, "
                        f"${a['price']}, crowd: {a['crowd_level']}")

    with col_b:
        st.markdown(f"##### ❌ WITHOUT Memory ({len(all_acts)} results)")
        st.caption("No filtering — all activities shown.")
        for a in all_acts:
            st.markdown(f"🎯 {a['name']} — {a['type']}, {a['duration']}, "
                        f"${a['price']}, crowd: {a['crowd_level']}")

    # User picks activities
    act_names = [a["name"] for a in (filtered_acts if filtered_acts else all_acts)]
    chosen_acts = st.multiselect("Pick your activities:", act_names, default=act_names[:3], key="act_select")

    if not chosen_acts:
        return

    plan["chosen_activities"] = chosen_acts

    # L2: Save checkpoint
    state_3 = {**state_2, "chosen_activities": chosen_acts, "step": "activities_selected"}
    _l2_save(3, state_3, "activity_selection")
    st.caption("💾 L2 checkpoint 3 saved → activities selected")

    # ══════════════════════════════════════════════════════════════════
    #  STEP 5: Weather + Flight info
    # ══════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown('<p class="step-header">Step 5 — Weather & Flight</p>', unsafe_allow_html=True)

    fl = MOCK_FLIGHTS.get(dest, {})
    we = MOCK_WEATHER.get(dest, {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🛫 From", departure)
    c2.metric("✈️ Flight", f"${fl.get('price', '?')}", fl.get("airline", ""))
    c3.metric("⏱️ Duration", fl.get("duration", "?"))
    c4.metric("🌤️ October Weather", we.get("Oct", "?"))

    # ══════════════════════════════════════════════════════════════════
    #  STEP 6: Final itinerary summary
    # ══════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown('<p class="step-header">Step 6 — Your Trip Summary</p>', unsafe_allow_html=True)

    st.markdown(f"""
    <div class="card-result">
        <strong>🌍 {dest} Trip Plan</strong><br><br>
        🛫 <strong>Departure:</strong> {departure}<br>
        🏨 <strong>Hotel:</strong> {chosen_hotel['name']} — ${chosen_hotel['price']}/night ({chosen_hotel['type']}, {chosen_hotel['neighborhood']})<br>
        🎯 <strong>Activities:</strong> {', '.join(chosen_acts)}<br>
        ✈️ <strong>Flight:</strong> {fl.get('airline','')} — ${fl.get('price','?')} ({fl.get('duration','?')})<br>
        🌤️ <strong>Weather:</strong> {we.get('Oct', '?')}<br>
        💰 <strong>Est. daily budget:</strong> ${chosen_hotel['price'] + 50}/day (hotel + activities)
    </div>
    """, unsafe_allow_html=True)

    # L2: Save checkpoint
    state_4 = {**state_3, "flight": fl, "weather": we.get("Oct", ""), "step": "summary"}
    _l2_save(4, state_4, "trip_summary")
    st.caption("💾 L2 checkpoint 4 saved → full itinerary")

    # ══════════════════════════════════════════════════════════════════
    #  STEP 7: Rate the trip → SAVE to L3 (the learning moment!)
    # ══════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown('<p class="step-header">Step 7 — Rate & Save to Memory (L3 WRITE)</p>', unsafe_allow_html=True)
    st.caption("This is where the agent LEARNS. Your rating and feedback get saved to Postgres. "
               "Next time you plan a trip, the agent will read this and make better recommendations.")

    with st.form("rate_trip"):
        rating = st.slider("Overall rating", 1, 5, 4)
        hotel_rating = st.slider("Hotel rating", 1, 5, 4)
        highlights = st.text_area("What did you love?", placeholder="e.g. The food tour was incredible!")
        lowlights = st.text_area("What would you skip?", placeholder="e.g. Too crowded at the main square")
        travel_style = st.selectbox("Travel style", ["solo", "couple", "family", "friends"])

        submitted = st.form_submit_button("💾 Save Trip to Long-term Memory", type="primary")

    if submitted:
        # L3 WRITE: Save trip
        trip_id = mem.save_trip(
            destination=dest,
            country=DESTINATION_COUNTRY.get(dest, ""),
            budget_actual=float(chosen_hotel["price"]) + 50,
            travel_style=travel_style,
            accommodation=chosen_hotel["name"],
            accom_type=chosen_hotel["type"],
            accom_rating=hotel_rating,
            activities=chosen_acts,
            highlights=highlights,
            lowlights=lowlights,
            overall_rating=rating,
            trip_summary=f"{dest} trip from {departure}: {chosen_hotel['name']}, activities: {', '.join(chosen_acts[:3])}",
        )

        st.markdown(f'<div class="card-mem"><span class="tier-badge tier3">L3 WRITE</span>'
                    f'<strong>Trip saved to Postgres!</strong> (id={trip_id})</div>',
                    unsafe_allow_html=True)

        # L3 WRITE: Infer preferences from this trip
        new_prefs = []

        mem.save_preference("accom_style", chosen_hotel["type"], 0.80,
                            f"Chose {chosen_hotel['type']} in {dest} (rated {hotel_rating}/5)")
        new_prefs.append(f"accom_style = {chosen_hotel['type']}")

        mem.save_preference("budget_per_night", str(chosen_hotel["price"]), 0.70,
                            f"Booked at ${chosen_hotel['price']}/night in {dest}")
        new_prefs.append(f"budget_per_night = ${chosen_hotel['price']}")

        act_types = set()
        for act_name in chosen_acts:
            for a in MOCK_ACTIVITIES.get(dest, []):
                if a["name"] == act_name:
                    act_types.add(a["type"])
        if act_types:
            act_pref_str = " + ".join(sorted(act_types))
            mem.save_preference("activity_preference", act_pref_str, 0.75,
                                f"Chose {act_pref_str} activities in {dest}")
            new_prefs.append(f"activity_preference = {act_pref_str}")

        if lowlights and any(w in lowlights.lower() for w in ["crowd", "busy", "packed", "touristy"]):
            mem.save_preference("avoid_crowds", "true", 0.70,
                                f"Mentioned crowding in {dest} lowlights")
            new_prefs.append("avoid_crowds = true")

        st.markdown(f'<div class="card-mem"><span class="tier-badge tier3">L3 WRITE</span>'
                    f'<strong>Preferences updated:</strong> {", ".join(new_prefs)}</div>',
                    unsafe_allow_html=True)

        st.success("✅ Memory updated! Next time you plan a trip, the agent will use this data "
                   "to give you better, personalised recommendations.")
        st.info("💡 **Try it now:** Go back to Step 1 and pick a different city — "
                "you'll see the recommendations change based on what you just saved!")

        # L2: Final checkpoint
        state_5 = {**state_4, "rating": rating, "highlights": highlights,
                   "lowlights": lowlights, "step": "rated_and_saved"}
        mem.save_checkpoint(_sid(), 5, state_5, "trip_saved_to_memory")

        # Clear caches so next planning reads fresh data
        _cached_prefs.clear()
        _cached_trips.clear()
        _cached_all_trips.clear()

    # ── Reset button ──────────────────────────────────────────────────
    st.markdown("---")
    if st.button("🔄 Start a New Trip"):
        st.session_state.plan = {}
        st.session_state.plan_step = 0
        st.session_state.session_id = f"session-{uuid.uuid4().hex[:8]}"
        for k in list(st.session_state.keys()):
            if k.startswith("_l2_saved_"):
                del st.session_state[k]
        _cached_prefs.clear()
        _cached_trips.clear()
        _cached_all_trips.clear()
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — Past Trips
# ═══════════════════════════════════════════════════════════════════════════════

def tab_past_trips():
    st.markdown("### 📜 Past Trips (L3 — trip_history)")
    trips = _cached_all_trips()

    if not trips:
        st.info("No trips in long-term memory yet. Plan a trip in Tab 1 or run `python seed_data.py`.")
        return

    st.metric("Total trips stored", len(trips))

    for t in trips:
        rating_stars = "⭐" * (t.get("overall_rating") or 0)
        with st.expander(f"🌍 {t['destination']} ({t.get('country','')}) — {rating_stars}", expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**Dates:** {t.get('start_date', '?')} → {t.get('end_date', '?')}")
            c2.markdown(f"**Style:** {t.get('travel_style', '?')}")
            c3.markdown(f"**Budget:** ${t.get('budget_actual', '?')}")

            st.markdown(f"**🏨 Hotel:** {t.get('accommodation', '?')} ({t.get('accom_type', '?')}, "
                        f"{'⭐' * (t.get('accom_rating') or 0)})")
            st.markdown(f"**✨ Highlights:** {t.get('highlights', '—')}")
            st.markdown(f"**👎 Lowlights:** {t.get('lowlights', '—')}")
            acts = t.get("activities")
            if acts:
                if isinstance(acts, str):
                    acts = json.loads(acts)
                st.markdown(f"**🎯 Activities:** {', '.join(acts)}")
            if t.get("trip_summary"):
                st.markdown(f"**📝 Summary:** {t['trip_summary']}")


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — Memory Browser (raw tables)
# ═══════════════════════════════════════════════════════════════════════════════

def tab_memory_browser():
    st.markdown("### 🧠 Memory Browser — Raw Postgres Tables")

    st.markdown('<span class="tier-badge tier3">L3</span> **trip_history**', unsafe_allow_html=True)
    trips = _cached_all_trips()
    if trips:
        # Convert activities JSONB to string for Arrow compatibility
        display_trips = []
        for t in trips:
            row = dict(t)
            if isinstance(row.get("activities"), (list, dict)):
                row["activities"] = json.dumps(row["activities"])
            display_trips.append(row)
        st.dataframe(display_trips, width="stretch")
    else:
        st.caption("Empty")

    st.markdown("---")
    st.markdown('<span class="tier-badge tier3">L3</span> **travel_preferences**', unsafe_allow_html=True)
    prefs = _cached_prefs()
    if prefs:
        st.dataframe(prefs, width="stretch")
    else:
        st.caption("Empty")

    st.markdown("---")
    st.markdown('<span class="tier-badge tier2">L2</span> **session_checkpoints**', unsafe_allow_html=True)
    cps = execute_query("SELECT session_id, step_number, node_name, agent_state, created_at "
                        "FROM session_checkpoints ORDER BY created_at DESC LIMIT 50")
    if cps:
        # Convert agent_state JSONB dict to string for Arrow compatibility
        display_cps = []
        for c in cps:
            row = dict(c)
            if isinstance(row.get("agent_state"), dict):
                row["agent_state"] = json.dumps(row["agent_state"], default=str)
            display_cps.append(row)
        st.dataframe(display_cps, width="stretch")
    else:
        st.caption("Empty")

    st.markdown("---")
    col_seed, col_reset = st.columns(2)
    with col_seed:
        if st.button("🌱 Seed Demo Data (3 trips + 7 prefs)", type="primary"):
            from db import seed_demo_data
            seed_demo_data()
            _cached_prefs.clear()
            _cached_trips.clear()
            _cached_all_trips.clear()
            st.success("Seeded 3 trips + 7 preferences!")
            st.rerun()
    with col_reset:
        if st.button("🗑️ Reset ALL Memory", type="secondary"):
            mem.reset_all_memory()
            _cached_prefs.clear()
            _cached_trips.clear()
            _cached_all_trips.clear()
            st.success("All memory wiped!")
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — Crash Recovery Demo
# ═══════════════════════════════════════════════════════════════════════════════

def tab_crash_recovery():
    st.markdown("### 💥 Crash Recovery Demo (L2 Session Memory)")
    st.caption("Demonstrates how session checkpoints let you resume planning after a crash.")

    demo_sid = f"crash-demo-{uuid.uuid4().hex[:4]}"

    if st.button("▶️  Start planning simulation (3 steps then crash)", type="primary"):
        st.markdown(f"**Session ID:** `{demo_sid}`")

        # Step 1
        st.markdown('<div class="card"><span class="tier-badge tier2">STEP 1</span>'
                    '<strong>Gather requirements</strong>'
                    '<p style="color:#aaa;font-size:0.85rem;">Departure: Washington D.C., Destination: Barcelona, Dates: Oct 15-22, Style: couple</p></div>',
                    unsafe_allow_html=True)
        state1 = {"departure": "Washington, D.C.", "destination": "Barcelona",
                  "dates": "Oct 15-22", "style": "couple", "step": "requirements"}
        mem.save_checkpoint(demo_sid, 1, state1, "gather_requirements")
        time.sleep(0.5)

        # Step 2
        st.markdown('<div class="card"><span class="tier-badge tier2">STEP 2</span>'
                    '<strong>Hotel selection</strong>'
                    '<p style="color:#aaa;font-size:0.85rem;">Shortlisted: Hotel Neri ($145), Casa Bonay ($135)</p></div>',
                    unsafe_allow_html=True)
        state2 = {**state1, "step": "hotel_selection",
                  "shortlisted_hotels": ["Hotel Neri ($145)", "Casa Bonay ($135)"]}
        mem.save_checkpoint(demo_sid, 2, state2, "hotel_selection")
        time.sleep(0.5)

        # Step 3
        st.markdown('<div class="card"><span class="tier-badge tier2">STEP 3</span>'
                    '<strong>Activity planning</strong>'
                    '<p style="color:#aaa;font-size:0.85rem;">Picked: Gothic Quarter walk, La Boqueria food tour</p></div>',
                    unsafe_allow_html=True)
        state3 = {**state2, "step": "activity_planning",
                  "chosen_hotel": "Hotel Neri",
                  "activities": ["Gothic Quarter walk", "La Boqueria food tour"]}
        mem.save_checkpoint(demo_sid, 3, state3, "activity_planning")
        time.sleep(0.5)

        # CRASH!
        st.markdown('<div class="card-warn">💥 <strong>CRASH!</strong> — Browser closed / pod restarted / network failure.'
                    '<p style="color:#c8a07e;font-size:0.85rem;">3 checkpoints safely stored in Postgres.</p></div>',
                    unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### 🔄 Recovering from crash…")
        time.sleep(1)

        # Recovery
        cp = mem.load_latest_checkpoint(demo_sid)
        if cp:
            st.success(f"✅ **State recovered!** Loaded step {cp['step_number']} ({cp['state'].get('step', '?')})")
            st.markdown(f"**Departure:** {cp['state'].get('departure')}")
            st.markdown(f"**Destination:** {cp['state'].get('destination')}")
            st.markdown(f"**Dates:** {cp['state'].get('dates')}")
            st.markdown(f"**Chosen hotel:** {cp['state'].get('chosen_hotel', 'not yet chosen')}")
            st.markdown(f"**Activities planned:** {cp['state'].get('activities', [])}")
            st.markdown(f"**Saved at:** {cp['saved_at']}")
            st.info("🔄 The agent would now resume from **step 4** (Day 2 planning) — "
                    "no need to redo requirements, hotel selection, or activity shortlisting!")

            with st.expander("📋 Full checkpoint JSON"):
                st.json(cp["state"])

            all_cps = mem.list_checkpoints(demo_sid)
            st.markdown("#### All checkpoints for this session:")
            for c in all_cps:
                st.markdown(f'<div class="card"><span class="tier-badge tier2">STEP {c["step_number"]}</span>'
                            f'<strong>{c["node_name"]}</strong>'
                            f'<span style="float:right;font-size:0.75rem;color:#888;">{c["created_at"]}</span></div>',
                            unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — Preferences Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

def tab_preferences():
    st.markdown("### 📊 Traveler Preferences (L3)")
    st.caption("Learned from past trips and conversations. Confidence grows as more data confirms each preference.")

    prefs = _cached_prefs()
    if not prefs:
        st.info("No preferences stored yet. Plan a trip in Tab 1 or run `python seed_data.py`.")
        return

    for p in prefs:
        conf = float(p.get("confidence", 0))
        color = "#00d4aa" if conf >= 0.7 else "#e3c07e" if conf >= 0.4 else "#e37e7e"

        st.markdown(f"""
        <div class="card">
            <span class="tier-badge tier3">L3</span>
            <strong>{p['pref_key']}</strong> = <code>{p['pref_value']}</code>
            <span style="float:right; color:{color}; font-weight:700;">{conf:.0%}</span>
            <div class="pref-bar" style="background:#333; width:100%;">
                <div style="width:{conf*100:.0f}%; background:{color}; height:10px; border-radius:5px;"></div>
            </div>
            <p style="font-size:0.8rem; color:#888; margin:4px 0 0 0;">
                Source: {p.get('source', '—')}  •  Updated: {str(p.get('updated_at', ''))[:19]}
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### ➕ Add / Update Preference")
    with st.form("add_pref"):
        c1, c2 = st.columns(2)
        key = c1.text_input("Key", placeholder="e.g. dietary")
        val = c2.text_input("Value", placeholder="e.g. vegetarian")
        c3, c4 = st.columns(2)
        conf = c3.slider("Confidence", 0.0, 1.0, 0.5, 0.05)
        src = c4.text_input("Source", placeholder="e.g. user stated")
        if st.form_submit_button("Save Preference"):
            if key and val:
                mem.save_preference(key, val, conf, src)
                _cached_prefs.clear()
                st.success(f"Saved: {key} = {val}")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — Strands Agent Chat (LLM + memory tools)
# ═══════════════════════════════════════════════════════════════════════════════

def tab_agent_chat():
    st.markdown("### 🤖 Strands Agent — Chat with LLM")
    st.caption("The Strands agent uses Bedrock Nova + 7 tools. It reads L3 memory, reasons, "
               "and makes personalised recommendations. Requires valid AWS credentials.")

    # Build agent once per session
    if "strands_agent" not in st.session_state:
        try:
            from agent import build_agent
            st.session_state.strands_agent = build_agent()
            st.session_state.agent_error = None
        except Exception as e:
            st.session_state.strands_agent = None
            st.session_state.agent_error = str(e)

    if st.session_state.agent_error:
        st.error(f"⚠️ Agent init failed: {st.session_state.agent_error}")
        st.info("Make sure your AWS credentials are valid (`aws sso login`).")
        if st.button("🔄 Retry"):
            del st.session_state["strands_agent"]
            del st.session_state["agent_error"]
            st.rerun()
        return

    agent = st.session_state.strands_agent

    # Chat history
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []

    for m in st.session_state.agent_messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if prompt := st.chat_input("Ask the agent (e.g. 'Plan a trip to Barcelona')"):
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("🤖 Agent thinking + calling tools…"):
                try:
                    import re
                    result = agent(prompt)
                    raw = str(result)
                    # Strip <thinking> blocks
                    clean = re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL).strip()
                    response = clean or raw
                except Exception as e:
                    response = f"❌ Agent error: {e}"
            st.markdown(response)

        st.session_state.agent_messages.append({"role": "assistant", "content": response})

    # Quick prompts
    st.markdown("---")
    st.markdown("**Quick prompts:**")
    cols = st.columns(3)
    prompts = [
        "Plan a trip to Barcelona for a couple",
        "What do you know about my travel preferences?",
        "I just visited Osaka, loved the street food, hotel was noisy. Rate 4/5.",
    ]
    for col, qp in zip(cols, prompts):
        if col.button(qp[:40] + "…", key=f"qp_{qp[:10]}"):
            st.session_state.agent_messages.append({"role": "user", "content": qp})
            try:
                import re
                result = agent(qp)
                raw = str(result)
                clean = re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL).strip()
                response = clean or raw
            except Exception as e:
                response = f"❌ Agent error: {e}"
            st.session_state.agent_messages.append({"role": "assistant", "content": response})
            st.rerun()

    if st.button("🗑️ Clear Chat"):
        st.session_state.agent_messages = []
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

st.title("🌍 AI Travel Planner — Memory POC")
st.markdown("**Strands Agent + Postgres** — L2 Session Memory + L3 Long-term Memory")
st.markdown("---")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🗺️ Plan a Trip",
    "🤖 Agent Chat",
    "📜 Past Trips",
    "🧠 Memory Browser",
    "💥 Crash Recovery",
    "📊 Preferences",
])

with tab1:
    tab_plan_trip()
with tab2:
    tab_agent_chat()
with tab3:
    tab_past_trips()
with tab4:
    tab_memory_browser()
with tab5:
    tab_crash_recovery()
with tab6:
    tab_preferences()



