"""Tests for the ascendant and the rasi-lagna windows of a day.

Independent checks only: geometry (windows tile the sunrise-to-sunrise day),
consistency (each boundary is where the ascendant reaches a multiple of 30 deg),
and one physical sanity check (at sunrise the ascendant is close to the Sun's
own longitude). No printed-panchangam reference values.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

import pytest

from panchangam import ephemeris, lagna
from panchangam.types import AngaSpan, Place

FIXTURES = Path(__file__).parent / "fixtures"
DAY = date(2026, 9, 6)


def kl_place():
    fx = json.loads((FIXTURES / "drikpanchang_kuala_lumpur_2026-09-06.json").read_text())
    return Place(**fx["place"])


def test_ascendant_is_sidereal_degrees():
    place = kl_place()
    asc = ephemeris.ascendant(ephemeris.sunrise(DAY, place), place)
    assert 0.0 <= asc < 360.0


def test_ascendant_at_sunrise_is_near_the_sun():
    place = kl_place()
    rise = ephemeris.sunrise(DAY, place)
    delta = ephemeris._signed_delta(
        ephemeris.ascendant(rise, place), ephemeris.sun_longitude(rise)
    )
    assert abs(delta) < 3.0


def test_windows_tile_sunrise_to_next_sunrise():
    place = kl_place()
    spans = lagna.lagna(DAY, place)
    assert all(isinstance(s, AngaSpan) for s in spans)
    assert spans[0].start <= ephemeris.sunrise(DAY, place) < spans[0].end
    assert spans[-1].end >= ephemeris.sunrise(DAY + timedelta(days=1), place)
    for a, b in pairwise(spans):
        assert a.end == b.start
        assert b.index == a.index % 12 + 1


def test_first_window_is_the_rasi_of_the_sunrise_ascendant():
    place = kl_place()
    rise = ephemeris.sunrise(DAY, place)
    spans = lagna.lagna(DAY, place)
    assert spans[0].index == int(ephemeris.ascendant(rise, place) // 30.0) + 1


def test_every_boundary_is_a_multiple_of_30_degrees():
    place = kl_place()
    for span in lagna.lagna(DAY, place)[:-1]:
        asc = ephemeris.ascendant(span.end, place)
        assert abs(ephemeris._signed_delta(asc, span.index * 30.0 % 360.0)) < 0.01


def test_a_day_holds_about_a_full_zodiac_of_windows():
    spans = lagna.lagna(DAY, kl_place())
    assert 12 <= len(spans) <= 14


def test_names_cover_twelve_rasis():
    assert len(lagna.RASI_NAMES) == 12
    assert lagna.RASI_NAMES[0] == "Mesha"


@pytest.mark.parametrize("n", range(7))
def test_holds_across_a_week(n):
    place = kl_place()
    spans = lagna.lagna(DAY + timedelta(days=n), place)
    assert all(a.end == b.start for a, b in pairwise(spans))
