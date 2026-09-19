"""rasi_hora_table and current_hora, against the real Swiss Ephemeris backend.

Reference values for hora scores are not asserted: the nature / friendship /
gochara tables are provisional. TODO: verify against a printed panchangam.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from panchangam.hora import engine

from panchangam.server import (
    RequestError,
    _BEST_HORAS_TOOL,
    _RASI_HORA_TABLE_TOOL,
    _handle_best_horas,
    _handle_current_hora,
    _handle_rasi_hora_table,
    load_provider,
)

MYT = timezone(timedelta(hours=8))
THURSDAY = {"rasi": 2, "date": "2026-09-24"}


def test_table_has_24_horas_and_thursday_hora_1_is_jupiter():
    out = _handle_rasi_hora_table(load_provider(), THURSDAY)
    rows = out["horas"]
    assert [r["hora"] for r in rows] == list(range(1, 25))
    assert rows[0]["lord"] == "Jupiter"
    assert rows[1]["lord"] == "Mars"
    assert set(rows[0]) == {"hora", "lord", "score", "start", "end"}
    assert all(0 <= r["score"] <= 100 for r in rows)
    assert rows[0]["end"] == rows[1]["start"]
    assert "PROVISIONAL" in out["caveat"]


def test_table_breakdown_adds_the_three_parts():
    out = _handle_rasi_hora_table(load_provider(), {**THURSDAY, "score_breakdown": True})
    assert {"nature", "friendship", "gochara"} <= set(out["horas"][0])


@pytest.mark.parametrize("rasi", [0, 13, "2", True, None])
def test_bad_rasi_is_a_request_error(rasi):
    with pytest.raises(RequestError, match="rasi"):
        _handle_rasi_hora_table(load_provider(), {**THURSDAY, "rasi": rasi})


def test_current_hora_matches_the_table_row_containing_now():
    provider = load_provider()
    now = datetime(2026, 9, 24, 10, 30, tzinfo=MYT)
    cur = _handle_current_hora(provider, {"rasi": 2}, now=now)
    row = _handle_rasi_hora_table(provider, THURSDAY)["horas"][cur["hora"] - 1]
    assert row["start"] <= "10:30" < row["end"]
    assert (cur["lord"], cur["score"]) == (row["lord"], row["score"])


def test_current_hora_before_sunrise_belongs_to_the_previous_day():
    now = datetime(2026, 9, 24, 3, 0, tzinfo=MYT)  # Thursday, before sunrise
    cur = _handle_current_hora(load_provider(), {"rasi": 2}, now=now)
    assert cur["date"] == "2026-09-24"
    assert cur["hora"] >= 20  # the tail of Wednesday's cycle


# --- best_horas ------------------------------------------------------------------

BEST = {"rasi": 4, "date": "2026-09-24"}


def _hhmm(s):
    return datetime.strptime(s, "%H:%M")


def test_best_horas_top_count_sorted_desc_and_favourable():
    out = _handle_best_horas(load_provider(), {**BEST, "count": 3})
    scores = [h["score"] for h in out["horas"]]
    assert len(scores) <= 3 and scores == sorted(scores, reverse=True)
    assert all(s >= engine.FAVOURABLE_MIN for s in scores)


def test_best_horas_default_count_is_3():
    assert len(_handle_best_horas(load_provider(), BEST)["horas"]) <= 3


def test_best_horas_are_the_true_maxima_of_the_day():
    p = load_provider()
    full = _handle_rasi_hora_table(p, BEST)["horas"]
    best = _handle_best_horas(p, {**BEST, "count": 2})["horas"]
    expected = sorted((r["score"] for r in full), reverse=True)[:2]
    assert [h["score"] for h in best] == [s for s in expected if s >= engine.FAVOURABLE_MIN]


def test_best_horas_time_window_filters_by_start():
    out = _handle_best_horas(
        load_provider(), {**BEST, "count": 24, "from_time": "09:00", "to_time": "13:00"}
    )
    assert all(_hhmm("09:00") <= _hhmm(h["start"]) < _hhmm("13:00") for h in out["horas"])


def test_best_horas_uses_server_configured_own_lord_floor():
    out = _handle_best_horas(load_provider(), {**BEST, "count": 24}, own_lord_floor=100)
    assert all(h["score"] == 100 for h in out["horas"] if h["lord"] == "Moon")


@pytest.mark.parametrize(
    "extra, match",
    [
        ({"count": 0}, "count"),
        ({"count": 25}, "count"),
        ({"from_time": "9am"}, "from_time"),
        ({"to_time": "25:00"}, "to_time"),
        ({"from_time": "13:00", "to_time": "09:00"}, "from_time"),
    ],
)
def test_best_horas_validation(extra, match):
    with pytest.raises(RequestError, match=match):
        _handle_best_horas(load_provider(), {**BEST, **extra})


@pytest.mark.parametrize("tool", [_RASI_HORA_TABLE_TOOL, _BEST_HORAS_TOOL])
def test_description_has_example_and_pointer_to_a_sibling(tool):
    d = tool.description
    assert "Example" in d and tool.name in d and "Not for" in d


def test_descriptions_point_at_each_other():
    assert "best_horas" in _RASI_HORA_TABLE_TOOL.description
    assert "rasi_hora_table" in _BEST_HORAS_TOOL.description


def test_best_horas_schema():
    props = _BEST_HORAS_TOOL.inputSchema["properties"]
    assert {"rasi", "date", "count", "from_time", "to_time"} <= set(props)
    assert _BEST_HORAS_TOOL.inputSchema["required"] == ["rasi"]
