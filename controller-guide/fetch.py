#!/usr/bin/env python3
"""Fetch controller data from Home Assistant into data/snapshot.json.

Read-only: REST GETs and WebSocket list commands. No SMB mount needed.

    python3 fetch.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import re
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from guide.ha_api import HAClient, load_env  # noqa: E402
from guide.hue_api import credentials, fetch_switch_config  # noqa: E402
from guide.layouts import CONTROLLER_BLUEPRINTS, is_controller_device  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
SNAPSHOT = HERE / "data" / "snapshot.json"
FRIENDLY_DOMAINS = {
    "scene", "light", "switch", "script", "fan", "media_player", "climate", "cover",
    "input_boolean", "input_button", "input_number", "input_select", "event", "lock",
    "automation", "sensor", "binary_sensor", "select", "tts", "input_text",
}
ENTITY_RE = re.compile(r"\b([a-z_]+\.[a-z0-9_]+)\b")
LED_RE = re.compile(r"LED|Indicator", re.I)
INOVELLI_LED_RE = re.compile(r"^number\..*default_all_led_((?:on|off)_(?:color|intensity))$")
HEX32_RE = re.compile(r"\b[0-9a-f]{32}\b")


def flatten_inputs(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Blueprint metadata.input may nest inputs inside sections."""
    flat: dict[str, dict[str, Any]] = {}
    for key, spec in inputs.items():
        if isinstance(spec, dict) and isinstance(spec.get("input"), dict):
            flat.update(flatten_inputs(spec["input"]))
        else:
            flat[key] = spec if isinstance(spec, dict) else {}
    return flat


def schema_hash(flat: dict[str, dict[str, Any]]) -> str:
    """Hash of input names + defaults: changes when the blueprint's knobs change."""
    canon = {k: v.get("default") for k, v in sorted(flat.items())}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()[:12]


async def fetch_leds(env: Any, keep_devs: dict[str, Any], entities: list[dict[str, Any]],
                     states: list[dict[str, Any]]) -> dict[str, Any]:
    """LED settings for controller devices, read-only.

    Z-Wave: config parameters whose label mentions an LED or indicator.
    ZHA Inovelli: the default light-bar colour/intensity number entities.
    """
    leds: dict[str, Any] = {}
    async with HAClient(env) as ha:
        for dev_id, dev in keep_devs.items():
            if not any(i[0] == "zwave_js" for i in dev.get("identifiers") or []):
                continue
            try:
                params = await ha.ws("zwave_js/get_config_parameters", device_id=dev_id)
            except RuntimeError as err:
                print(f"warning: no config parameters for {dev.get('name_by_user') or dev['name']}: "
                      f"{err}", file=sys.stderr)
                continue
            rows = []
            for key, p in params.items():
                md = p.get("metadata") or {}
                label = md.get("label") or ""
                if LED_RE.search(label) and "Reporting" not in label:
                    value = p.get("value")
                    rows.append({"param": int(key.split("-")[-1]), "label": label, "value": value,
                                 "state": (md.get("states") or {}).get(str(value))})
            if rows:
                leds[dev_id] = {"zwave": sorted(rows, key=lambda r: r["param"])}
    state_by_id = {st["entity_id"]: st["state"] for st in states}
    for e in entities:
        m = INOVELLI_LED_RE.match(e["entity_id"])
        if m and e.get("device_id") in keep_devs:
            leds.setdefault(e["device_id"], {}).setdefault("zha", {})[m.group(1)] = \
                state_by_id.get(e["entity_id"])
    return leds


async def fetch() -> dict[str, Any]:
    env = load_env()
    async with HAClient(env) as ha:
        states = ha.get("/api/states")
        blueprints = await ha.ws("blueprint/list", domain="automation")
        devices = await ha.ws("config/device_registry/list")
        areas = await ha.ws("config/area_registry/list")
        floors = await ha.ws("config/floor_registry/list")
        entities = await ha.ws("config/entity_registry/list")


    # Automations: fetch config only for controller-blueprint instances.
    instances: list[dict[str, Any]] = []
    for st in states:
        if not st["entity_id"].startswith("automation."):
            continue
        auto_id = st["attributes"].get("id")
        if not auto_id:
            continue
        cfg = ha.get(f"/api/config/automation/config/{auto_id}")
        bp = (cfg.get("use_blueprint") or {}).get("path")
        if bp not in CONTROLLER_BLUEPRINTS:
            continue
        instances.append({
            "id": auto_id,
            "entity_id": st["entity_id"],
            "alias": cfg.get("alias"),
            "state": st["state"],
            "blueprint": bp,
            "input": cfg["use_blueprint"].get("input", {}),
        })
    instances.sort(key=lambda i: i["id"])

    bp_schemas: dict[str, Any] = {}
    for path in CONTROLLER_BLUEPRINTS:
        meta = (blueprints.get(path) or {}).get("metadata")
        if not meta:
            print(f"warning: blueprint {path} not found in HA", file=sys.stderr)
            continue
        flat = flatten_inputs(meta.get("input", {}))
        bp_schemas[path] = {
            "name": meta.get("name"),
            "hash": schema_hash(flat),
            "inputs": {k: {"name": v.get("name"), "default": v.get("default")}
                       for k, v in flat.items()},
        }

    lost = sorted({i["blueprint"] for i in instances} - set(bp_schemas))
    if lost:
        raise SystemExit(f"blueprint metadata missing for {lost}; snapshot NOT written")

    # Devices: referenced by an instance, or a known controller model.
    blob = json.dumps(instances)
    referenced_devs = set(HEX32_RE.findall(blob))
    keep_devs = {
        d["id"]: {k: d.get(k) for k in ("id", "name", "name_by_user", "manufacturer",
                                         "model", "model_id", "area_id", "identifiers")}
        for d in devices
        if d["id"] in referenced_devs or is_controller_device(d)
    }

    leds = await fetch_leds(env, keep_devs, entities, states)

    # Entities: referenced by an instance (by entity_id or registry id), or on a kept device.
    referenced_ents = set(ENTITY_RE.findall(blob))
    keep_ents = {}
    for e in entities:
        on_controller = e.get("device_id") in keep_devs and e["entity_id"].startswith("event.")
        if e["entity_id"] in referenced_ents or e.get("id") in referenced_devs or on_controller:
            keep_ents[e["entity_id"]] = {
                k: e.get(k) for k in ("entity_id", "id", "device_id", "name",
                                       "original_name", "platform", "disabled_by")
            }

    friendly = {
        st["entity_id"]: st["attributes"].get("friendly_name") or st["entity_id"]
        for st in states if st["entity_id"].split(".", 1)[0] in FRIENDLY_DOMAINS
    }
    # Keep friendly names small: referenced entities + all scenes/scripts (for labels).
    friendly = {
        k: v for k, v in friendly.items()
        if k in referenced_ents or k in keep_ents or k.split(".", 1)[0] in ("scene", "script")
    }

    return {
        "ha_url": env.url,
        "instances": instances,
        "blueprints": bp_schemas,
        "devices": keep_devs,
        "areas": {a["area_id"]: {"name": a["name"], "floor_id": a.get("floor_id")} for a in areas},
        "floors": {f["floor_id"]: {"name": f["name"], "level": f.get("level")} for f in floors},
        "entities": keep_ents,
        "leds": leds,
        "friendly": dict(sorted(friendly.items())),
        "all_entity_ids": sorted(st["entity_id"] for st in states),
    }


def fetch_hue(previous: dict[str, Any] | None) -> dict[str, Any] | None:
    creds = credentials()
    if creds is None:
        if previous and previous.get("hue"):
            print("warning: no Hue credentials (add HUE_BRIDGE_HOST/HUE_APP_KEY to .env or mount "
                  "the HA config share); keeping the previous Hue data, which may be stale",
                  file=sys.stderr)
            hue = dict(previous["hue"])
            hue["stale"] = True
            return hue
        print("warning: no Hue credentials; Hue switch cards will be placeholders", file=sys.stderr)
        return None
    host, key, source = creds
    try:
        hue = fetch_switch_config(host, key)
    except Exception as err:  # noqa: BLE001 - network/bridge errors all mean "keep old data"
        print(f"warning: Hue bridge {host} unreachable ({err}); keeping previous Hue data",
              file=sys.stderr)
        return {**previous["hue"], "stale": True} if previous and previous.get("hue") else None
    print(f"hue: {len(hue['behaviors'])} switch configurations from {host} (key from {source})")
    return hue


def main() -> None:
    previous = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else None
    snap = asyncio.run(fetch())
    hue = fetch_hue(previous)
    if hue is not None:
        snap["hue"] = hue
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(snap, indent=1, sort_keys=True, default=str) + "\n")
    on = sum(1 for i in snap["instances"] if i["state"] != "off")
    print(f"wrote {SNAPSHOT.relative_to(HERE)}: {len(snap['instances'])} instances "
          f"({on} enabled), {len(snap['devices'])} devices, {len(snap['entities'])} entities")


if __name__ == "__main__":
    main()
