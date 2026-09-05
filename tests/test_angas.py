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
KL_MONTH_FIXTURE = "panchangam_kuala_lumpur_2026-09.json"


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


# --- tithi across a whole lunation --------------------------------------
#
# panchangam_kuala_lumpur_2026-09.json freezes tithi() output for every day of
# September 2026 -- one full lunation (Krishna Chaturthi #19 through the next
# Krishna Panchami #20). Three instants in it are externally verified; the rest
# is a regression + invariant guard. See the fixture's _note.


def month_fixture():
    return load_fixture(KL_MONTH_FIXTURE)


def recompute_month(fx):
    """tithi() for every day in the fixture, in date order."""
    place = fixture_place(fx)
    return [
        (day, angas.tithi(date.fromisoformat(day), place))
        for day in sorted(fx["days"])
    ]


def test_month_reproduces_frozen_spans():
    fx = month_fixture()
    for day, spans in recompute_month(fx):
        frozen = fx["days"][day]
        assert [s.index for s in spans] == [f["index"] for f in frozen]
        assert [s.name for s in spans] == [f["name"] for f in frozen]
        for span, f in zip(spans, frozen):
            # self-generated fixture: allow only patch-level ephemeris drift
            assert abs(span.start - datetime.fromisoformat(f["start"])) <= timedelta(seconds=5)
            assert abs(span.end - datetime.fromisoformat(f["end"])) <= timedelta(seconds=5)


def test_month_spans_are_contiguous_within_and_across_days():
    fx = month_fixture()
    month = recompute_month(fx)
    for _, spans in month:
        for earlier, later in zip(spans, spans[1:]):
            assert earlier.end == later.start
    # the last span of one day and the first of the next are the same tithi,
    # carried across the shared sunrise. The boundary instant is recomputed
    # from a different bracket in each call, so it agrees only to within the
    # find_crossing tolerance -- not to the microsecond.
    for (_, today), (_, tomorrow) in zip(month, month[1:]):
        assert today[-1].index == tomorrow[0].index
        assert abs(today[-1].start - tomorrow[0].start) <= timedelta(seconds=2)


def test_month_tithi_index_advances_by_one_mod_thirty():
    fx = month_fixture()
    sequence = []
    for _, spans in recompute_month(fx):
        for span in spans:
            if not sequence or sequence[-1] != span.index:
                sequence.append(span.index)
    # every tithi of the lunation, once, in order, wrapping Amavasya -> Pratipada
    assert sequence[0] == 19
    for prev, curr in zip(sequence, sequence[1:]):
        assert curr == prev % 30 + 1
    assert set(range(1, 31)) <= set(sequence)
    assert sequence.count(30) == 1  # one Amavasya
    assert sequence.count(15) == 1  # one Purnima


def test_month_external_anchors():
    fx = month_fixture()
    place = fixture_place(fx)
    for day, anchor in fx["anchors"].items():
        expected = datetime.fromisoformat(anchor["expected"])
        boundaries = set()
        for span in angas.tithi(date.fromisoformat(day), place):
            boundaries.add(span.start)
            boundaries.add(span.end)
        closest = min(boundaries, key=lambda t: abs(t - expected))
        assert abs(closest - expected) <= BOUNDARY_TOLERANCE, anchor["what"]
