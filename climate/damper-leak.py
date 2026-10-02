#!/usr/bin/env python3
"""Zone damper leak index: how much a zone cools while only the OTHER zone calls.

For each room sensor, averages the temperature change (degF/hour, 10-minute
windows) in three states: only the upstairs zone calling, nothing calling,
and the downstairs zone calling. The leak index for a downstairs room is

    (idle rate - upstairs-only rate) / (idle rate - downstairs-call rate)

i.e. the share of its own-call cooling it still gets while its damper should
be shut. Natural stack coupling (cold air down the stairwell) and the
afternoon clustering of upstairs-only calls also count, so read it as an
upper bound on damper leakage and compare before/after the damper repair.

Baseline 2026-09-27 (3 days, rusted Honeywell square dampers that don't
fully close): kitchen 59 %, master bedroom 49 %, living room 58 %. The
downstairs-call denominator had only n=6 windows (downstairs rarely calls -
itself a leak symptom), so compare with a longer --days run after the fix.

    python3 climate/damper-leak.py              # last 3 days
    python3 climate/damper-leak.py --days 7

Reads HA_TOKEN and HA_IP from ../.env. Only 10 days of hvac_action history
are practical to pull at once (attributes are fetched).
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import statistics as st
import urllib.request
from pathlib import Path

UP = "climate.studio_upstairs_thermostat"
DOWN = "climate.downstairs"
ROOMS = {
    "sensor.downstairs_current_temperature": ("Kitchen (downstairs ecobee)", True),
    "sensor.bedroom_co2_temperature": ("Master bedroom (Aranet4)", True),
    "sensor.airgradient_living_room_temperature": ("Living room (AirGradient)", True),
    "sensor.studio_upstairs_thermostat_current_temperature": ("Studio (upstairs ecobee)", False),
}
WINDOW = dt.timedelta(minutes=10)
Intervals = list[tuple[dt.datetime, dt.datetime]]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def history(env: dict[str, str], ids: list[str], start: dt.datetime, end: dt.datetime,
            attributes: bool) -> list[list[dict]]:
    q = (f"http://{env['HA_IP']}:8123/api/history/period/{start:%Y-%m-%dT%H:%M:%SZ}"
         f"?end_time={end:%Y-%m-%dT%H:%M:%SZ}&filter_entity_id={','.join(ids)}"
         + ("&significant_changes_only=0" if attributes else "&minimal_response&no_attributes"))
    req = urllib.request.Request(q, headers={"Authorization": f"Bearer {env['HA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def cooling_intervals(series: list[dict]) -> Intervals:
    runs: Intervals = []
    cur: dt.datetime | None = None
    for p in series:
        t = dt.datetime.fromisoformat(p.get("last_updated", p["last_changed"])).astimezone()
        cooling = p.get("attributes", {}).get("hvac_action") == "cooling"
        if cooling and cur is None:
            cur = t
        elif not cooling and cur is not None:
            runs.append((cur, t))
            cur = None
    return runs


def inside(runs: Intervals, t: dt.datetime) -> bool:
    return any(a <= t < b for a, b in runs)


def state_at(up: Intervals, down: Intervals, t: dt.datetime) -> str:
    if inside(down, t):
        return "down"
    return "up" if inside(up, t) else "idle"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=3)
    args = ap.parse_args()
    env = load_env()
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=args.days)

    zones = {s[0]["entity_id"]: cooling_intervals(s)
             for s in history(env, [UP, DOWN], start, end, attributes=True)}
    up, down = zones.get(UP, []), zones.get(DOWN, [])
    temps: dict[str, list[tuple[dt.datetime, float]]] = {}
    for s in history(env, list(ROOMS), start, end, attributes=False):
        pts = []
        for p in s:
            try:
                pts.append((dt.datetime.fromisoformat(p["last_changed"]).astimezone(), float(p["state"])))
            except ValueError:
                pass
        temps[s[0]["entity_id"]] = pts

    t0 = max(v[0][0] for v in temps.values())
    t1 = min(v[-1][0] for v in temps.values())
    print(f"{'room':30} {'upstairs-only':>15} {'idle':>15} {'downstairs call':>16} {'leak index':>11}")
    for eid, (name, downstairs) in ROOMS.items():
        pts = temps.get(eid, [])
        times = [t for t, _ in pts]
        rates: dict[str, list[float]] = {"up": [], "idle": [], "down": []}
        t = t0
        while t + WINDOW <= t1:
            states = {state_at(up, down, t + dt.timedelta(minutes=m)) for m in (0, 5, 9)}
            ka = bisect.bisect_right(times, t) - 1
            kb = bisect.bisect_right(times, t + WINDOW) - 1
            if len(states) == 1 and ka >= 0 and kb >= 0:
                rates[states.pop()].append((pts[kb][1] - pts[ka][1]) * 6)
            t += WINDOW

        def fmt(xs: list[float]) -> str:
            return f"{st.mean(xs):+.2f} (n={len(xs)})" if len(xs) >= 3 else "-"

        leak = "-"
        if downstairs and all(len(rates[k]) >= 3 for k in rates):
            idle, u, d = (st.mean(rates[k]) for k in ("idle", "up", "down"))
            if idle - d > 0:
                leak = f"{(idle - u) / (idle - d):.0%}"
        print(f"{name:30} {fmt(rates['up']):>15} {fmt(rates['idle']):>15} {fmt(rates['down']):>16} {leak:>11}")


if __name__ == "__main__":
    main()
