# ESP32-S3 port: plan for the calculation core

Status: **plan only, no C written.** Everything below is derived from the code at
`f08b49d` (`src/panchangam/{ephemeris,angas,muhurta,lagna}.py` and `hora/engine.py`). Numbers marked
*estimate* are not measured; section 5 says how to measure them.

Scope note: this maps `ephemeris`, `angas`, `muhurta`, `lagna` and the pure
`hora/engine.py`. The `personal/` package (delivery, formatting, its own
`muhurta.py`) and the scoring tables in `hora/engine.py` are not analysed here.
Horas and lagna have golden data.

## 1. Function map

Legend: **P** pure math (port as is) · **S** Swiss Ephemeris call (replace) ·
**I** I/O, datetime or formatting (do not port; the C side works on JD doubles).

### `ephemeris.py`

| Function | Class | Notes |
|---|---|---|
| `configure`, `_ensure_configured` | S | `set_sid_mode`; C bakes Lahiri in at compile time |
| `_julian_day_ut` | I | tz-aware datetime to JD. C takes JD directly |
| `_utc_from_jd` | I | `revjul` plus datetime; formatting only |
| `ayanamsa_degrees` | S | `get_ayanamsa_ut`; replace with a fitted polynomial (section 4) |
| `_calc`, `graha_longitude`, `graha_speed` | S | `calc_ut` |
| `graha_longitude(KETU)` | P | Rahu + 180 |
| `is_retrograde` | P | speed < 0 |
| `sun_longitude`, `moon_longitude` | S | thin wrappers |
| `elongation` | P | `(moon - sun) mod 360` |
| `paksha` | P | elongation < 180 |
| `_sun_event`, `sunrise`, `sunset` | S + I | `rise_trans`; the whole function must be reimplemented |
| `_signed_delta` | P | wrap to (-180, 180] |
| `find_crossing` | P | bisection; takes a callback `fn(datetime)`, C needs an enum instead |
| `Graha`, `Ayanamsa`, `Paksha`, `CircumpolarError`, `NaiveDatetimeError` | I | enums and exceptions; C uses `enum` and return codes |

### `angas.py`

| Function | Class | Notes |
|---|---|---|
| `_tithi_name`, `_karana_name` | P | integer index maths, `(n-2) % 7`, fixed karana table |
| name tables (`_NAKSHATRA_NAMES`, `_YOGA_NAMES`, ...) | P | `const char *const[]` in flash |
| `_yoga_sum` | P | `(sun + moon) mod 360` |
| `tithi`, `nakshatra`, `yoga`, `karana` | P | one-liners over `_angam_spans` |
| `vara` | P + S | index is `isoweekday % 7 + 1` (pure); its start and end are sunrises (S) |
| `_angam_spans` | P | the core loop: floor-divide angle by step, find previous boundary in the 30 h before sunrise, then walk forward. Uses `timedelta` and callbacks, both need reshaping |
| `DEGREES_PER_*`, `*_COUNT` | P | constants |

### `muhurta.py`

| Function | Class | Notes |
|---|---|---|
| `_partition` | P | n equal divisions; C does it in JD with exact endpoints |
| `_weekday_part` | P | table lookup by `isoweekday % 7` |
| `_eighth`, `rahu_kalam`, `yamaganda`, `gulika` | P | given sunrise and sunset, integer table lookups |
| `abhijit`, `durmuhurtam`, `choghadiya` | P | same; `durmuhurtam` needs next sunrise |
| `_daylight_span` | S | two `sunrise`/`sunset` calls; the only S in this file |
| `_choghadiya_day_start` | P | `(3 * weekday) % 7` |
| tables (`RAHU_KALAM_PART`, `_DURMUHURTAM`, ...) | P | `const uint8_t[]` |

`muhurta.py` is pure once sunrise, sunset and next sunrise are supplied. That makes
it the easiest first C port and the one to test first.

### `hora/engine.py`, `lagna.py`

| Function | Class | Notes |
|---|---|---|
| `engine.hora_lord` | P | lord of hora 1..24 by table lookup, integer maths |
| `HORA_SEQUENCE`, `WEEKDAY_LORD` | P | `const` tables |
| hora slot times | P + S | `sunrise + (n - 1)` h, built in `server.py`; only sunrise is S |
| `lagna.lagna` | P + S | bisection over the ascendant, 6 h bracket |
| `ephemeris.ascendant` | S | `houses_ex`; C needs sidereal time, obliquity and the ascendant formula |

### `server.py`, `types.py`

All I/O (MCP, JSON, HTTP, ISO strings, tz lookup). Not ported. The dataclasses map
to the structs in section 3.

## 2. Swiss Ephemeris calls and flags actually used

| Call | Arguments | Used for |
|---|---|---|
| `swe.set_sid_mode(SIDM_LAHIRI or SIDM_RAMAN, 0, 0)` | t0 and ayan_t0 are 0 | ayanamsa selection (Lahiri is the default) |
| `swe.calc_ut(jd, body, FLG_MOSEPH \| FLG_SIDEREAL \| FLG_SPEED)` | bodies `SUN`, `MOON`, `MERCURY`, `VENUS`, `MARS`, `JUPITER`, `SATURN`, `MEAN_NODE` | longitude and longitude speed. Ketu is derived, not calculated |
| `swe.get_ayanamsa_ut(jd)` | none | `ayanamsa_degrees` |
| `swe.rise_trans(jd, SUN, CALC_RISE or CALC_SET, (lon, lat, elev), 0.0, 0.0, FLG_MOSEPH)` | pressure 0 and temperature 0 (Swiss then uses its standard atmosphere) | sunrise, sunset. No `BIT_HINDU_RISING`, so upper limb plus refraction |
| `swe.julday(y, m, d, hour, GREG_CAL)` | | datetime to JD |
| `swe.revjul(jd, GREG_CAL)` | | JD to datetime |
| `swe.houses_ex(jd, lat, lon, b"P", FLG_SIDEREAL)` | `ascmc[0]` is the ascendant | lagna; the house system is irrelevant to the ascendant |

Not used anywhere: `FLG_TRUEPOS`,
`FLG_NONUT`, other ayanamsas, other nodes, `swe.deltat`. `calc_ut` adds ΔT
internally, so the C port has to supply its own (section 4).

**What the five angas and muhurta actually need:** Sun and Moon longitude, the
ayanamsa, ΔT and sunrise/sunset. The other five grahas and the mean node are only
exposed through the `ephemeris` API; no anga or muhurta code calls them. A first
port needs only the Sun and Moon (plus the mean node, which is a simple polynomial
if wanted). Personal gochara cards, when they exist, will need the other grahas.

## 3. Proposed C layout

Constraints: fixed arrays, no `malloc`, no I/O in the core, `double` for JD and
angles (the S3 has no double-precision FPU, so doubles are software-emulated; the
work below is small enough for that to be fine), integer maths for indices.

```
core/
  pg_types.h      structs and constants
  pg_tables.h/.c  const name and weekday tables (flash)
  pg_ephem.h/.c   Sun, Moon, ayanamsa, delta-T           (replaces S calls)
  pg_rise.h/.c    sunrise, sunset                         (replaces rise_trans)
  pg_cross.h/.c   angle enum, signed delta, find_crossing
  pg_angas.h/.c   tithi, nakshatra, yoga, karana, vara
  pg_muhurta.h/.c partition, rahu/yama/gulika, abhijit, durmuhurtam, choghadiya
  pg_hora.h/.c    24 horas from sunrise
  pg_lagna.h/.c   rasi-lagna windows (needs sidereal time, obliquity, ayanamsa)
```

`pg_types.h`

```c
#define PG_MAX_ANGA_SPANS 6      /* max seen in 30 days of golden data: 4 (karana) */

typedef struct {
    double lat_deg, lon_deg, elev_m;
    int32_t utc_offset_s;        /* fixed offset, e.g. 28800; no tz database on device */
} pg_place_t;

typedef struct {
    uint8_t index;               /* 1-based, as in the Python types */
    double  start_jd, end_jd;    /* UT Julian Day */
} pg_span_t;                     /* name comes from a table lookup by index */

typedef struct { uint8_t count; pg_span_t s[PG_MAX_ANGA_SPANS]; } pg_span_list_t;

typedef struct { double start_jd, end_jd; uint8_t auspicious; } pg_period_t;

typedef enum { PG_OK = 0, PG_ERR_CIRCUMPOLAR, PG_ERR_BRACKET, PG_ERR_OVERFLOW } pg_status_t;
```

`pg_ephem.h`

```c
double pg_delta_t_days(double jd_ut);            /* TT - UT; see section 4 */
double pg_ayanamsa_lahiri(double jd_ut);         /* degrees */
double pg_sun_lon_sid(double jd_ut);             /* [0, 360) */
double pg_moon_lon_sid(double jd_ut);
double pg_rahu_lon_sid(double jd_ut);            /* mean node; Ketu = +180 */
void   pg_sun_eq(double jd_ut, double *ra_deg, double *dec_deg, double *dist_au); /* for pg_rise */
```

`pg_cross.h`

```c
typedef enum { PG_ANGLE_MOON, PG_ANGLE_ELONG, PG_ANGLE_YOGA_SUM } pg_angle_t;

double pg_angle(pg_angle_t a, double jd_ut);
double pg_signed_delta(double angle, double base);
pg_status_t pg_find_crossing(pg_angle_t a, double target_deg,
                             double lo_jd, double hi_jd, double tol_days,
                             double *out_jd);
```

The callback in `find_crossing` becomes the `pg_angle_t` enum, which removes the
function pointer and keeps the three angles in one switch.

`pg_rise.h`

```c
pg_status_t pg_sunrise(double day_start_ut_jd, const pg_place_t *p, double *out_jd);
pg_status_t pg_sunset (double day_start_ut_jd, const pg_place_t *p, double *out_jd);
```

`pg_angas.h`

```c
pg_status_t pg_tithi    (double sunrise_jd, double next_sunrise_jd, pg_span_list_t *out);
pg_status_t pg_nakshatra(double sunrise_jd, double next_sunrise_jd, pg_span_list_t *out);
pg_status_t pg_yoga     (double sunrise_jd, double next_sunrise_jd, pg_span_list_t *out);
pg_status_t pg_karana   (double sunrise_jd, double next_sunrise_jd, pg_span_list_t *out);
uint8_t     pg_vara_index(int iso_weekday);                 /* 1..7, Ravivara = 1 */
const char *pg_tithi_name(uint8_t n);  /* etc. for nakshatra, yoga, karana, vara */
```

`pg_muhurta.h` (all take `sunrise_jd`, `sunset_jd`, `next_sunrise_jd`, `iso_weekday`)

```c
void    pg_partition(double start_jd, double end_jd, int n, double *bounds /* n+1 */);
void    pg_rahu_kalam(...,  pg_period_t *out);   /* likewise yamaganda, gulika, abhijit */
uint8_t pg_durmuhurtam(..., pg_period_t out[2]); /* returns count */
void    pg_choghadiya(...,  pg_span_t out[16]);  /* + 16 name indices */
```

`pg_hora.h` (mirrors `hora.engine.hora_lord`; rule from CLAUDE.md)

```c
/* hora 1..24, each 60 min from sunrise; hora 1 lord = weekday lord;
   order Sun, Venus, Mercury, Moon, Saturn, Jupiter, Mars */
uint8_t pg_hora_lord(int iso_weekday, int hora_1based);
```

Design notes:
- The caller (firmware glue, not part of the core) owns time zones: it converts
  local dates to `day_start_ut_jd` with the fixed offset in `pg_place_t`, and
  formats "HH:MM". The core never sees a date string.
- The Python `end == next span's start` invariant carries over and is worth a test.
- Total per-day state is a few hundred bytes: four `pg_span_list_t` (~ 6 × 24 B
  each) plus 16 choghadiya spans. RAM is not the constraint.

## 4. Flash, RAM and accuracy

### What "fits" means here

The S3 module usually ships with 8 or 16 MB flash and 512 KB SRAM (some with PSRAM).
Per-day core state is under about 2 KB, so **RAM is a non-issue**; the question is
flash for the series tables and CPU time.

CPU: one crossing is a bisection to 1 s tolerance over up to 30 h, about 17 Sun +
Moon evaluations. A full day is roughly 25 crossings, about 450 evaluations, plus
a handful for sunrise and sunset. Even at a millisecond per software-double
evaluation that is well under a second per day. *(estimate; measure on target.)*

### Can `SEFLG_MOSEPH` fit?

*Estimate, not measured.* The Moshier code is `swemmoon.c` (Moon) and `swemplan.c`
plus `swemptab.h` (planets and Earth/Sun). They are compiled-in tables, with no data
files, which is why the Python service uses it. My expectation:

- Moshier Sun + Moon only (the current need): tens of KB of tables plus code.
  Fits trivially in 8 MB flash.
- Full Moshier for all grahas: low hundreds of KB. Still fits in 8 MB flash.

Neither number is measured, so I would not rely on it. Measure it (section 5)
before choosing.

Two things flash size does not settle:
1. **Porting effort.** Extracting only Sun/Moon/Earth from the Swiss code, without
   dragging in the rest of the library, is real work. Alternative: implement Meeus
   Ch. 47 (Moon) and a Sun series directly, and validate against the golden data.
2. **Licence.** Swiss Ephemeris is dual AGPL/commercial. Copying its Moshier tables
   into firmware you distribute is a licensing decision for you; I have not assessed it.

### Accuracy vs time, what matters

Angular error to time error uses the body's rate. Rates are from the daily motions;
they are arithmetic, not measured:

| Quantity | Rate | 1 arcmin (1') of error is about |
|---|---|---|
| Moon longitude (nakshatra) | about 0.55°/h (varies about 0.49–0.64) | 1.8 min |
| Elongation (tithi, karana) | about 0.5°/h | 2 min |
| Sun + Moon (yoga) | about 0.59°/h | 1.7 min |
| Sun longitude | about 0.04°/h | about 24 min (but Sun error enters tithi and yoga divided by the faster Moon rate, see below) |
| Ascendant (lagna) | about 1° per 4 min of time | 4 s |

So the practical target: the printed panchangam reports to the minute, so to agree
within ±1 min the **Moon needs about 0.5' or better**. That is:
- **Full Moshier / Meeus Ch. 47 series (tens of arcseconds or better):** comfortably
  inside the target. Per the Swiss Ephemeris docs Moshier is at the arcsecond level
  for the Sun and Moon *(verify the exact figure in the SE docs)*; 10" is 0.17', about
  0.3 min.
- **Truncated Moon series (about 6 major terms):** errors on the order of 0.1–0.3°,
  meaning 10' or more, so tens of minutes on nakshatra boundaries. **Not acceptable.**
  Moon term count is the main accuracy knob.
- **Sun:** an error of 0.6' (the Meeus Ch. 25 "low accuracy" 0.01° Sun) shifts a tithi
  boundary by about 0.6' / (0.5°/h) ≈ 1.2 min, because elongation depends on it.
  Use a Sun series good to a few arcseconds instead.
- **Ayanamsa:** enters nakshatra, yoga and lagna but not tithi or karana (the
  difference cancels it). A 1' ayanamsa error is 1.8 min on nakshatra. Precession is
  about 50.3"/year, so fit a polynomial to the golden `ayanamsa_deg` values and
  check that the residual stays under about 0.1'.
- **ΔT: must not be omitted.** `calc_ut` adds ΔT (roughly a minute in 2026, *value
  to be checked against the Swiss result*). At 0.55'/min for the Moon, ignoring a
  ΔT of about 69 s would be a 0.6' error, about 1.2 min on a nakshatra boundary. Use
  a short polynomial for ΔT over the years you support, or a small lookup table.
- **Sunrise/sunset:** needs the Sun's RA/declination/distance (semidiameter) and
  the standard refraction. The Sun's position error of 1' is about 4 s of time.
  The upper-limb-plus-refraction convention (CLAUDE.md) must be reproduced exactly;
  the largest risk is the rise/set solver and refraction model, not the ephemeris.
  Validate against golden sunrise/sunset.
- **Lagna** (when added) is far less sensitive than nakshatra: 1' is about 4 s.
  Needs sidereal time, obliquity and latitude but no ephemeris, so it has no ephemeris-
  driven flash cost. Its accuracy is dominated by ayanamsa and ΔT/UT1.

**Recommendation:** try a Sun + Moon implementation with Meeus/Moshier-quality
series, ΔT polynomial, fitted ayanamsa, and a reimplemented rise/set. Accept it
only if the golden comparison passes the tolerances below. Fall back to trimming
terms only if flash forces it, and re-measure.

Suggested acceptance tolerances (proposal, you decide): anga boundaries within
±30 s, sunrise/sunset within ±10 s, longitudes within 0.5' (0.01°). These are
looser than the ephemeris is likely to deliver, so they leave room.

## 5. Measuring, and the golden data

Measure flash before deciding: compile the candidate ephemeris sources for
`xtensa-esp32s3-elf` and run `xtensa-esp32s3-elf-size -A` on the objects. A host
`size -A` on `swemmoon.o` and `swemplan.o` gives an upper-bound proxy.

Golden data: `scripts/dump_golden.py` dumps N days (default 30) to JSON, using the
public Python API only:

```
PYTHONPATH=src .venv/bin/python scripts/dump_golden.py \
    --start 2026-09-01 --days 30 --out tests/fixtures/golden_petaling_jaya.json
```

Per day: sunrise, sunset, next sunrise; vara; tithi, nakshatra, yoga and karana
spans; Rahu kalam, Yamaganda, Gulika, Abhijit, Durmuhurtam; 16 choghadiya; 24 horas;
the rasi-lagna windows; and raw sidereal longitude and speed for all nine grahas
plus the ayanamsa and ascendant at sunrise (the layer the C ephemeris replaces). Every instant is stored as a local ISO string and
as `jd_ut`. Place: Petaling Jaya, Lahiri, Moshier.

The script's output is not committed; regenerate it where you need it.

## 6. Suggested order of work

1. `pg_muhurta` and the tables: pure, testable against golden with sunrise/sunset
   fed in from the JSON. This proves the layout with no ephemeris at all.
2. `pg_cross` + `pg_angas`, again fed `sunrise`, plus a stub angle function that
   interpolates golden longitudes, to check the boundary logic alone.
3. `pg_ephem` (Sun, Moon, ayanamsa, ΔT): compare longitudes to golden.
4. `pg_rise`: compare sunrise/sunset to golden.
5. Measure flash and time on the S3; decide about trimming.
6. `pg_hora` once a Python reference exists.
