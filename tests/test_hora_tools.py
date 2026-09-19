"""MCP tools rasi_hora_table and best_horas, against a stub provider.

The stub returns fixed sunrise and lord longitudes; nothing astronomical is
asserted, only tool behaviour. TODO: verify real hora times/scores against a
printed panchangam once the tables are confirmed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from panchangam.hora import engine
from panchangam.server import (
    _BEST_HORAS_TOOL,
    _RASI_HORA_TABLE_TOOL,
    RequestError,
    _handle_best_horas,
    _handle_rasi_hora_table,
    build_server,
)

MYT = timezone(timedelta(hours=8))
SUNRISE = datetime(2026, 9, 24, 6, 58, tzinfo=MYT)  # a Thursday


class _HoraProvider:
    def __init__(self):
        self.calls = []

    def hora_day(self, place, day):
        self.calls.append((place, day))
        return SUNRISE, tuple(float(i * 37 % 360) for i in range(24))


ARGS = {"rasi": 1, "date": "2026-09-24"}


def _hhmm(s):
    return datetime.strptime(s, "%H:%M")


# --- rasi_hora_table -----------------------------------------------------------


def test_table_default_output_is_small_and_uses_hhmm():
    out = _handle_rasi_hora_table(_HoraProvider(), ARGS)
    assert out["date"] == "2026-09-24"
    assert len(out["horas"]) == 24
    row = out["horas"][0]
    assert set(row) == {"hora", "lord", "start", "end", "score"}
    assert row["lord"] == "Jupiter" and row["start"] == "06:58" and row["end"] == "07:58"


def test_table_score_breakdown_flag():
    out = _handle_rasi_hora_table(_HoraProvider(), {**ARGS, "score_breakdown": True})
    assert {"nature", "friendship", "gochara"} <= set(out["horas"][0])


def test_table_uses_server_configured_own_lord_floor():
    out = _handle_rasi_hora_table(_HoraProvider(), ARGS, own_lord_floor=100)
    assert all(r["score"] == 100 for r in out["horas"] if r["lord"] == "Mars")


def test_table_rejects_bad_rasi():
    with pytest.raises(RequestError, match="rasi"):
        _handle_rasi_hora_table(_HoraProvider(), {**ARGS, "rasi": 13})


def test_table_defaults_place_to_petaling_jaya():
    p = _HoraProvider()
    _handle_rasi_hora_table(p, ARGS)
    place, _ = p.calls[0]
    assert (place.latitude, place.longitude, place.timezone) == (3.1073, 101.6067, "Asia/Kuala_Lumpur")


def test_table_date_defaults_to_today_in_tz():
    out = _handle_rasi_hora_table(_HoraProvider(), {"rasi": 1})
    assert len(out["date"]) == 10


# --- 2. best_horas -------------------------------------------------------------


def test_best_horas_returns_top_count_sorted_desc_and_favourable():
    out = _handle_best_horas(_HoraProvider(), {**ARGS, "count": 3})
    scores = [h["score"] for h in out["horas"]]
    assert len(scores) <= 3 and scores == sorted(scores, reverse=True)
    assert all(s >= engine.FAVOURABLE_MIN for s in scores)


def test_best_horas_default_count_is_3():
    assert len(_handle_best_horas(_HoraProvider(), ARGS)["horas"]) <= 3


def test_best_horas_are_the_true_maxima_of_the_day():
    full = _handle_rasi_hora_table(_HoraProvider(), ARGS)["horas"]
    best = _handle_best_horas(_HoraProvider(), {**ARGS, "count": 2})["horas"]
    expected = sorted((r["score"] for r in full), reverse=True)[:2]
    assert [h["score"] for h in best] == [s for s in expected if s >= engine.FAVOURABLE_MIN]


def test_best_horas_time_window_filters_by_start():
    out = _handle_best_horas(
        _HoraProvider(),
        {**ARGS, "count": 24, "from_time": "09:00", "to_time": "13:00"},
    )
    assert all(_hhmm("09:00") <= _hhmm(h["start"]) < _hhmm("13:00") for h in out["horas"])


def test_best_horas_window_may_be_empty():
    out = _handle_best_horas(
        _HoraProvider(), {**ARGS, "from_time": "12:00", "to_time": "12:01"}
    )
    assert isinstance(out["horas"], list)


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
        _handle_best_horas(_HoraProvider(), {**ARGS, **extra})


# --- 4. tool descriptions ------------------------------------------------------


@pytest.mark.parametrize("tool", [_RASI_HORA_TABLE_TOOL, _BEST_HORAS_TOOL])
def test_description_has_when_to_use_example_and_sibling_pointer(tool):
    d = tool.description
    assert "Example" in d and tool.name in d
    assert "Not for" in d or "instead" in d


def test_descriptions_point_at_each_other():
    assert "best_horas" in _RASI_HORA_TABLE_TOOL.description
    assert "rasi_hora_table" in _BEST_HORAS_TOOL.description


def test_schemas_expose_the_new_arguments():
    assert _RASI_HORA_TABLE_TOOL.inputSchema["properties"]["score_breakdown"]["type"] == "boolean"
    props = _BEST_HORAS_TOOL.inputSchema["properties"]
    assert {"rasi", "date", "count", "from_time", "to_time"} <= set(props)
    assert _BEST_HORAS_TOOL.inputSchema["required"] == ["rasi"]


def test_server_lists_both_tools():
    import anyio
    from mcp.types import ListToolsRequest

    server = build_server(_HoraProvider())
    handler = server.request_handlers[ListToolsRequest]

    async def run():
        res = await handler(ListToolsRequest(method="tools/list"))
        return {t.name for t in res.root.tools}

    assert {"rasi_hora_table", "best_horas"} <= anyio.run(run)


# --- real Swiss Ephemeris backend ------------------------------------------------


def test_real_backend_thursday_hora_1_is_jupiter():
    pytest.importorskip("swisseph")
    from panchangam.server import load_provider

    out = _handle_rasi_hora_table(load_provider(), {"rasi": 4, "date": "2026-09-24"})
    assert len(out["horas"]) == 24
    assert out["horas"][0]["lord"] == "Jupiter"
    assert all(0 <= h["score"] <= 100 for h in out["horas"])
    best = _handle_best_horas(load_provider(), {"rasi": 4, "date": "2026-09-24"})
    assert len(best["horas"]) <= 3
