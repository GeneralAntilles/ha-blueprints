#!/usr/bin/env python3
"""Kitchen air event report: cooking PM2.5 events and how fast they clear.

Finds cooking events in the living-room AirGradient PM2.5 history (a rise of
10+ ug/m3 over the rolling 60-minute median, to at least 15), fits each
event's exponential decay from peak back to baseline, and reports what was
running at the time (AC compressor, exhaust fans, the kitchen-air automation).

Use it as a before/after yardstick: baseline on 2026-09-27 was 19 measurable events in
30 days (24 incl. ones spanning sensor gaps) with a median decay of 2.3/h
(half-life ~18 min), with the microwave
vent + Coway HEPA + normal AC cycling. Re-run after the MERV 13 cartridge and
after the RVF8 install. The recorder keeps 60 days of raw history, so run it
within two months of each change.

    python3 climate/kitchen-air-events.py            # last 30 days
    python3 climate/kitchen-air-events.py --days 14
    python3 climate/kitchen-air-events.py --since 2026-11-01

Reads HA_TOKEN and HA_IP (or HA_URL) from ../.env.
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
import os
import statistics as st
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PM = "sensor.airgradient_living_room_pm2_5"
NOX = "sensor.airgradient_living_room_nox_index"
AC = "sensor.ac_compressor_state"
FANS = ("switch.downstairs_bathroom_fan", "switch.laundry_room_fan")

RISE = 10.0  # ug/m3 above the rolling median to start an event
FLOOR = 15.0  # and at least this absolute level
END_MARGIN = 3.0  # event ends when back within this of its baseline
MAX_FILL = dt.timedelta(minutes=5)  # never forward-fill across a longer silence

Series = list[tuple[dt.datetime, str]]


@dataclass
class Event:
    start: dt.datetime
    base: float
    peak: float
    peak_at: dt.datetime
    end: dt.datetime
    decay_per_h: float | None
    ac_frac: float
    fan_frac: float
    nox_peak: float | None
    ongoing: bool = False


def load_env() -> tuple[str, str]:
    env: dict[str, str] = {}
    for line in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    base = f"http://{env['HA_IP']}:8123" if env.get("HA_IP") else env["HA_URL"]
    return base, env["HA_TOKEN"]


def fetch(base: str, token: str, start: dt.datetime, end: dt.datetime) -> dict[str, Series]:
    ids = ",".join((PM, NOX, AC) + FANS)
    url = (f"{base}/api/history/period/{start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
           f"?end_time={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
           f"&filter_entity_id={ids}&minimal_response&no_attributes")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = json.load(r)
    out: dict[str, Series] = {}
    for series in raw:
        eid = series[0]["entity_id"]
        out[eid] = [(dt.datetime.fromisoformat(p["last_changed"]).astimezone(), p["state"])
                    for p in series]
    return out


def numeric(s: Series) -> list[tuple[dt.datetime, float]]:
    out = []
    for t, v in s:
        try:
            out.append((t, float(v)))
        except ValueError:
            pass
    return out


def fraction(s: Series, a: dt.datetime, b: dt.datetime, on: set[str]) -> float:
    """Share of [a, b] that series s spent in one of the `on` states."""
    if not s or b <= a:
        return 0.0
    total = 0.0
    for k, (t, v) in enumerate(s):
        seg_end = s[k + 1][0] if k + 1 < len(s) else b
        lo, hi = max(t, a), min(seg_end, b)
        if v in on and hi > lo:
            total += (hi - lo).total_seconds()
    return total / (b - a).total_seconds()


def minute_grid(raw: Series) -> list[tuple[dt.datetime, float | None]]:
    """One value per minute; None while unavailable or after MAX_FILL of silence."""
    t = raw[0][0].replace(second=0, microsecond=0)
    grid: list[tuple[dt.datetime, float | None]] = []
    i, cur, cur_t = 0, None, raw[0][0]
    while t <= raw[-1][0]:
        while i < len(raw) and raw[i][0] <= t:
            try:
                cur = float(raw[i][1])
            except ValueError:
                cur = None
            cur_t, i = raw[i][0], i + 1
        grid.append((t, cur if cur is not None and t - cur_t <= MAX_FILL else None))
        t += dt.timedelta(minutes=1)
    return grid


def decay_rate(points: list[tuple[dt.datetime, float]]) -> float | None:
    """Least-squares slope of ln(excess) over hours; None if too few points."""
    if len(points) < 8:
        return None
    xs = [(t - points[0][0]).total_seconds() / 3600 for t, _ in points]
    ys = [math.log(v) for _, v in points]
    mx, my = st.mean(xs), st.mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return None if den == 0 else -sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def find_events(h: dict[str, Series]) -> list[Event]:
    raw = h.get(PM, [])
    if len(numeric(raw)) < 10:
        return []
    grid = minute_grid(raw)
    nox = numeric(h.get(NOX, []))
    fan_series = [h.get(f, []) for f in FANS]
    events: list[Event] = []
    cur: dict | None = None
    for n, (t, x) in enumerate(grid):
        if x is None:  # data gap: an event spanning it can't be measured
            cur = None
            continue
        window = [v for _, v in grid[max(0, n - 60):n] if v is not None]
        base = st.median(window) if len(window) > 5 else x
        if cur is None:
            if x >= base + RISE and x >= FLOOR:
                cur = {"start": t, "base": base, "peak": x, "peak_at": t, "pn": n}
            continue
        if x > cur["peak"]:
            cur.update(peak=x, peak_at=t, pn=n)
        if x <= cur["base"] + END_MARGIN:
            tail = [(g[0], g[1] - cur["base"]) for g in grid[cur["pn"]:n]
                    if g[1] is not None and g[1] - cur["base"] > END_MARGIN]
            a, b = cur["peak_at"], t
            nox_in = [v for tt, v in nox if cur["start"] - dt.timedelta(minutes=10) <= tt <= t]
            events.append(Event(
                start=cur["start"], base=cur["base"], peak=cur["peak"], peak_at=a, end=t,
                decay_per_h=decay_rate(tail),
                ac_frac=fraction(h.get(AC, []), a, b, {"1", "1.0"}),
                fan_frac=max((fraction(s, a, b, {"on"}) for s in fan_series), default=0.0),
                nox_peak=max(nox_in) if nox_in else None,
            ))
            cur = None
    if cur is not None:  # still clearing when the history window ends
        t = grid[-1][0]
        events.append(Event(start=cur["start"], base=cur["base"], peak=cur["peak"],
                            peak_at=cur["peak_at"], end=t, decay_per_h=None,
                            ac_frac=fraction(h.get(AC, []), cur["peak_at"], t, {"1", "1.0"}),
                            fan_frac=max((fraction(s, cur["peak_at"], t, {"on"})
                                          for s in fan_series), default=0.0),
                            nox_peak=None, ongoing=True))
    return events


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--since", help="start date YYYY-MM-DD, local midnight (overrides --days)")
    args = ap.parse_args()
    end = dt.datetime.now(dt.timezone.utc)
    start = (dt.datetime.fromisoformat(args.since).astimezone(dt.timezone.utc)
             if args.since else end - dt.timedelta(days=args.days))
    base, token = load_env()
    events = find_events(fetch(base, token, start, end))

    print(f"{'event':17} {'peak':>5} {'mins':>5} {'decay/h':>8} {'half-life':>9} "
          f"{'AC on':>6} {'fans':>5} {'NOx':>4}")
    for e in events:
        k = e.decay_per_h
        hl = f"{60 * math.log(2) / k:6.0f} m" if k and k > 0 else "     -"
        print(f"{e.start:%a %m-%d %H:%M} {e.peak:5.0f} {(e.end - e.start).total_seconds() / 60:5.0f} "
              f"{(f'{k:8.2f}' if k else '       -')} {hl:>9} {e.ac_frac:6.0%} {e.fan_frac:5.0%} "
              f"{(f'{e.nox_peak:4.0f}' if e.nox_peak is not None else '   -')}"
              f"{'  (ongoing)' if e.ongoing else ''}")
    rates = [e.decay_per_h for e in events if e.decay_per_h]
    if not rates:
        print("no events with a usable decay fit")
        return
    med = st.median(rates)
    print(f"\n{len(events)} events in {(end - start).days} days; median decay {med:.2f}/h "
          f"(half-life {60 * math.log(2) / med:.0f} min)")
    for label, pick in (("fans mostly on", lambda e: e.fan_frac >= 0.5),
                        ("fans mostly off", lambda e: e.fan_frac < 0.5),
                        ("AC mostly on", lambda e: e.ac_frac >= 0.5),
                        ("AC mostly off", lambda e: e.ac_frac < 0.5)):
        sub = [e.decay_per_h for e in events if e.decay_per_h and pick(e)]
        if sub:
            print(f"  {label:16} n={len(sub):2}  median decay {st.median(sub):.2f}/h")


if __name__ == "__main__":
    main()
