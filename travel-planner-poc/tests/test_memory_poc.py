"""
Lightweight tests for Travel Planner Memory POC.
No real DB needed — patches db.execute_query / db.execute_insert with in-memory stores.
Run:  pytest tests/test_memory_poc.py -v
"""

import json
import pytest
from unittest.mock import patch
from datetime import datetime
from decimal import Decimal

from mock_data import MOCK_HOTELS, MOCK_ACTIVITIES, MOCK_WEATHER


# ── In-memory fake DB ────────────────────────────────────────────────────────

_tables: dict[str, list[dict]] = {}


def _reset_tables():
    _tables.clear()
    _tables["session_checkpoints"] = []
    _tables["trip_history"] = []
    _tables["travel_preferences"] = []


def _fake_insert(sql: str, params: tuple = ()):
    sql_lower = sql.strip().lower()

    if "delete from session_checkpoints" in sql_lower and "where" not in sql_lower:
        _tables["session_checkpoints"].clear()
    elif "delete from trip_history" in sql_lower and "where" not in sql_lower:
        _tables["trip_history"].clear()
    elif "delete from travel_preferences" in sql_lower and "where" not in sql_lower:
        _tables["travel_preferences"].clear()
    elif "delete from session_checkpoints" in sql_lower:
        sid = params[0]
        _tables["session_checkpoints"] = [r for r in _tables["session_checkpoints"] if r["session_id"] != sid]
    elif "delete from travel_preferences" in sql_lower:
        _tables["travel_preferences"] = [r for r in _tables["travel_preferences"] if r["pref_key"] != params[0]]
    elif "insert into session_checkpoints" in sql_lower:
        sid, step, state_json, node = params
        state = json.loads(state_json) if isinstance(state_json, str) else state_json
        existing = [r for r in _tables["session_checkpoints"] if r["session_id"] == sid and r["step_number"] == step]
        if existing:
            existing[0].update(agent_state=state, node_name=node, created_at=datetime.now())
        else:
            _tables["session_checkpoints"].append(
                {"session_id": sid, "step_number": step, "agent_state": state,
                 "node_name": node, "created_at": datetime.now()})
    elif "insert into trip_history" in sql_lower:
        row = dict(
            trip_id=params[0], destination=params[1], country=params[2],
            start_date=params[3], end_date=params[4],
            budget_planned=params[5], budget_actual=params[6],
            travel_style=params[7], accommodation=params[8],
            accom_type=params[9], accom_rating=params[10],
            activities=json.loads(params[11]) if isinstance(params[11], str) else params[11],
            highlights=params[12], lowlights=params[13],
            overall_rating=params[14], trip_summary=params[15],
            created_at=datetime.now(),
        )
        _tables["trip_history"].append(row)
    elif "insert into travel_preferences" in sql_lower:
        key, val, conf, src = params
        existing = [r for r in _tables["travel_preferences"] if r["pref_key"] == key]
        if existing:
            existing[0]["pref_value"] = val
            existing[0]["confidence"] = max(float(existing[0]["confidence"]), float(conf))
            existing[0]["source"] = src
            existing[0]["updated_at"] = datetime.now()
        else:
            _tables["travel_preferences"].append(
                {"pref_key": key, "pref_value": val, "confidence": Decimal(str(conf)),
                 "source": src, "updated_at": datetime.now()})


def _fake_query(sql: str, params: tuple = ()):
    sql_lower = sql.strip().lower()

    if "from session_checkpoints" in sql_lower:
        sid = params[0]
        rows = [r for r in _tables["session_checkpoints"] if r["session_id"] == sid]
        if "order by step_number desc" in sql_lower:
            rows = sorted(rows, key=lambda r: r["step_number"], reverse=True)
            return rows[:1] if "limit 1" in sql_lower else rows
        return sorted(rows, key=lambda r: r["step_number"])

    if "from trip_history" in sql_lower:
        if "ilike" in sql_lower:
            q = params[0].strip("%").lower()
            limit = params[-1]
            rows = [r for r in _tables["trip_history"]
                    if q in (r.get("destination") or "").lower()
                    or q in (r.get("country") or "").lower()
                    or q in (r.get("highlights") or "").lower()]
            return sorted(rows, key=lambda r: r["created_at"], reverse=True)[:limit]
        return sorted(_tables["trip_history"], key=lambda r: r["created_at"], reverse=True)

    if "from travel_preferences" in sql_lower:
        if "where pref_key" in sql_lower:
            rows = [r for r in _tables["travel_preferences"] if r["pref_key"] == params[0]]
            return rows[:1] if rows else []
        return sorted(_tables["travel_preferences"], key=lambda r: float(r["confidence"]), reverse=True)

    return []


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_db():
    _reset_tables()
    with patch("memory.execute_insert", side_effect=_fake_insert), \
         patch("memory.execute_query", side_effect=_fake_query):
        import memory as mem
        yield mem


# ── L3: Trip History ──────────────────────────────────────────────────────────

class TestTripHistory:
    def test_save_and_get(self, mock_db):
        tid = mock_db.save_trip(destination="Tokyo", country="Japan", overall_rating=4, highlights="Tsukiji")
        assert tid.startswith("trip-")
        trips = mock_db.get_all_trips()
        assert len(trips) == 1 and trips[0]["destination"] == "Tokyo"

    def test_search_by_destination(self, mock_db):
        mock_db.save_trip(destination="Tokyo", country="Japan")
        mock_db.save_trip(destination="Paris", country="France")
        assert len(mock_db.search_trips("Tokyo")) == 1

    def test_search_no_match(self, mock_db):
        mock_db.save_trip(destination="Tokyo")
        assert mock_db.search_trips("Antarctica") == []


# ── L3: Preferences ──────────────────────────────────────────────────────────

class TestPreferences:
    def test_save_and_get(self, mock_db):
        mock_db.save_preference("accom_style", "boutique", 0.85)
        p = mock_db.get_preference("accom_style")
        assert p["pref_value"] == "boutique"
        assert float(p["confidence"]) == 0.85

    def test_confidence_only_goes_up(self, mock_db):
        mock_db.save_preference("style", "boutique", 0.85)
        mock_db.save_preference("style", "boutique", 0.50)
        assert float(mock_db.get_preference("style")["confidence"]) == 0.85

    def test_confidence_increases(self, mock_db):
        mock_db.save_preference("style", "boutique", 0.60)
        mock_db.save_preference("style", "boutique", 0.90)
        assert float(mock_db.get_preference("style")["confidence"]) == 0.90

    def test_get_missing_returns_none(self, mock_db):
        assert mock_db.get_preference("nope") is None

    def test_delete(self, mock_db):
        mock_db.save_preference("diet", "veg", 0.5)
        mock_db.delete_preference("diet")
        assert mock_db.get_preference("diet") is None


# ── L2: Session Checkpoints ──────────────────────────────────────────────────

class TestCheckpoints:
    def test_save_and_load(self, mock_db):
        mock_db.save_checkpoint("s1", 1, {"dest": "Barcelona"}, "step_1")
        cp = mock_db.load_latest_checkpoint("s1")
        assert cp["step_number"] == 1 and cp["state"]["dest"] == "Barcelona"

    def test_load_returns_latest(self, mock_db):
        mock_db.save_checkpoint("s1", 1, {"s": "a"}, "n1")
        mock_db.save_checkpoint("s1", 2, {"s": "b"}, "n2")
        assert mock_db.load_latest_checkpoint("s1")["step_number"] == 2

    def test_crash_recovery(self, mock_db):
        state = {"dest": "Barcelona", "hotel": {"name": "Neri"}, "acts": ["walk", "food"]}
        mock_db.save_checkpoint("s1", 3, state, "act_select")
        recovered = mock_db.load_latest_checkpoint("s1")
        assert recovered["state"]["hotel"]["name"] == "Neri"
        assert len(recovered["state"]["acts"]) == 2

    def test_nonexistent_session(self, mock_db):
        assert mock_db.load_latest_checkpoint("nope") is None

    def test_delete_session(self, mock_db):
        mock_db.save_checkpoint("s1", 1, {}, "n")
        mock_db.delete_session("s1")
        assert mock_db.load_latest_checkpoint("s1") is None

    def test_sessions_isolated(self, mock_db):
        mock_db.save_checkpoint("a", 1, {"d": "Tokyo"}, "n")
        mock_db.save_checkpoint("b", 1, {"d": "Paris"}, "n")
        assert mock_db.load_latest_checkpoint("a")["state"]["d"] == "Tokyo"
        assert mock_db.load_latest_checkpoint("b")["state"]["d"] == "Paris"


# ── Mock Data Sanity ──────────────────────────────────────────────────────────

class TestMockData:
    def test_hotel_filter_by_type(self):
        boutique = [h for h in MOCK_HOTELS["Tokyo"] if h["type"] == "boutique"]
        assert 0 < len(boutique) < len(MOCK_HOTELS["Tokyo"])

    def test_activity_filter_by_type(self):
        food = [a for a in MOCK_ACTIVITIES["Tokyo"] if a["type"] == "food"]
        assert 0 < len(food) < len(MOCK_ACTIVITIES["Tokyo"])

    def test_all_destinations_have_data(self):
        for dest in MOCK_HOTELS:
            assert dest in MOCK_ACTIVITIES
            assert dest in MOCK_WEATHER


# ── Reset ─────────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_everything(self, mock_db):
        mock_db.save_trip(destination="Tokyo", overall_rating=4)
        mock_db.save_preference("style", "boutique", 0.8)
        mock_db.save_checkpoint("s1", 1, {}, "n")
        mock_db.reset_all_memory()
        assert mock_db.get_all_trips() == []
        assert mock_db.get_all_preferences() == []
        assert mock_db.load_latest_checkpoint("s1") is None

