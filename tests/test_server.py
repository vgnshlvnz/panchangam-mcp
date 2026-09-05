"""Tests for the MCP panchangam server.

Layout:
  - argument parsing / validation / schema / serialization -- pure, no backend
  - error mapping (_invoke) -- stub providers that raise
  - transports & entry point -- stub provider, nothing computed
  - real Swiss Ephemeris backend (load_provider) -- @requires_swisseph, asserts
    real computed data flows through the tools correctly

There is no fake provider. Anything that needs panchangam values uses the real
backend; anything that does not, does not construct one.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime, timedelta, timezone

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
    _iso,
    _serialize_day,
    _serialize_period,
    _serialize_span,
    build_http_app,
    build_place,
    build_server,
    load_provider,
    main,
    parse_query_date,
)
from panchangam.types import AngaSpan, DayPanchangam, NamedPeriod, Place

requires_swisseph = pytest.mark.skipif(
    importlib.util.find_spec("swisseph") is None,
    reason="swisseph not installed -- needs the uv-managed Python 3.12 venv",
)

KL_ARGS = {"date": "2026-09-06", "lat": 3.14111, "lon": 101.68639,
           "tz": "Asia/Kuala_Lumpur"}
_TZ8 = timezone(timedelta(hours=8))


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
    with pytest.raises(RequestError):
        build_place(0.0, 0.0, "asia/kuala_lumpur")


# --- tool schema & descriptions ---------------------------------------------


def test_tool_advertises_the_four_arguments():
    schema = _GET_PANCHANGAM_TOOL.inputSchema
    assert schema["required"] == ["date", "lat", "lon", "tz"]
    assert schema["properties"]["lat"]["type"] == "number"
    assert schema["properties"]["tz"]["type"] == "string"


def test_panchangam_description_is_jargon_light():
    text = _GET_PANCHANGAM_TOOL.description.lower()
    # Stands on its own for a caller who has never heard "tithi".
    assert "lunar day" in text
    assert "new moon" in text and "full moon" in text
    assert "sunrise" in text and "sunset" in text
    assert "get_muhurta" in text


def test_panchangam_description_names_what_it_is_not_for():
    text = _GET_PANCHANGAM_TOOL.description.lower()
    assert "horoscope" in text or "birth chart" in text
    assert "not for" in text


def test_muhurta_tool_shares_the_input_schema():
    assert _GET_MUHURTA_TOOL.inputSchema == _GET_PANCHANGAM_TOOL.inputSchema
    assert _GET_MUHURTA_TOOL.inputSchema["required"] == ["date", "lat", "lon", "tz"]


def test_muhurta_description_is_jargon_light_and_cross_links():
    text = _GET_MUHURTA_TOOL.description.lower()
    assert "auspicious" in text and "inauspicious" in text
    assert "rahu kalam" in text
    assert "within" in text  # distinguishes it from get_panchangam
    assert "get_panchangam" in text


# --- serialization (hand-built value types, no backend) --------------------


def _span(index, name, start, end):
    return AngaSpan(index=index, name=name, start=start, end=end)


def test_iso_truncates_sub_second_digits():
    assert _iso(datetime(2026, 9, 6, 7, 6, 49, 123456, tzinfo=_TZ8)) == (
        "2026-09-06T07:06:49+08:00"
    )


def test_serialize_span_shape_and_precision():
    out = _serialize_span(
        _span(25, "Krishna Dashami",
              datetime(2026, 9, 6, 0, 24, 11, 500000, tzinfo=_TZ8),
              datetime(2026, 9, 6, 21, 59, 43, 900000, tzinfo=_TZ8))
    )
    assert out == {
        "name": "Krishna Dashami",
        "number": 25,
        "starts": "2026-09-06T00:24:11+08:00",
        "ends": "2026-09-06T21:59:43+08:00",
    }


def test_serialize_period_shape_and_precision():
    out = _serialize_period(
        NamedPeriod("Rahu Kalam",
                    datetime(2026, 9, 6, 17, 45, 19, 930352, tzinfo=_TZ8),
                    datetime(2026, 9, 6, 19, 16, 32, tzinfo=_TZ8),
                    auspicious=False)
    )
    assert out == {
        "name": "Rahu Kalam",
        "auspicious": False,
        "starts": "2026-09-06T17:45:19+08:00",
        "ends": "2026-09-06T19:16:32+08:00",
    }


def test_serialize_day_is_json_safe_and_complete():
    place = Place("Kuala Lumpur", 3.14111, 101.68639, "Asia/Kuala_Lumpur", 56.0)
    noon = datetime(2026, 9, 6, 12, 0, tzinfo=_TZ8)
    span = _span(1, "X", noon, noon + timedelta(hours=1))
    day = DayPanchangam(
        place=place, date=date(2026, 9, 6),
        sunrise=datetime(2026, 9, 6, 7, 6, 49, tzinfo=_TZ8),
        sunset=datetime(2026, 9, 6, 19, 16, 32, tzinfo=_TZ8),
        vaara="Ravivara",
        tithi=(span,), nakshatra=(span,), yoga=(span,), karana=(span,),
    )
    out = _serialize_day(day)
    json.dumps(out)  # must not raise
    assert out["date"] == "2026-09-06"
    assert out["weekday"] == "Ravivara"
    assert out["sunrise"] == "2026-09-06T07:06:49+08:00"
    assert out["location"] == {
        "name": "Kuala Lumpur", "latitude": 3.14111,
        "longitude": 101.68639, "timezone": "Asia/Kuala_Lumpur",
    }
    assert set(out) == {"location", "date", "weekday", "sunrise", "sunset",
                        "tithi", "nakshatra", "yoga", "karana"}


# --- input validation through the handler (provider never reached) ---------


class _NullProvider:
    """A provider that fails loudly if a handler ever calls it -- for tests
    where validation must reject the request first."""

    def day_panchangam(self, place, day):
        raise AssertionError("provider reached despite invalid arguments")

    def named_periods(self, place, day):
        raise AssertionError("provider reached despite invalid arguments")


@pytest.mark.parametrize(
    "args, needle",
    [
        ({**KL_ARGS, "date": "6 Sept 2026"}, "2026-09-06"),
        ({**KL_ARGS, "lat": 200}, "-90 and 90"),
        ({**KL_ARGS, "tz": "Narnia/Cair_Paravel"}, "not a known zone"),
    ],
)
def test_panchangam_handler_validates_before_touching_provider(args, needle):
    with pytest.raises(RequestError) as exc:
        _handle_get_panchangam(_NullProvider(), args)
    assert needle in str(exc.value)


def test_muhurta_handler_validates_before_touching_provider():
    with pytest.raises(RequestError, match="not a known zone"):
        _handle_get_muhurta(_NullProvider(), {**KL_ARGS, "tz": "Somewhere/Nice"})


# --- error mapping (_invoke) -------------------------------------------------


class _BoomProvider:
    def __init__(self, exc):
        self._exc = exc

    def day_panchangam(self, place, day):
        raise self._exc

    def named_periods(self, place, day):
        raise self._exc


def test_invoke_maps_request_error_to_invalid_arguments():
    with pytest.raises(ToolError, match=r"^invalid arguments: lat must be between"):
        _invoke(_handle_get_panchangam, _NullProvider(), {**KL_ARGS, "lat": 999})


def test_invoke_maps_provider_error_to_cannot_compute():
    provider = _BoomProvider(ProviderError("no sunrise at this latitude on this date"))
    with pytest.raises(ToolError, match=r"^cannot compute: no sunrise"):
        _invoke(_handle_get_panchangam, provider, KL_ARGS)


def test_invoke_sanitizes_unexpected_error():
    provider = _BoomProvider(KeyError("secret_internal_field"))
    with pytest.raises(ToolError) as exc:
        _invoke(_handle_get_muhurta, provider, KL_ARGS)
    assert "internal error" in str(exc.value)
    assert "secret_internal_field" not in str(exc.value)


# --- transports & entry point (nothing computed) --------------------------


def _roundtrip(provider, tool: str, arguments: dict):
    """Call a tool through a real in-memory MCP client session."""
    import asyncio

    from mcp.shared.memory import create_connected_server_and_client_session

    async def go():
        async with create_connected_server_and_client_session(
            build_server(provider)
        ) as client:
            await client.initialize()
            listed = await client.list_tools()
            result = await client.call_tool(tool, arguments)
            return [t.name for t in listed.tools], result

    names, result = asyncio.run(go())
    payload = None if result.isError else json.loads(result.content[0].text)
    return names, result, payload


def test_list_tools_returns_both_tools():
    names, _result, _payload = _roundtrip(_NullProvider(), "get_panchangam",
                                          {**KL_ARGS, "lat": 999})
    assert names == ["get_panchangam", "get_muhurta"]


def test_call_tool_bad_input_is_an_error_result_not_a_crash():
    _names, result, _payload = _roundtrip(_NullProvider(), "get_panchangam",
                                          {**KL_ARGS, "lat": 999})
    assert result.isError is True
    assert "-90 and 90" in result.content[0].text


def test_call_tool_unknown_name_lists_available():
    _names, result, _payload = _roundtrip(_NullProvider(), "get_moon_phase", KL_ARGS)
    assert result.isError is True
    text = result.content[0].text
    assert "unknown tool" in text
    assert "get_panchangam" in text and "get_muhurta" in text


def test_build_http_app_mounts_mcp_endpoint():
    app = build_http_app(_NullProvider())
    mounts = [r for r in app.routes if getattr(r, "path", None) == HTTP_PATH]
    assert len(mounts) == 1


def test_main_rejects_unknown_transport():
    with pytest.raises(SystemExit):
        main(["--transport", "carrier-pigeon"])


def test_main_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "--transport" in capsys.readouterr().out


def test_main_dispatches_to_the_chosen_transport(monkeypatch):
    calls = []
    monkeypatch.setattr("panchangam.server.load_provider", lambda: "PROVIDER")
    monkeypatch.setattr("panchangam.server.anyio.run",
                        lambda fn, p: calls.append(("stdio", fn.__name__, p)))
    monkeypatch.setattr("panchangam.server.run_http",
                        lambda p, host, port: calls.append(("http", p, host, port)))

    main(["--transport", "stdio"])
    main(["--transport", "http", "--port", "9999"])

    assert calls == [
        ("stdio", "run_stdio", "PROVIDER"),
        ("http", "PROVIDER", "127.0.0.1", 9999),
    ]


# --- real Swiss Ephemeris backend (load_provider) ------------------------


@pytest.fixture(scope="module")
def real():
    return load_provider()


@requires_swisseph
def test_load_provider_satisfies_the_protocol(real):
    assert callable(real.day_panchangam)
    assert callable(real.named_periods)


@requires_swisseph
def test_real_get_panchangam_flows_through_the_tool(real):
    _names, result, payload = _roundtrip(real, "get_panchangam", KL_ARGS)
    assert result.isError is False

    assert payload["date"] == "2026-09-06"
    assert payload["location"]["timezone"] == "Asia/Kuala_Lumpur"
    assert payload["weekday"] == "Ravivara"  # 2026-09-06 is a Sunday
    # anchors, checked against drikpanchang.com to the minute-ish
    assert payload["sunrise"].startswith("2026-09-06T07:0")
    assert payload["tithi"][0]["name"] == "Krishna Dashami"
    assert payload["tithi"][0]["ends"].startswith("2026-09-06T21:5")

    for anga in ("tithi", "nakshatra", "yoga", "karana"):
        spans = payload[anga]
        assert spans, anga
        for span in spans:
            assert set(span) == {"name", "number", "starts", "ends"}
            assert span["starts"].endswith("+08:00")
            assert "." not in span["starts"]  # second precision
        for earlier, later in zip(spans, spans[1:]):
            assert earlier["ends"] == later["starts"]  # contiguous, ordered


@requires_swisseph
def test_real_get_muhurta_flows_through_the_tool(real):
    _names, result, payload = _roundtrip(real, "get_muhurta", KL_ARGS)
    assert result.isError is False

    by_name = {p["name"]: p for p in payload["periods"]}
    assert {"Rahu Kalam", "Yamaganda", "Gulika Kalam", "Abhijit Muhurta"} <= set(by_name)
    assert by_name["Rahu Kalam"]["auspicious"] is False
    assert by_name["Abhijit Muhurta"]["auspicious"] is True
    assert by_name["Rahu Kalam"]["starts"].startswith("2026-09-06T17:4")  # ~17:45

    for period in payload["periods"]:
        assert set(period) == {"name", "auspicious", "starts", "ends"}
        assert period["starts"].endswith("+08:00") and "." not in period["starts"]
        assert period["starts"] < period["ends"]


@requires_swisseph
def test_real_backend_reports_circumpolar_as_cannot_compute(real):
    # Longyearbyen in polar night: the Sun never rises -> ProviderError.
    _names, result, _payload = _roundtrip(
        real, "get_panchangam",
        {"date": "2026-12-21", "lat": 78.22, "lon": 15.65,
         "tz": "Arctic/Longyearbyen"},
    )
    assert result.isError is True
    assert result.content[0].text.startswith("cannot compute:")
