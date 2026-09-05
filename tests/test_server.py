"""Tests for the MCP panchangam server.

This file grows with the lane. First slice: input validation -- every bad
argument must produce a :class:`RequestError` a model can act on.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from panchangam.server import (
    HTTP_PATH,
    ProviderError,
    RequestError,
    ToolError,
    _GET_MUHURTA_TOOL,
    _GET_PANCHANGAM_TOOL,
    _handle_get_muhurta,
    _handle_get_panchangam,
    _invoke,
    build_http_app,
    build_place,
    build_server,
    load_provider,
    main,
    parse_query_date,
)
from panchangam.types import AngaSpan, DayPanchangam, NamedPeriod, Place

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


def test_fake_named_periods_from_fixture(provider):
    periods = provider.named_periods(KL, KL_DAY)
    assert all(isinstance(p, NamedPeriod) for p in periods)
    by_name = {p.name: p for p in periods}
    assert by_name["Rahu Kalam"].auspicious is False
    assert by_name["Abhijit Muhurat"].auspicious is True
    assert by_name["Rahu Kalam"].start == datetime.fromisoformat(
        "2026-09-06T17:45:00+08:00"
    )
    for p in periods:
        assert p.start < p.end
        assert p.start.utcoffset().total_seconds() == 8 * 3600


def test_fake_named_periods_raises_for_unknown_day(provider):
    with pytest.raises(MissingFixtureError):
        provider.named_periods(KL, date(2026, 6, 1))


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


# --- get_muhurta ---------------------------------------------------------------


def test_muhurta_tool_shares_the_input_schema():
    assert _GET_MUHURTA_TOOL.inputSchema == _GET_PANCHANGAM_TOOL.inputSchema
    assert _GET_MUHURTA_TOOL.inputSchema["required"] == ["date", "lat", "lon", "tz"]


def test_muhurta_description_is_jargon_light_and_cross_links():
    text = _GET_MUHURTA_TOOL.description.lower()
    assert "auspicious" in text and "inauspicious" in text
    assert "rahu kalam" in text
    assert "within" in text  # distinguishes it from get_panchangam
    assert "get_panchangam" in text


def test_muhurta_handler_returns_json_safe_dict():
    import json

    out = _handle_get_muhurta(
        FakePanchangamProvider(),
        {"date": "2026-09-06", "lat": 3.14111, "lon": 101.68639,
         "tz": "Asia/Kuala_Lumpur"},
    )
    json.dumps(out)
    assert out["date"] == "2026-09-06"
    names = [p["name"] for p in out["periods"]]
    assert "Rahu Kalam" in names and "Abhijit Muhurat" in names
    for period in out["periods"]:
        assert set(period) == {"name", "auspicious", "starts", "ends"}
        assert period["starts"].endswith("+08:00")
        assert isinstance(period["auspicious"], bool)


def test_muhurta_handler_validates_input_like_panchangam():
    with pytest.raises(RequestError, match="not a known zone"):
        _handle_get_muhurta(
            FakePanchangamProvider(),
            {"date": "2026-09-06", "lat": 3.14, "lon": 101.68, "tz": "Somewhere/Nice"},
        )


# --- build_server ----------------------------------------------------------


def test_build_server_registers_get_panchangam():
    import asyncio

    from mcp.types import ListToolsRequest

    server = build_server(FakePanchangamProvider())
    handler = server.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest(method="tools/list")))
    tools = result.root.tools
    assert [t.name for t in tools] == ["get_panchangam", "get_muhurta"]


# --- transports & entry point ---------------------------------------------


def test_load_provider_is_not_wired_yet():
    with pytest.raises(RuntimeError, match="integration pending"):
        load_provider()


def test_main_rejects_unknown_transport():
    with pytest.raises(SystemExit):
        main(["--transport", "carrier-pigeon"])


def test_main_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "--transport" in capsys.readouterr().out


def test_main_stdio_fails_at_provider_not_transport(monkeypatch):
    # main() builds the provider before touching a transport, so today it stops
    # at load_provider() for either transport choice.
    with pytest.raises(RuntimeError, match="integration pending"):
        main(["--transport", "stdio"])


def test_build_http_app_mounts_mcp_endpoint():
    app = build_http_app(FakePanchangamProvider())
    mounts = [r for r in app.routes if getattr(r, "path", None) == HTTP_PATH]
    assert len(mounts) == 1


def _roundtrip(tool: str, arguments: dict):
    """Call a tool through a real in-memory MCP client session and return the
    parsed structured result."""
    import asyncio
    import json

    from mcp.shared.memory import create_connected_server_and_client_session

    async def go():
        server = build_server(FakePanchangamProvider())
        async with create_connected_server_and_client_session(server) as client:
            await client.initialize()
            listed = await client.list_tools()
            result = await client.call_tool(tool, arguments)
            return [t.name for t in listed.tools], result

    names, result = asyncio.run(go())
    payload = None if result.isError else json.loads(result.content[0].text)
    return names, result, payload


def test_get_panchangam_roundtrip_over_mcp_session():
    names, result, payload = _roundtrip(
        "get_panchangam",
        {"date": "2026-09-06", "lat": 3.14111, "lon": 101.68639,
         "tz": "Asia/Kuala_Lumpur"},
    )
    assert names == ["get_panchangam", "get_muhurta"]
    assert result.isError is False
    assert payload["weekday"] == "Raviwara"
    assert payload["sunrise"] == "2026-09-06T07:07:00+08:00"
    assert payload["tithi"][0]["name"] == "Krishna Dashami"


def test_get_panchangam_bad_input_is_an_error_result_not_a_crash():
    _names, result, _payload = _roundtrip(
        "get_panchangam",
        {"date": "2026-09-06", "lat": 999, "lon": 0, "tz": "Asia/Kuala_Lumpur"},
    )
    assert result.isError is True
    assert "-90 and 90" in result.content[0].text


# --- error mapping (_invoke) -------------------------------------------------


class _BoomProvider:
    """A provider whose methods all raise; the exception is configurable."""

    def __init__(self, exc):
        self._exc = exc

    def day_panchangam(self, place, day):
        raise self._exc

    def named_periods(self, place, day):
        raise self._exc


_GOOD_ARGS = {"date": "2026-09-06", "lat": 3.14111, "lon": 101.68639,
              "tz": "Asia/Kuala_Lumpur"}


def test_invoke_maps_request_error_to_invalid_arguments():
    with pytest.raises(ToolError, match=r"^invalid arguments: lat must be between"):
        _invoke(_handle_get_panchangam, FakePanchangamProvider(),
                {**_GOOD_ARGS, "lat": 999})


def test_invoke_maps_provider_error_to_cannot_compute():
    provider = _BoomProvider(ProviderError("no sunrise at this latitude on this date"))
    with pytest.raises(ToolError, match=r"^cannot compute: no sunrise"):
        _invoke(_handle_get_panchangam, provider, _GOOD_ARGS)


def test_invoke_sanitizes_unexpected_error():
    provider = _BoomProvider(KeyError("secret_internal_field"))
    with pytest.raises(ToolError) as exc:
        _invoke(_handle_get_muhurta, provider, _GOOD_ARGS)
    assert "internal error" in str(exc.value)
    assert "secret_internal_field" not in str(exc.value)


def test_invoke_passes_through_on_success():
    out = _invoke(_handle_get_panchangam, FakePanchangamProvider(), _GOOD_ARGS)
    assert out["date"] == "2026-09-06"


def test_call_tool_unknown_name_lists_available():
    _names, result, _payload = _roundtrip("get_moon_phase", _GOOD_ARGS)
    assert result.isError is True
    text = result.content[0].text
    assert "unknown tool" in text and "get_panchangam" in text and "get_muhurta" in text


def test_call_tool_missing_fixture_comes_back_as_cannot_compute():
    _names, result, _payload = _roundtrip(
        "get_panchangam", {**_GOOD_ARGS, "date": "2025-01-01"}
    )
    assert result.isError is True
    assert result.content[0].text.startswith("cannot compute:")


def test_get_muhurta_roundtrip_over_mcp_session():
    names, result, payload = _roundtrip(
        "get_muhurta",
        {"date": "2026-09-06", "lat": 3.14111, "lon": 101.68639,
         "tz": "Asia/Kuala_Lumpur"},
    )
    assert names == ["get_panchangam", "get_muhurta"]
    assert result.isError is False
    rahu = next(p for p in payload["periods"] if p["name"] == "Rahu Kalam")
    assert rahu["auspicious"] is False
    assert rahu["starts"] == "2026-09-06T17:45:00+08:00"
