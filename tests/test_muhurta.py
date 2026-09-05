"""Tests for the standard day divisions.

These depend only on sunrise/sunset and the weekday, so the checks are of two
kinds: the weekday -> part tables (published values, parametrised over all
seven days) and the geometry (a part is 1/8 or 1/15 of the daylight span, in
the right place, contiguous). The 2026-09-06 fixture supplies one real
sunrise/sunset pair; that day is a Sunday.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from panchangam import ephemeris, muhurta
from panchangam.types import AngaSpan, Place

FIXTURES = Path(__file__).parent / "fixtures"
KL_FIXTURE = "drikpanchang_kuala_lumpur_2026-09-06.json"


def kl_place():
    fx = json.loads((FIXTURES / KL_FIXTURE).read_text())
    return Place(**fx["place"])


SUNDAY = date(2026, 9, 6)
WEEK = [SUNDAY + timedelta(days=n) for n in range(7)]  # Sun .. Sat


# --- the inauspicious eighths -----------------------------------------


@pytest.mark.parametrize("anga_fn", [muhurta.rahu_kalam, muhurta.yamagandam, muhurta.gulika])
def test_eighth_is_one_daylight_part_in_the_right_slot(anga_fn):
    place = kl_place()
    sunrise = ephemeris.sunrise(SUNDAY, place)
    sunset = ephemeris.sunset(SUNDAY, place)
    bounds = muhurta._partition(sunrise, sunset, 8)

    span = anga_fn(SUNDAY, place)
    assert isinstance(span, AngaSpan)
    assert 1 <= span.index <= 8
    assert span.start == bounds[span.index - 1]
    assert span.end == bounds[span.index]
    assert sunrise <= span.start < span.end <= sunset
    eighth = (sunset - sunrise) / 8
    assert abs((span.end - span.start) - eighth) < timedelta(seconds=1)


@pytest.mark.parametrize(
    "day, rahu, yama, gulika",
    [
        (WEEK[0], 8, 5, 7),  # Sunday
        (WEEK[1], 2, 4, 6),  # Monday
        (WEEK[2], 7, 3, 5),  # Tuesday
        (WEEK[3], 5, 2, 4),  # Wednesday
        (WEEK[4], 6, 1, 3),  # Thursday
        (WEEK[5], 4, 7, 2),  # Friday
        (WEEK[6], 3, 6, 1),  # Saturday
    ],
)
def test_weekday_part_tables(day, rahu, yama, gulika):
    place = kl_place()
    assert muhurta.rahu_kalam(day, place).index == rahu
    assert muhurta.yamagandam(day, place).index == yama
    assert muhurta.gulika(day, place).index == gulika


def test_the_three_eighths_never_share_a_part():
    place = kl_place()
    for day in WEEK:
        parts = {
            muhurta.rahu_kalam(day, place).index,
            muhurta.yamagandam(day, place).index,
            muhurta.gulika(day, place).index,
        }
        assert len(parts) == 3


def test_rahu_kalam_times_on_the_fixture_sunday():
    # Regression pin on our own output (drikpanchang lists these to the
    # minute; architect spot-checking): Sunday rahu kalam is the last eighth.
    span = muhurta.rahu_kalam(SUNDAY, kl_place())
    assert span.start.strftime("%H:%M") == "17:45"
    assert span.end.strftime("%H:%M") == "19:16"


# --- abhijit ---------------------------------------------------------


def test_abhijit_straddles_the_daylight_midpoint():
    place = kl_place()
    sunrise = ephemeris.sunrise(SUNDAY, place)
    sunset = ephemeris.sunset(SUNDAY, place)
    midpoint = sunrise + (sunset - sunrise) / 2

    span = muhurta.abhijit(SUNDAY, place)
    assert span.index == 8
    assert span.name == "Abhijit"
    assert span.start < midpoint < span.end
    # one of fifteen equal daylight muhurtas
    muhurta_width = (sunset - sunrise) / 15
    assert abs((span.end - span.start) - muhurta_width) < timedelta(seconds=1)


def test_abhijit_is_computed_every_day_including_wednesday():
    place = kl_place()
    for day in WEEK:
        span = muhurta.abhijit(day, place)
        assert span.start < span.end


# --- choghadiya ----------------------------------------------------


def test_choghadiya_has_16_contiguous_parts_covering_day_then_night():
    place = kl_place()
    sunrise = ephemeris.sunrise(SUNDAY, place)
    sunset = ephemeris.sunset(SUNDAY, place)
    next_sunrise = ephemeris.sunrise(SUNDAY + timedelta(days=1), place)

    spans = muhurta.choghadiya(SUNDAY, place)
    assert [s.index for s in spans] == list(range(1, 17))
    for earlier, later in zip(spans, spans[1:]):
        assert earlier.end == later.start

    assert spans[0].start == sunrise
    assert spans[7].end == sunset
    assert spans[8].start == sunset
    assert spans[15].end == next_sunrise

    for span in spans:
        assert span.name in muhurta.CHOGHADIYA_QUALITY


@pytest.mark.parametrize(
    "day, day_first, night_first",
    [
        (WEEK[0], "Udveg", "Shubh"),  # Sunday
        (WEEK[1], "Amrit", "Char"),   # Monday
        (WEEK[2], "Rog", "Kaal"),     # Tuesday
        (WEEK[3], "Labh", "Udveg"),   # Wednesday
        (WEEK[4], "Shubh", "Amrit"),  # Thursday
        (WEEK[5], "Char", "Rog"),     # Friday
        (WEEK[6], "Kaal", "Labh"),    # Saturday
    ],
)
def test_choghadiya_sequence_start_by_weekday(day, day_first, night_first):
    spans = muhurta.choghadiya(day, kl_place())
    assert spans[0].name == day_first
    assert spans[8].name == night_first
    # each block cycles the 7 names in fixed order, wrapping once
    cycle = muhurta._CHOGHADIYA_CYCLE
    for block_start in (0, 8):
        first_pos = cycle.index(spans[block_start].name)
        for k in range(8):
            assert spans[block_start + k].name == cycle[(first_pos + k) % 7]


def test_choghadiya_quality_table_partitions_the_seven_names():
    q = muhurta.CHOGHADIYA_QUALITY
    assert set(q) == set(muhurta._CHOGHADIYA_CYCLE)
    assert {name for name, v in q.items() if v == "good"} == {"Amrit", "Shubh", "Labh"}
    assert {name for name, v in q.items() if v == "bad"} == {"Udveg", "Kaal", "Rog"}
    assert {name for name, v in q.items() if v == "neutral"} == {"Char"}
