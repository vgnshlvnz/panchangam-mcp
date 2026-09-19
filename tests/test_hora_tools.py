"""rasi_hora_table and current_hora, against the real Swiss Ephemeris backend.

Reference values for hora scores are not asserted: the nature / friendship /
gochara tables are provisional. TODO: verify against a printed panchangam.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from panchangam.server import (
    RequestError,
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
