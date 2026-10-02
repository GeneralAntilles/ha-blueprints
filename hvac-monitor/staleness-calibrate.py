#!/usr/bin/env python3
"""Calibrate the sensor staleness watchdog: one "Stale <tier>" label per sensor.

For every enabled, non-diagnostic numeric sensor from a physical integration
(derived helpers like template/statistics/group are skipped - their sources
are checked instead), this pulls N days of recorder history, takes the 99th
longest gap between recorded changes, and picks the smallest tier that is
at least 1.5x that gap (the max, not a percentile: a solar sensor sits at 0
all night, and those few long gaps are exactly what must not false-alarm): 30m, 2h, 6h, 24h or 72h. Sensors with fewer than 20
changes in the window get 72h. Devices labelled "Awaiting setup" are skipped.

sensor.stale_sensors (template) then flags a labelled sensor whose
last_reported is older than its tier. The recorder stores changes, not
reports, and last_reported >= last_changed, so thresholds err towards "not
stale" (flat-but-alive sensors never false-alarm). Limits: a restart resets
last_reported (a quiet sensor is re-flagged one tier later), and integrations
that keep re-writing a cached value hide silence - the Health tab's
unavailable list covers those.

Dry run by default (prints the plan); --apply creates the labels if needed
and rewrites only the managed "Stale ..." labels on each entity, keeping any
other labels. Re-run monthly or after adding devices.

    python3 hvac-monitor/staleness-calibrate.py            # dry run, 7 days
    python3 hvac-monitor/staleness-calibrate.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import urllib.request
from pathlib import Path

import websockets

TIERS: list[tuple[str, str, int]] = [  # label name, label id, seconds
    ("Stale 30m", "stale_30m", 1800),
    ("Stale 2h", "stale_2h", 7200),
    ("Stale 6h", "stale_6h", 21600),
    ("Stale 24h", "stale_24h", 86400),
    ("Stale 72h", "stale_72h", 259200),
]
MANAGED = {lid for _, lid, _ in TIERS}
DERIVED_PLATFORMS = {
    "template", "group", "statistics", "min_max", "derivative", "integration",
    "utility_meter", "filter", "threshold", "trend", "history_stats", "sun",
    "time_date", "uptime", "battery_notes", "powercalc", "energy", "compensation",
    "command_line", "season", "workday", "moon", "scrape",
    # personal devices / vehicles / consumables: legitimately silent for days
    "mobile_app", "ipp", "teslemetry", "ibeacon",
}
MIN_CHANGES = 20
BATCH = 25


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class WS:
    def __init__(self, ws: websockets.WebSocketClientProtocol) -> None:
        self.ws, self.n = ws, 0

    async def call(self, msg: dict) -> object:
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, **msg}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.n:
                if not r.get("success", True):
                    raise RuntimeError(r.get("error"))
                return r.get("result")


def is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def change_times(env: dict[str, str], ids: list[str], start: dt.datetime,
                 end: dt.datetime) -> dict[str, list[float]]:
    q = (f"http://{env['HA_IP']}:8123/api/history/period/{start:%Y-%m-%dT%H:%M:%SZ}"
         f"?end_time={end:%Y-%m-%dT%H:%M:%SZ}&filter_entity_id={','.join(ids)}"
         "&minimal_response&no_attributes")
    req = urllib.request.Request(q, headers={"Authorization": f"Bearer {env['HA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.load(r)
    out: dict[str, list[float]] = {}
    for series in data:
        out[series[0]["entity_id"]] = [dt.datetime.fromisoformat(p["last_changed"]).timestamp()
                                       for p in series[1:]]  # first row is the window-start state
    return out


def tier_for(times: list[float]) -> tuple[str, float | None]:
    if len(times) < MIN_CHANGES:
        return "stale_72h", None
    longest = max(b - a for a, b in zip(times, times[1:]))
    for _, lid, sec in TIERS:
        if sec >= 1.5 * longest:
            return lid, longest
    return "stale_72h", longest


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    env = load_env()
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=args.days)

    async with websockets.connect(f"ws://{env['HA_IP']}:8123/api/websocket", max_size=None) as raw:
        await raw.recv()
        await raw.send(json.dumps({"type": "auth", "access_token": env["HA_TOKEN"]}))
        await raw.recv()
        ws = WS(raw)
        entities = await ws.call({"type": "config/entity_registry/list"})
        devices = await ws.call({"type": "config/device_registry/list"})
        labels = await ws.call({"type": "config/label_registry/list"})
        states = {s["entity_id"]: s for s in await ws.call({"type": "get_states"})}

        awaiting = {lab["label_id"] for lab in labels if lab["name"].lower() == "awaiting setup"}
        parked_devices = {d["id"] for d in devices if awaiting & set(d.get("labels", []))}
        candidates = [
            e for e in entities
            if e["entity_id"].startswith("sensor.")
            and not e.get("disabled_by")
            and e.get("entity_category") is None
            and e.get("platform") not in DERIVED_PLATFORMS
            and e.get("device_id") not in parked_devices
            and e["entity_id"] in states
            and is_number(states[e["entity_id"]]["state"])
        ]
        ids = [e["entity_id"] for e in candidates]
        times: dict[str, list[float]] = {}
        for i in range(0, len(ids), BATCH):
            times.update(change_times(env, ids[i:i + BATCH], start, end))

        plan: dict[str, str] = {}
        by_tier: collections.Counter[str] = collections.Counter()
        by_platform: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
        changes: list[tuple[str, str, str]] = []
        for e in candidates:
            eid = e["entity_id"]
            lid, p99 = tier_for(times.get(eid, []))
            plan[eid] = lid
            by_tier[lid] += 1
            by_platform[e["platform"]][lid] += 1
            current = sorted(set(e.get("labels", [])) & MANAGED)
            if current != [lid]:
                changes.append((eid, ",".join(current) or "-", lid))

        print(f"{len(candidates)} sensors considered ({args.days} days of history)")
        for name, lid, _ in TIERS:
            print(f"  {name:10} {by_tier[lid]:4}")
        print("by integration:")
        for plat, c in sorted(by_platform.items()):
            print(f"  {plat:22} " + "  ".join(f"{lid[6:]}:{n}" for lid, n in sorted(c.items())))
        dropped_n = sum(1 for e in entities
                        if e["entity_id"] not in plan and MANAGED & set(e.get("labels", [])))
        print(f"{len(changes)} label changes, {dropped_n} out-of-scope labels to clear")
        for eid, old, new in changes[:25]:
            print(f"  {eid:60} {old:>10} -> {new}")
        if len(changes) > 25:
            print(f"  ... {len(changes) - 25} more")

        if not args.apply:
            print("\ndry run - re-run with --apply to write labels")
            return
        have = {lab["label_id"] for lab in labels}
        for name, lid, _ in TIERS:
            if lid not in have:
                await ws.call({"type": "config/label_registry/create", "name": name,
                               "icon": "mdi:clock-alert-outline"})
        reg = {e["entity_id"]: e for e in candidates}
        for eid, _, lid in changes:
            keep = [x for x in reg[eid].get("labels", []) if x not in MANAGED]
            await ws.call({"type": "config/entity_registry/update", "entity_id": eid,
                           "labels": keep + [lid]})
        # Entities that were calibrated before but are no longer candidates
        # (device now "Awaiting setup", disabled, excluded platform...) lose
        # their managed label so the watchdog stops checking them.
        dropped = [e for e in entities
                   if e["entity_id"] not in plan and MANAGED & set(e.get("labels", []))]
        for e in dropped:
            await ws.call({"type": "config/entity_registry/update", "entity_id": e["entity_id"],
                           "labels": [x for x in e.get("labels", []) if x not in MANAGED]})
        print(f"applied {len(changes)} label changes, cleared {len(dropped)} out-of-scope")


if __name__ == "__main__":
    asyncio.run(main())
