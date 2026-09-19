"""Tests for panchangam.hora.engine -- pure hora scoring, no I/O.

Scoring tables (nature, friendship, gochara) are provisional defaults chosen by
the assistant, not taken from a printed source. Tests here assert structure and
the own-lord floor, never specific table values.
TODO: verify tables against the user's reference before asserting exact scores.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from panchangam.hora import engine

# Sidereal longitudes (degrees) that put a lord in house 1 / house 2 from Aries.
IN_ARIES = 10.0


def test_thursday_hora_1_is_jupiter():
    assert engine.hora_lord(weekday=4, hora=1) == "Jupiter"  # Sun=0 .. Sat=6


def test_hora_lord_order_and_cycle():
    assert [engine.hora_lord(0, h) for h in (1, 2, 3, 4, 5, 6, 7, 8)] == [
        "Sun", "Venus", "Mercury", "Moon", "Saturn", "Jupiter", "Mars", "Sun",
    ]
    assert engine.hora_lord(4, 2) == "Mars"


def test_rasi_lord_of_aries_is_mars():
    assert engine.rasi_lord(1) == "Mars"


# --- 1. own-lord floor ---------------------------------------------------------


def test_own_lord_hora_never_scores_below_default_floor():
    # Mars rules Aries. Try every house: none may fall below 60.
    for house in range(1, 13):
        lon = (house - 1) * 30.0 + 5.0
        assert engine.score_hora(1, "Mars", lon)["total"] >= 60


def test_own_lord_floor_is_configurable():
    for house in range(1, 13):
        lon = (house - 1) * 30.0 + 5.0
        assert engine.score_hora(1, "Mars", lon, own_lord_floor=85)["total"] >= 85


def test_floor_does_not_lift_other_lords():
    # Saturn is not Aries' lord; floor must not apply to it.
    totals = [
        engine.score_hora(1, "Saturn", (h - 1) * 30.0 + 5.0, own_lord_floor=100)["total"]
        for h in range(1, 13)
    ]
    assert min(totals) < 100


def test_floor_only_raises_total_parts_stay_raw():
    s = engine.score_hora(1, "Mars", IN_ARIES, own_lord_floor=100)
    assert s["total"] == 100
    assert s["nature"] + s["friendship"] + s["gochara"] <= 100


def test_total_is_sum_of_parts_when_no_floor_applies():
    s = engine.score_hora(1, "Saturn", IN_ARIES, own_lord_floor=0)
    assert s["total"] == s["nature"] + s["friendship"] + s["gochara"]


# --- 3. breakdown --------------------------------------------------------------


def _lons():
    return tuple(float(i * 13 % 360) for i in range(24))


def test_table_has_24_one_based_rows_with_small_default_keys():
    rows = engine.hora_table(rasi=1, weekday=4, lord_longitudes=_lons())
    assert [r["hora"] for r in rows] == list(range(1, 25))
    assert rows[0]["lord"] == "Jupiter"
    assert set(rows[0]) == {"hora", "lord", "score"}


def test_table_breakdown_adds_three_parts():
    rows = engine.hora_table(1, 4, _lons(), breakdown=True)
    assert set(rows[0]) == {"hora", "lord", "score", "nature", "friendship", "gochara"}


def test_table_rejects_bad_rasi():
    with pytest.raises(ValueError):
        engine.hora_table(13, 4, _lons())


def test_table_own_lord_floor_argument_is_used():
    lo = engine.hora_table(1, 2, _lons(), own_lord_floor=0)  # Tuesday: hora 1 Mars
    hi = engine.hora_table(1, 2, _lons(), own_lord_floor=100)
    assert hi[0]["score"] == 100 and hi[0]["score"] >= lo[0]["score"]


# --- purity --------------------------------------------------------------------


def test_engine_is_pure_no_io_or_config_imports():
    tree = ast.parse(Path(engine.__file__).read_text())
    banned = {"os", "pathlib", "yaml", "tomllib", "json", "socket", "swisseph", "panchangam"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not imported & banned
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "open" not in calls
