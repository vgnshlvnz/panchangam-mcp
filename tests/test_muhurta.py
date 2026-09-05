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
from panchangam.types import AngaSpan, NamedPeriod, Place

FIXTURES = Path(__file__).parent / "fixtures"
KL_FIXTURE = "drikpanchang_kuala_lumpur_2026-09-06.json"


def kl_place():
    fx = json.loads((FIXTURES / KL_FIXTURE).read_text())
    return Place(**fx["place"])


SUNDAY = date(2026, 9, 6)
WEEK = [SUNDAY + timedelta(days=n) for n in range(7)]  # Sun .. Sat


def _part_index(period, bounds):
    """1-based part of ``bounds`` that ``period`` exactly occupies."""
    for i in range(len(bounds) - 1):
        if period.start == bounds[i] and period.end == bounds[i + 1]:
            return i + 1
    raise AssertionError(f"{period} is not one part of {bounds}")


# --- the inauspicious eighths -----------------------------------------


@pytest.mark.parametrize("anga_fn", [muhurta.rahu_kalam, muhurta.yamaganda, muhurta.gulika])
def test_eighth_is_one_daylight_part(anga_fn):
    place = kl_place()
    sunrise = ephemeris.sunrise(SUNDAY, place)
    sunset = ephemeris.sunset(SUNDAY, place)
    bounds = muhurta._partition(sunrise, sunset, 8)

    period = anga_fn(SUNDAY, place)
    assert isinstance(period, NamedPeriod)
    assert period.auspicious is False
    assert 1 <= _part_index(period, bounds) <= 8
    assert sunrise <= period.start < period.end <= sunset
    eighth = (sunset - sunrise) / 8
    assert abs((period.end - period.start) - eighth) < timedelta(seconds=1)


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
    bounds = muhurta._partition(
        ephemeris.sunrise(day, place), ephemeris.sunset(day, place), 8
    )
    # the module tables...
    slot = day.isoweekday() % 7
    assert (
        muhurta.RAHU_KALAM_PART[slot],
        muhurta.YAMAGANDA_PART[slot],
        muhurta.GULIKA_PART[slot],
    ) == (rahu, yama, gulika)
    # ...and what the functions actually return
    assert _part_index(muhurta.rahu_kalam(day, place), bounds) == rahu
    assert _part_index(muhurta.yamaganda(day, place), bounds) == yama
    assert _part_index(muhurta.gulika(day, place), bounds) == gulika


def test_the_three_eighths_never_share_a_part():
    for day in WEEK:
        slot = day.isoweekday() % 7
        parts = {
            muhurta.RAHU_KALAM_PART[slot],
            muhurta.YAMAGANDA_PART[slot],
            muhurta.GULIKA_PART[slot],
        }
        assert len(parts) == 3


def test_rahu_kalam_times_on_the_fixture_sunday():
    # Regression pin on our own output (drikpanchang lists these to the
    # minute; architect spot-checking): Sunday rahu kalam is the last eighth.
    period = muhurta.rahu_kalam(SUNDAY, kl_place())
    assert period.name == "Rahu Kalam"
    assert period.start.strftime("%H:%M") == "17:45"
    assert period.end.strftime("%H:%M") == "19:16"


# --- abhijit ---------------------------------------------------------


def test_abhijit_straddles_the_daylight_midpoint():
    place = kl_place()
    sunrise = ephemeris.sunrise(SUNDAY, place)
    sunset = ephemeris.sunset(SUNDAY, place)
    midpoint = sunrise + (sunset - sunrise) / 2

    period = muhurta.abhijit(SUNDAY, place)
    assert isinstance(period, NamedPeriod)
    assert period.name == "Abhijit Muhurta"
    assert period.auspicious is True
    assert period.start < midpoint < period.end
    # one of fifteen equal daylight muhurtas
    muhurta_width = (sunset - sunrise) / 15
    assert abs((period.end - period.start) - muhurta_width) < timedelta(seconds=1)


def test_abhijit_is_computed_every_day_including_wednesday():
    place = kl_place()
    for day in WEEK:
        period = muhurta.abhijit(day, place)
        assert period.start < period.end


# --- choghadiya ----------------------------------------------------


def test_choghadiya_has_16_contiguous_parts_covering_day_then_night():
    place = kl_place()
    sunrise = ephemeris.sunrise(SUNDAY, place)
    sunset = ephemeris.sunset(SUNDAY, place)
    next_sunrise = ephemeris.sunrise(SUNDAY + timedelta(days=1), place)

    spans = muhurta.choghadiya(SUNDAY, place)
    assert all(isinstance(s, AngaSpan) for s in spans)  # not NamedPeriod
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
