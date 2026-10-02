#!/usr/bin/env python3
"""Whole-house thermal balance from HA long-term statistics.

Three views of how hard the house makes the AC work:

1. Night fit (23:00-06:00, no sun): hourly compressor duty vs the
   outdoor-indoor temperature gap. The slope is the house's sensible heat
   leak in "duty per degF"; where the line hits zero is the outdoor
   temperature at which the AC would idle (a natural window-opening line).
2. Daily fit: AC hours/day vs mean temperature gap and mean moisture gap
   (outdoor minus indoor humidity ratio, grains/lb), splitting runtime into
   temperature, moisture (infiltration + the 8" intake) and everything else
   (people, appliances, sun). Residuals show days the AC worked harder or
   easier than the weather explains - a drift upward at equal weather is an
   early sign of an AC or envelope problem.
3. Coasting fit, for when there are hours with the compressor fully off
   (shoulder season): indoor temperature change per hour vs the gap, whose
   inverse is the house's time constant.

Baseline 2026-09-27 (09-07..09-26, cooling, 74 degF setpoint): night duty
0.037/degF, idle at ~70 degF outdoors; daily 0.54 h per degF + 0.044 h per
grain/lb + 4.3 h; ~13.8 h/day = ~50 % temperature, ~20 % moisture, ~30 %
other; 2 fully-off hours (no coasting fit yet).

    python3 climate/thermal-balance.py               # since 2026-09-06
    python3 climate/thermal-balance.py --since 2026-10-15

Reads HA_TOKEN and HA_IP from ../.env. Needs numpy and websockets.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import math
import statistics as st
from pathlib import Path

import numpy as np
import websockets

IDS = {
    "tin": "sensor.indoor_temperature",
    "tout": "sensor.outdoor_temperature",
    "duty": "sensor.ac_compressor_state",
    "odp": "sensor.outdoor_dewpoint",
    "idp": "sensor.indoor_dew_point",
    "sun": "sensor.weather_station_solar_radiation",
}
NIGHT_HOURS = {23, 0, 1, 2, 3, 4, 5}
# Lennox 14ACXS036 (3-ton, 2019) on a CHX35-30B 2.5-ton cased coil with an
# EL180UH070E36B furnace blower: a mismatched pair, so effective capacity is
# assumed between the two (~2.7 ton). Check the AHRI match rating to refine.
CAPACITY_BTUH = 32_000
FLOOR_AREA_SQFT = 1772  # ~1100 down, ~670 up; duplex with a shared party wall
Hourly = dict[str, dict[int, float]]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


async def fetch(env: dict[str, str], start: dt.datetime) -> Hourly:
    async with websockets.connect(f"ws://{env['HA_IP']}:8123/api/websocket", max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": env["HA_TOKEN"]}))
        await ws.recv()
        await ws.send(json.dumps({
            "id": 1, "type": "recorder/statistics_during_period",
            "start_time": start.isoformat(), "period": "hour",
            "statistic_ids": list(IDS.values()), "types": ["mean"],
        }))
        res = json.loads(await ws.recv())["result"]
    return {key: {p["start"]: p["mean"] for p in res.get(eid, []) if p.get("mean") is not None}
            for key, eid in IDS.items()}


def grains(dew_point_f: float) -> float:
    """Humidity ratio in grains of water per lb of dry air, sea level."""
    tc = (dew_point_f - 32) * 5 / 9
    pw = 0.61078 * math.exp(17.27 * tc / (tc + 237.3))
    return 0.622 * pw / (101.325 - pw) * 7000


def local_hour(ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000)


def night_fit(d: Hourly, cap: float, sqft: float) -> None:
    hs = [h for h in d["duty"] if h in d["tin"] and h in d["tout"]
          and local_hour(h).hour in NIGHT_HOURS]
    if len(hs) < 20:
        print("night fit: not enough hours")
        return
    x = np.array([d["tout"][h] - d["tin"][h] for h in hs])
    y = np.array([d["duty"][h] for h in hs])
    a, c = np.polyfit(x, y, 1)
    r2 = np.corrcoef(x, y)[0, 1] ** 2
    tin = st.mean(d["tin"][h] for h in hs)
    print(f"NIGHT  n={len(hs)}  duty = {a:.4f} x gap + {c:.3f}  (R2 {r2:.2f})")
    if a > 0:
        print(f"       AC idles at gap {-c / a:+.1f} degF -> ~{tin - c / a:.0f} degF outdoors "
              f"(indoor mean {tin:.1f})")
        ua = a * cap
        print(f"       envelope UA ~{ua:.0f} BTU/h per degF ({ua / sqft:.2f} per sq ft) "
              f"at {cap / 12000:.2f} ton")


def daily_fit(d: Hourly, cap: float, sqft: float) -> None:
    days: dict[dt.date, list[int]] = collections.defaultdict(list)
    for h in d["duty"]:
        if all(h in d[k] for k in ("tin", "tout", "odp", "idp")):
            days[local_hour(h).date()].append(h)
    rows = []
    for day, hs in sorted(days.items()):
        if len(hs) < 23:
            continue
        rows.append((day, sum(d["duty"][h] for h in hs),
                     st.mean(d["tout"][h] - d["tin"][h] for h in hs),
                     st.mean(grains(d["odp"][h]) - grains(d["idp"][h]) for h in hs)))
    if len(rows) < 7:
        print("daily fit: fewer than 7 full days")
        return
    y = np.array([r[1] for r in rows])
    x = np.array([[r[2], r[3], 1.0] for r in rows])
    b, *_ = np.linalg.lstsq(x, y, rcond=None)
    pred = x @ b
    r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    gap, moist = x[:, 0].mean(), x[:, 1].mean()
    print(f"DAILY  n={len(rows)}  AC h/day = {b[0]:.2f} x gap + {b[1]:.3f} x grains + {b[2]:.2f}"
          f"  (R2 {r2:.2f})")
    print(f"       at mean conditions ({gap:.1f} degF, {moist:.0f} gr/lb): temperature "
          f"{b[0] * gap:.1f} h, moisture {b[1] * moist:.1f} h, other {b[2]:.1f} h "
          f"of {y.mean():.1f} h/day")
    ua = b[0] / 24 * cap
    latent_per_grain = b[1] / 24 * cap  # BTU/h per grain/lb of moisture gap
    print(f"       envelope UA ~{ua:.0f} BTU/h per degF ({ua / sqft:.2f} per sq ft); "
          f"moisture term ~{latent_per_grain / 0.68:.0f} CFM of outside air "
          f"(~{latent_per_grain * moist * 24 / 1060:.0f} lb water/day)")
    print("       residual (actual - expected h): "
          + " ".join(f"{r[0]:%m-%d}:{y[i] - pred[i]:+.1f}" for i, r in enumerate(rows)))


def coasting_fit(d: Hourly) -> None:
    hour = 3_600_000
    pts = [(d["tout"][h] - d["tin"][h], d["tin"][h + hour] - d["tin"][h])
           for h in d["duty"]
           if d["duty"][h] == 0 and d["duty"].get(h + hour) == 0
           and h in d["tin"] and h + hour in d["tin"] and h in d["tout"]]
    if len(pts) < 10:
        print(f"COAST  only {len(pts)} consecutive compressor-off hour pairs - "
              "wait for the shoulder season")
        return
    x = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    k, c = np.polyfit(x, y, 1)
    print(f"COAST  n={len(pts)}  indoor change/h = {k:.3f} x gap + {c:+.2f} degF/h"
          + (f"  -> time constant ~{1 / k:.0f} h" if k > 0 else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default="2026-09-06", help="YYYY-MM-DD, local midnight")
    ap.add_argument("--capacity", type=float, default=CAPACITY_BTUH, help="AC BTU/h")
    ap.add_argument("--sqft", type=float, default=FLOOR_AREA_SQFT)
    args = ap.parse_args()
    start = dt.datetime.fromisoformat(args.since).astimezone(dt.timezone.utc)
    d = asyncio.run(fetch(load_env(), start))
    print(f"{len(d['duty'])} hourly rows since {args.since}; "
          f"{sum(1 for v in d['duty'].values() if v == 0)} with the compressor fully off\n")
    night_fit(d, args.capacity, args.sqft)
    daily_fit(d, args.capacity, args.sqft)
    coasting_fit(d)


if __name__ == "__main__":
    main()
