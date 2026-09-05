"""Tests for the MCP panchangam server.

This file grows with the lane. First slice: input validation -- every bad
argument must produce a :class:`RequestError` a model can act on.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from panchangam.server import (
    RequestError,
    _GET_PANCHANGAM_TOOL,
    _handle_get_panchangam,
    build_place,
    build_server,
    parse_query_date,
)
from panchangam.types import AngaSpan, DayPanchangam, Place

from fakes import FakePanchangamProvider, MissingFixtureError

KL = build_place(3.14111, 101.68639, "Asia/Kuala_Lumpur", name="Kuala Lumpur")
KL_DAY = date(2026, 9, 6)


# --- parse_query_date --------------------------------------------------------


def test_parse_query_date_accepts_iso_date():
    assert parse_query_date("2026-09-06") == date(2026, 9, 6)


@pytest.mark.parametrize(
    "value",
    ["2026-9-6", "06/09/2026", "2026-13-01", "next tuesday", "2026-09-06T06:00"],
)
def test_parse_query_date_rejects_non_iso(value):
    with pytest.raises(RequestError) as exc:
        parse_query_date(value)
    assert "2026-09-06" in str(exc.value)  # message shows the wanted format


def test_parse_query_date_rejects_non_string():
    with pytest.raises(RequestError, match="must be a string"):
        parse_query_date(20260906)


# --- build_place: latitude / longitude --------------------------------------


def test_build_place_happy_path():
    place = build_place(3.14111, 101.68639, "Asia/Kuala_Lumpur")
    assert isinstance(place, Place)
    assert place.latitude == pytest.approx(3.14111)
    assert place.longitude == pytest.approx(101.68639)
    assert place.timezone == "Asia/Kuala_Lumpur"


@pytest.mark.parametrize("lat", [90.5, -91, 1000])
def test_build_place_rejects_out_of_range_latitude(lat):
    with pytest.raises(RequestError) as exc:
        build_place(lat, 0.0, "UTC")
    assert "-90 and 90" in str(exc.value)
    assert str(lat) in str(exc.value) or str(float(lat)) in str(exc.value)


@pytest.mark.parametrize("lon", [180.1, -181, 360])
def test_build_place_rejects_out_of_range_longitude(lon):
    with pytest.raises(RequestError, match="-180 and 180"):
        build_place(0.0, lon, "UTC")


def test_build_place_accepts_numeric_string_coordinates():
    place = build_place("3.14", "101.69", "Asia/Kuala_Lumpur")
    assert place.latitude == pytest.approx(3.14)


def test_build_place_rejects_non_numeric_coordinate():
    with pytest.raises(RequestError, match="lat must be a number"):
        build_place("north", 0.0, "UTC")


def test_build_place_rejects_boolean_coordinate():
    with pytest.raises(RequestError, match="lat must be a number"):
        build_place(True, 0.0, "UTC")


# --- build_place: timezone -------------------------------------------------


def test_build_place_rejects_unknown_zone():
    with pytest.raises(RequestError) as exc:
        build_place(0.0, 0.0, "Mars/Olympus_Mons")
    assert "Mars/Olympus_Mons" in str(exc.value)
    assert "IANA" in str(exc.value)


def test_build_place_rejects_utc_offset_as_zone():
    with pytest.raises(RequestError, match="not a UTC offset"):
        build_place(0.0, 0.0, "+05:30")


def test_build_place_rejects_non_string_zone():
    with pytest.raises(RequestError, match="tz must be an IANA"):
        build_place(0.0, 0.0, 5.5)


def test_build_place_zone_is_case_sensitive():
    # 'asia/kuala_lumpur' is not the zone key; the real one is 'Asia/Kuala_Lumpur'.
    with pytest.raises(RequestError):
        build_place(0.0, 0.0, "asia/kuala_lumpur")


# --- FakePanchangamProvider ------------------------------------------------


@pytest.fixture
def provider():
    return FakePanchangamProvider()


def test_fake_returns_a_daypanchangam(provider):
    result = provider.day_panchangam(KL, KL_DAY)
    assert isinstance(result, DayPanchangam)
    assert result.place is KL
    assert result.date == KL_DAY
    assert result.vaara == "Raviwara"


def test_fake_datetimes_are_tz_aware_in_place_zone(provider):
    result = provider.day_panchangam(KL, KL_DAY)
    stamps = [result.sunrise, result.sunset]
    for angas in (result.tithi, result.nakshatra, result.yoga, result.karana):
        for span in angas:
            stamps += [span.start, span.end]
    for when in stamps:
        assert when.tzinfo is not None
        assert when.utcoffset().total_seconds() == 8 * 3600


def test_fake_matches_fixture_anchors(provider):
    result = provider.day_panchangam(KL, KL_DAY)
    assert result.sunrise == datetime.fromisoformat("2026-09-06T07:07:00+08:00")
    assert result.tithi[0].name == "Krishna Dashami"
    assert result.tithi[0].index == 25
    assert result.tithi[0].end == datetime.fromisoformat("2026-09-06T21:59:00+08:00")
    assert result.nakshatra[-1].name == "Punarvasu"


@pytest.mark.parametrize("anga", ["tithi", "nakshatra", "yoga", "karana"])
def test_fake_anga_spans_are_contiguous_and_ordered(provider, anga):
    spans = getattr(provider.day_panchangam(KL, KL_DAY), anga)
    assert all(isinstance(s, AngaSpan) for s in spans)
    assert len(spans) >= 2
    for earlier, later in zip(spans, spans[1:]):
        assert earlier.end == later.start  # AngaSpan: end == next span's start
        assert earlier.start < earlier.end


def test_fake_raises_for_unknown_date(provider):
    with pytest.raises(MissingFixtureError, match="2026-06-01"):
        provider.day_panchangam(KL, date(2026, 6, 1))


def test_fake_raises_for_unknown_location(provider):
    tokyo = build_place(35.68, 139.69, "Asia/Tokyo")
    with pytest.raises(MissingFixtureError):
        provider.day_panchangam(tokyo, KL_DAY)


# --- get_panchangam tool schema ------------------------------------------------


def test_tool_advertises_the_four_arguments():
    schema = _GET_PANCHANGAM_TOOL.inputSchema
    assert schema["required"] == ["date", "lat", "lon", "tz"]
    assert schema["properties"]["lat"]["type"] == "number"
    assert schema["properties"]["tz"]["type"] == "string"


def test_tool_description_is_jargon_light():
    text = _GET_PANCHANGAM_TOOL.description.lower()
    # The description must stand on its own for a caller who has never heard
    # "tithi": every specialist term it uses is glossed in the same sentence.
    assert "lunar day" in text
    assert "new moon" in text and "full moon" in text
    assert "sunrise" in text and "sunset" in text
    assert "get_muhurta" in text  # points onward for within-day timing


def test_tool_description_names_what_it_is_not_for():
    text = _GET_PANCHANGAM_TOOL.description.lower()
    assert "horoscope" in text or "birth chart" in text
    assert "not for" in text


# --- get_panchangam handler --------------------------------------------------


def _call(args):
    return _handle_get_panchangam(FakePanchangamProvider(), args)


def test_handler_returns_json_safe_dict():
    import json

    out = _call({"date": "2026-09-06", "lat": 3.14111, "lon": 101.68639,
                 "tz": "Asia/Kuala_Lumpur"})
    json.dumps(out)  # must not raise
    assert out["date"] == "2026-09-06"
    assert out["weekday"] == "Raviwara"
    assert out["location"]["timezone"] == "Asia/Kuala_Lumpur"


def test_handler_emits_tz_aware_iso_strings():
    out = _call({"date": "2026-09-06", "lat": 3.14111, "lon": 101.68639,
                 "tz": "Asia/Kuala_Lumpur"})
    assert out["sunrise"] == "2026-09-06T07:07:00+08:00"
    for anga in ("tithi", "nakshatra", "yoga", "karana"):
        for span in out[anga]:
            assert span["starts"].endswith("+08:00")
            assert span["ends"].endswith("+08:00")
            assert set(span) == {"name", "number", "starts", "ends"}


def test_handler_tithi_matches_fixture():
    out = _call({"date": "2026-09-06", "lat": 3.14111, "lon": 101.68639,
                 "tz": "Asia/Kuala_Lumpur"})
    assert [t["name"] for t in out["tithi"]] == ["Krishna Dashami", "Krishna Ekadashi"]
    assert out["tithi"][0]["number"] == 25


@pytest.mark.parametrize(
    "args, needle",
    [
        ({"date": "6 Sept 2026", "lat": 3.14, "lon": 101.68, "tz": "Asia/Kuala_Lumpur"},
         "2026-09-06"),
        ({"date": "2026-09-06", "lat": 200, "lon": 101.68, "tz": "Asia/Kuala_Lumpur"},
         "-90 and 90"),
        ({"date": "2026-09-06", "lat": 3.14, "lon": 101.68, "tz": "Narnia/Cair_Paravel"},
         "not a known zone"),
    ],
)
def test_handler_raises_requesterror_with_actionable_text(args, needle):
    with pytest.raises(RequestError) as exc:
        _call(args)
    assert needle in str(exc.value)


def test_handler_unknown_date_propagates_missing_fixture():
    with pytest.raises(MissingFixtureError):
        _call({"date": "2025-01-01", "lat": 3.14111, "lon": 101.68639,
               "tz": "Asia/Kuala_Lumpur"})


# --- build_server ----------------------------------------------------------


def test_build_server_registers_get_panchangam():
    import asyncio

    from mcp.types import ListToolsRequest

    server = build_server(FakePanchangamProvider())
    handler = server.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest(method="tools/list")))
    tools = result.root.tools
    assert [t.name for t in tools] == ["get_panchangam"]
