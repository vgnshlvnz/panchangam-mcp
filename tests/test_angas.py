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


# --- shape shared by tithi, nakshatra and yoga -------------------------

SPAN_LISTS = {
    "tithi": (angas.tithi, angas.TITHI_COUNT),
    "nakshatra": (angas.nakshatra, angas.NAKSHATRA_COUNT),
    "yoga": (angas.yoga, angas.YOGA_COUNT),
}


@pytest.mark.parametrize("anga_fn, count", SPAN_LISTS.values(), ids=SPAN_LISTS)
def test_span_list_is_contiguous_and_covers_the_window(anga_fn, count):
    from panchangam import ephemeris

    fx = load_fixture(KL_FIXTURE)
    place = fixture_place(fx)
    day = date.fromisoformat(fx["date"])
    spans = anga_fn(day, place)

    for earlier, later in zip(spans, spans[1:]):
        assert earlier.end == later.start  # no gaps, no overlaps

    window_start = ephemeris.sunrise(day, place)
    window_end = ephemeris.sunrise(day + timedelta(days=1), place)
    assert spans[0].start <= window_start
    assert spans[-1].end >= window_end


@pytest.mark.parametrize("anga_fn, count", SPAN_LISTS.values(), ids=SPAN_LISTS)
def test_span_list_fields_are_well_formed(anga_fn, count):
    fx = load_fixture(KL_FIXTURE)
    spans = anga_fn(date.fromisoformat(fx["date"]), fixture_place(fx))
    assert spans
    for span in spans:
        assert isinstance(span, AngaSpan)
        assert 1 <= span.index <= count
        assert span.start.utcoffset() == timedelta(hours=8)
        assert span.end.utcoffset() == timedelta(hours=8)
        assert span.start < span.end


# --- nakshatra --------------------------------------------------------


def test_nakshatra_at_kuala_lumpur_matches_drikpanchang():
    fx = load_fixture(KL_FIXTURE)
    spans = angas.nakshatra(date.fromisoformat(fx["date"]), fixture_place(fx))

    assert [s.index for s in spans] == [6, 7]
    assert [s.name for s in spans] == ["Ardra", "Punarvasu"]

    first = spans[0]
    assert first.index == fx["nakshatra"]["number"]
    assert first.name == fx["nakshatra"]["name"]
    expected_end = datetime.fromisoformat(fx["nakshatra"]["ends_at"])
    assert abs(first.end - expected_end) <= BOUNDARY_TOLERANCE


def test_nakshatra_name_table_is_27_long_and_ordered():
    assert len(angas._NAKSHATRA_NAMES) == 27
    assert angas._NAKSHATRA_NAMES[0] == "Ashwini"
    assert angas._NAKSHATRA_NAMES[5] == "Ardra"
    assert angas._NAKSHATRA_NAMES[-1] == "Revati"


# --- yoga ------------------------------------------------------------


def test_yoga_name_table_is_27_long_and_ordered():
    assert len(angas._YOGA_NAMES) == 27
    assert angas._YOGA_NAMES[0] == "Vishkambha"
    assert angas._YOGA_NAMES[-1] == "Vaidhriti"


def test_yoga_at_kuala_lumpur_is_siddhi_then_vyatipata():
    # The fixture has no drikpanchang yoga row, so this is a regression pin on
    # our own output, not external ground truth: the Sun+Moon sidereal sum
    # crosses 16 * 13.333 deg (Siddhi -> Vyatipata) near midday on 2026-09-06.
    fx = load_fixture(KL_FIXTURE)
    spans = angas.yoga(date.fromisoformat(fx["date"]), fixture_place(fx))
    assert [s.name for s in spans] == ["Siddhi", "Vyatipata"]
    assert spans[0].index == 16
    assert spans[0].end.strftime("%H:%M") == "12:15"


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


# --- nakshatra and yoga across the same month --------------------------
#
# No external ground truth for a full month of these, and no frozen fixture --
# only the invariant that the index steps by 1 (mod 27), never skipping or
# repeating, with every division appearing. A wrong step size, a naming
# off-by-one, or a broken 360 deg wrap all fail here.

MONTH_INVARIANTS = {
    "nakshatra": (angas.nakshatra, 27),
    "yoga": (angas.yoga, 27),
}


@pytest.mark.parametrize(
    "anga_fn, count", MONTH_INVARIANTS.values(), ids=MONTH_INVARIANTS
)
def test_month_index_advances_by_one_mod_count(anga_fn, count):
    fx = month_fixture()
    place = fixture_place(fx)
    sequence = []
    for day in sorted(fx["days"]):
        spans = anga_fn(date.fromisoformat(day), place)
        for earlier, later in zip(spans, spans[1:]):
            assert earlier.end == later.start
        for span in spans:
            assert 1 <= span.index <= count
            if not sequence or sequence[-1] != span.index:
                sequence.append(span.index)
    for prev, curr in zip(sequence, sequence[1:]):
        assert curr == prev % count + 1
    assert set(range(1, count + 1)) <= set(sequence)  # 30 days > one full cycle
