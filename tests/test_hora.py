"""Tests for the 24 planetary horas of a day.

Rules under test (CLAUDE.md "Domain rules"): fixed 60 min from sunrise, hora 1
is the weekday lord, order Sun -> Venus -> Mercury -> Moon -> Saturn -> Jupiter
-> Mars. No printed-panchangam reference values are used.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from panchangam import ephemeris, hora
from panchangam.types import AngaSpan, Place

FIXTURES = Path(__file__).parent / "fixtures"
SUNDAY = date(2026, 9, 6)
WEEK = [SUNDAY + timedelta(days=n) for n in range(7)]  # Sun .. Sat
WEEKDAY_LORDS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")
ORDER = ("Sun", "Venus", "Mercury", "Moon", "Saturn", "Jupiter", "Mars")


def kl_place():
    fx = json.loads((FIXTURES / "drikpanchang_kuala_lumpur_2026-09-06.json").read_text())
    return Place(**fx["place"])


def test_thursday_hora_1_is_jupiter():
    assert hora.horas(date(2026, 9, 24), kl_place())[0].name == "Jupiter"


@pytest.mark.parametrize("day,lord", zip(WEEK, WEEKDAY_LORDS))
def test_hora_1_is_weekday_lord(day, lord):
    assert hora.horas(day, kl_place())[0].name == lord


def test_lords_follow_the_planetary_order():
    spans = hora.horas(SUNDAY, kl_place())
    start = ORDER.index(spans[0].name)
    assert [s.name for s in spans] == [ORDER[(start + i) % 7] for i in range(24)]


def test_24_indexed_spans():
    spans = hora.horas(SUNDAY, kl_place())
    assert len(spans) == 24
    assert [s.index for s in spans] == list(range(1, 25))
    assert all(isinstance(s, AngaSpan) for s in spans)


def test_spans_are_contiguous_hours_from_sunrise():
    place = kl_place()
    spans = hora.horas(SUNDAY, place)
    assert spans[0].start == ephemeris.sunrise(SUNDAY, place)
    for a, b in zip(spans, spans[1:]):
        assert a.end == b.start
    assert all(s.end - s.start == timedelta(minutes=60) for s in spans)


def test_hora_25_would_repeat_hora_1_lord_shifted_by_three():
    # 24 % 7 == 3: the next day's hora 1 is the lord 3 places on in the order,
    # which is the next weekday's lord. Guards the Sunday-first table.
    for today, tomorrow in zip(WEEK, WEEK[1:] + [WEEK[0]]):
        first = hora.horas(today, kl_place())[0].name
        nxt = hora.horas(tomorrow, kl_place())[0].name
        assert ORDER[(ORDER.index(first) + 24) % 7] == nxt
