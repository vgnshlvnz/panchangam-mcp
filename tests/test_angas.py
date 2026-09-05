"""Tests for the five angas.

Ground truth is ``tests/fixtures/*.json``, scraped from drikpanchang.com (which
uses the Lahiri ayanamsa, same as the ephemeris lane). A drikpanchang day page
reports the anga in force at sunrise and the clock time it ends; that pins the
last two fields of the first span in our sunrise-to-sunrise list.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from panchangam import angas
from panchangam.types import AngaSpan, Place

FIXTURES = Path(__file__).parent / "fixtures"

# drikpanchang prints boundary times to the minute; the ephemeris root-finder
# is good to the second. Allow a little more than a minute of rounding slack.
BOUNDARY_TOLERANCE = timedelta(minutes=2)


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def fixture_place(fx):
    return Place(**fx["place"])


KL_FIXTURE = "drikpanchang_kuala_lumpur_2026-09-06.json"


# --- tithi --------------------------------------------------------------


def test_tithi_name_covers_both_pakshas_and_the_poles():
    assert angas._tithi_name(1) == "Shukla Pratipada"
    assert angas._tithi_name(10) == "Shukla Dashami"
    assert angas._tithi_name(15) == "Purnima"
    assert angas._tithi_name(16) == "Krishna Pratipada"
    assert angas._tithi_name(25) == "Krishna Dashami"
    assert angas._tithi_name(30) == "Amavasya"


def test_tithi_at_kuala_lumpur_matches_drikpanchang():
    fx = load_fixture(KL_FIXTURE)
    spans = angas.tithi(date.fromisoformat(fx["date"]), fixture_place(fx))

    # The fixture day carries two tithis: Krishna Dashami, then Ekadashi.
    assert [s.index for s in spans] == [25, 26]
    assert [s.name for s in spans] == ["Krishna Dashami", "Krishna Ekadashi"]

    first = spans[0]
    expected_end = datetime.fromisoformat(fx["tithi"]["ends_at"])
    assert abs(first.end - expected_end) <= BOUNDARY_TOLERANCE
    # Krishna Dashami is #25: its number and the fixture agree.
    assert first.index == fx["tithi"]["number"]


def test_tithi_spans_are_contiguous_and_cover_the_window():
    fx = load_fixture(KL_FIXTURE)
    place = fixture_place(fx)
    day = date.fromisoformat(fx["date"])
    spans = angas.tithi(day, place)

    for earlier, later in zip(spans, spans[1:]):
        assert earlier.end == later.start  # no gaps, no overlaps

    from panchangam import ephemeris

    window_start = ephemeris.sunrise(day, place)
    window_end = ephemeris.sunrise(day + timedelta(days=1), place)
    assert spans[0].start <= window_start
    assert spans[-1].end >= window_end


def test_tithi_spans_are_tz_aware_in_place_zone():
    fx = load_fixture(KL_FIXTURE)
    spans = angas.tithi(date.fromisoformat(fx["date"]), fixture_place(fx))
    for span in spans:
        assert isinstance(span, AngaSpan)
        assert span.start.utcoffset() == timedelta(hours=8)
        assert span.end.utcoffset() == timedelta(hours=8)
        assert span.start < span.end
