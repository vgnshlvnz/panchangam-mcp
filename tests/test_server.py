"""Tests for the MCP panchangam server.

This file grows with the lane. First slice: input validation -- every bad
argument must produce a :class:`RequestError` a model can act on.
"""

from __future__ import annotations

from datetime import date

import pytest

from panchangam.server import RequestError, build_place, parse_query_date
from panchangam.types import Place


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
