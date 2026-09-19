"""Turn a DayResult into a short chat message (Slack mrkdwn and WhatsApp both use *bold*)."""
from .muhurta import NAKSHATRAS, NAKSHATRAS_TA, RASIS, RASIS_TA, TARAS, DayResult

L = {
    "en": {"moon": "Moon", "tara": "Tara", "chandra": "Chandra", "good": "Good windows",
               "none": "No strong window today — keep important starts for another day.",
               "avoid": "Avoid", "ashtama": "⚠️ *Chandrashtama*{until} — no new starts in that time.",
               "till": " till {t}", "house": " from your rasi", "lagna": "lagna",
               "kalam": {"Rahu kalam": "Rahu kalam", "Yamagandam": "Yamagandam", "Gulika": "Gulika"}},
    "ta": {"moon": "சந்திரன்", "tara": "தாரை", "chandra": "சந்திர பலம்", "good": "நல்ல நேரம்",
               "none": "இன்று சிறப்பான நேரம் இல்லை — முக்கிய காரியங்களை வேறு நாளில் வைக்கவும்.",
               "avoid": "தவிர்க்கவும்", "ashtama": "⚠️ *சந்திராஷ்டமம்*{until} — அந்த நேரத்தில் புதிய காரியம் வேண்டாம்.",
               "till": " {t} வரை", "house": "-ம் இடம்", "lagna": "லக்னம்",
               "kalam": {"Rahu kalam": "ராகு காலம்", "Yamagandam": "எமகண்டம்", "Gulika": "குளிகை"}},
}
ICON = {"good": "✅", "neutral": "➖", "mixed": "➖", "weak": "⚠️", "bad": "❌", "chandrashtama": "🚫"}


def _t(dt):
    return dt.strftime("%H:%M")


def _ordinal(n: int, lang: str) -> str:
    if lang == "ta":
        return str(n)
    suffix = "th" if 10 < n % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def render(r: DayResult, lang: str = "en", max_windows: int = 4) -> str:
    s = L[lang]
    nak = NAKSHATRAS_TA if lang == "ta" else NAKSHATRAS
    ras = RASIS_TA if lang == "ta" else RASIS
    tara_name = (lambda i: TARAS[i][1]) if lang == "ta" else (lambda i: TARAS[i][0])

    out = [f"🗓 *{r.day.strftime('%a %d %b %Y')}* · {r.person.name}",
           f"🌅 {_t(r.sunrise)}  🌇 {_t(r.sunset)}"]

    # moon segments that start before 22:00 local on the day
    cutoff = r.sunrise.replace(hour=22, minute=0)
    segs = [m for m in r.moon if m.start < cutoff]
    moon_line, tara_line, ch_line = [], [], []
    for i, m in enumerate(segs):
        until = "" if i == len(segs) - 1 else s['till'].format(t=_t(m.end))
        moon_line.append(f"{nak[m.nakshatra - 1]}/{ras[m.rasi - 1]}{until}")
        tara_line.append(f"{tara_name(m.tara)} {ICON[m.tara_verdict]}")
        ch_line.append(f"{_ordinal(m.chandra_house, lang)}{s['house']} {ICON[m.chandra_verdict]}")
    dedupe = lambda xs: [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    out.append(f"🌙 {s['moon']}: " + " → ".join(moon_line))
    out.append(f"⭐ {s['tara']}: " + " → ".join(dedupe(tara_line)))
    out.append(f"🌓 {s['chandra']}: " + " → ".join(dedupe(ch_line)))

    if r.chandrashtama:
        ash = [m for m in segs if m.chandra_verdict == "chandrashtama"]
        end = ash[-1].end
        until = f" ({s['till'].format(t=_t(end)).strip()})" if end < cutoff else ""
        out.append(s["ashtama"].format(until=until))

    out.append("")
    if r.good_windows:
        out.append(f"*{s['good']}:*")
        for span, lw, _ in r.good_windows[:max_windows]:
            extra = [n for n in lw.notes if n.startswith("benefics")]
            tail = f" · {extra[0].split(': ')[1]} ✨" if extra else ""
            out.append(f"• {_t(span.start)}–{_t(span.end)}  {ras[lw.rasi - 1]} {s['lagna']}{tail}")
    else:
        out.append(s["none"])

    k = " · ".join(f"{s['kalam'][name]} {_t(sp.start)}–{_t(sp.end)}" for name, sp in r.kalams.items())
    out.append(f"🚫 {s['avoid']}: {k}")
    return "\n".join(out)
