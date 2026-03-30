"""
Strands @tool functions — memory + planning tools.
───────────────────────────────────────────────────
Memory tools (Postgres):
  get_preferences        — L3 READ: load traveler profile
  search_past_trips      — L3 READ: find similar past trips
  save_trip_to_memory    — L3 WRITE: store completed trip
  save_user_preference   — L3 WRITE: update preference

Planning tools (mock data):
  search_hotels          — find hotels by destination/type/budget
  search_activities      — find activities by destination/type/crowd
  get_weather            — get weather for destination + month
"""

import json
from strands import tool
import memory as mem
from mock_data import (
    MOCK_HOTELS, MOCK_ACTIVITIES, MOCK_WEATHER, DESTINATION_COUNTRY,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  L3 READ
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def get_preferences() -> str:
    """Load ALL known traveler preferences from long-term memory.
    Returns JSON array of {pref_key, pref_value, confidence, source}.
    ALWAYS call this FIRST before planning any trip so you can personalise."""
    prefs = mem.get_all_preferences()
    if not prefs:
        return json.dumps({"message": "No preferences yet — new traveler."})
    return mem.to_json(prefs)


@tool
def search_past_trips(query: str, limit: int = 5) -> str:
    """Search past trips by destination, country, or keyword.
    Call this to find relevant travel history BEFORE making recommendations.
    Args:
        query: search text — e.g. 'Japan', 'beach', 'food tour'
        limit: max results (default 5)"""
    trips = mem.search_trips(query, limit=limit)
    if not trips:
        return json.dumps({"message": f"No past trips matching '{query}'."})
    return mem.to_json(trips)


# ═══════════════════════════════════════════════════════════════════════════════
#  L3 WRITE
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def save_trip_to_memory(
    destination: str,
    overall_rating: int,
    highlights: str = "",
    lowlights: str = "",
    accommodation: str = "",
    accom_type: str = "",
    accom_rating: int = 0,
    budget_actual: float = 0.0,
    travel_style: str = "",
    activities: str = "",
    trip_summary: str = "",
) -> str:
    """Save a completed trip to long-term memory for future learning.
    Call this AFTER a trip is finalised and the user gives feedback.
    Args:
        destination:    city name
        overall_rating: 1-5 stars
        highlights:     what the user loved
        lowlights:      what the user disliked
        accommodation:  hotel name
        accom_type:     boutique / chain / hostel / luxury
        accom_rating:   1-5 for the hotel
        budget_actual:  per-day spend
        travel_style:   solo / couple / family / friends
        activities:     comma-separated list
        trip_summary:   short summary"""
    country = DESTINATION_COUNTRY.get(destination, "")
    act_list = [a.strip() for a in activities.split(",") if a.strip()] if activities else []
    trip_id = mem.save_trip(
        destination=destination, country=country,
        budget_actual=budget_actual, travel_style=travel_style,
        accommodation=accommodation, accom_type=accom_type,
        accom_rating=accom_rating or None, activities=act_list,
        highlights=highlights, lowlights=lowlights,
        overall_rating=overall_rating, trip_summary=trip_summary,
    )
    return f"✅ Trip to {destination} saved (id={trip_id}, rating={overall_rating}/5)"


@tool
def save_user_preference(pref_key: str, pref_value: str,
                         confidence: float = 0.5, source: str = "") -> str:
    """Save or update a traveler preference in long-term memory.
    Call whenever you learn something new about the traveler.
    Args:
        pref_key:   e.g. 'accom_style', 'dietary', 'budget_per_night'
        pref_value: e.g. 'boutique', 'vegetarian', '150'
        confidence: 0.0–1.0
        source:     why we know this"""
    mem.save_preference(pref_key, pref_value, confidence, source)
    return f"✅ Preference: {pref_key} = {pref_value} ({confidence:.0%})"


# ═══════════════════════════════════════════════════════════════════════════════
#  PLANNING TOOLS (mock data)
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def search_hotels(destination: str, max_price: float = 9999.0,
                  hotel_type: str = "any") -> str:
    """Search for hotels at a destination.
    Args:
        destination: city name
        max_price:   max nightly rate USD (default: no limit)
        hotel_type:  'boutique', 'chain', 'hostel', 'luxury', or 'any'"""
    hotels = MOCK_HOTELS.get(destination, [])
    if not hotels:
        return json.dumps({"error": f"No data for '{destination}'. Available: {', '.join(MOCK_HOTELS)}"})
    if hotel_type != "any":
        hotels = [h for h in hotels if h["type"] == hotel_type]
    hotels = [h for h in hotels if h["price"] <= max_price]
    hotels.sort(key=lambda h: h["rating"], reverse=True)
    return json.dumps(hotels)


@tool
def search_activities(destination: str, activity_type: str = "any",
                      max_crowd: str = "any") -> str:
    """Search for activities at a destination.
    Args:
        destination:   city name
        activity_type: 'food', 'cultural', 'adventure', 'relaxation', 'sightseeing', or 'any'
        max_crowd:     'low', 'moderate', 'high', 'very_high', or 'any'"""
    from mock_data import MOCK_ACTIVITIES
    acts = MOCK_ACTIVITIES.get(destination, [])
    if not acts:
        return json.dumps({"error": f"No data for '{destination}'."})
    if activity_type != "any":
        acts = [a for a in acts if a["type"] == activity_type]
    crowd_order = ["low", "moderate", "high", "very_high"]
    if max_crowd != "any" and max_crowd in crowd_order:
        max_idx = crowd_order.index(max_crowd)
        acts = [a for a in acts if crowd_order.index(a["crowd_level"]) <= max_idx]
    return json.dumps(acts)


@tool
def get_weather(destination: str, month: str) -> str:
    """Get weather for a destination in a specific month.
    Args:
        destination: city name
        month: 3-letter month — Jan, Feb, … Dec"""
    weather = MOCK_WEATHER.get(destination, {})
    if not weather:
        return json.dumps({"error": f"No weather data for '{destination}'."})
    desc = weather.get(month[:3].capitalize(), "No data.")
    return json.dumps({"destination": destination, "month": month, "weather": desc})


# ── All tools list ───────────────────────────────────────────────────────────

ALL_TOOLS = [
    get_preferences, search_past_trips,
    save_trip_to_memory, save_user_preference,
    search_hotels, search_activities, get_weather,
]

