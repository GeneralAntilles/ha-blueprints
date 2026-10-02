"""Read-only access to the Hue bridge (CLIP v2) for switch configurations.

Credentials, first match wins:
  1. HUE_BRIDGE_HOST / HUE_APP_KEY in the repo .env
  2. Home Assistant's own Hue config entry, when the config share is mounted
     at HA_CONFIG_PATH (.storage/core.config_entries)
The bridge uses a self-signed certificate, so TLS verification is off for
this LAN-only host. Only GET requests are made.
"""
from __future__ import annotations

import json
import pathlib
import ssl
import urllib.request
from typing import Any

from .ha_api import REPO_ROOT

RESOURCES = ("behavior_instance", "device", "button", "room", "zone", "scene", "smart_scene")


def _env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    env = REPO_ROOT / ".env"
    if env.exists():
        for raw in env.read_text().splitlines():
            if "=" in raw and not raw.lstrip().startswith("#"):
                k, v = raw.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def credentials() -> tuple[str, str, str] | None:
    """(host, key, source) or None."""
    env = _env_values()
    if env.get("HUE_BRIDGE_HOST") and env.get("HUE_APP_KEY"):
        return env["HUE_BRIDGE_HOST"], env["HUE_APP_KEY"], ".env"
    cfg = pathlib.Path(env.get("HA_CONFIG_PATH", "/Volumes/config")) / ".storage" / "core.config_entries"
    try:
        entries = json.loads(cfg.read_text())["data"]["entries"]
    except (OSError, KeyError, ValueError):
        return None
    for e in entries:
        if e.get("domain") == "hue" and e.get("data", {}).get("api_key"):
            return e["data"]["host"], e["data"]["api_key"], "HA hue config entry"
    return None


def fetch_switch_config(host: str, key: str) -> dict[str, Any]:
    ctx = ssl._create_unverified_context()   # self-signed bridge cert, LAN only

    def get(rtype: str) -> list[dict[str, Any]]:
        req = urllib.request.Request(f"https://{host}/clip/v2/resource/{rtype}",
                                     headers={"hue-application-key": key})
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            return json.load(resp)["data"]

    raw = {r: get(r) for r in RESOURCES}
    behaviors = [b for b in raw["behavior_instance"]
                 if isinstance((b.get("configuration") or {}).get("buttons"), dict)]
    blob = json.dumps(behaviors)
    return {
        "behaviors": [{
            "id": b["id"], "name": (b.get("metadata") or {}).get("name"), "enabled": b.get("enabled"),
            "device": b["configuration"].get("device", {}).get("rid"),
            "model_id": b["configuration"].get("model_id"),
            "buttons": b["configuration"]["buttons"],
        } for b in behaviors],
        "buttons": {x["id"]: {"control_id": x["metadata"]["control_id"], "device": x["owner"]["rid"]}
                    for x in raw["button"]},
        "devices": {x["id"]: {"name": x["metadata"]["name"],
                              "model_id": x["product_data"]["model_id"],
                              "product": x["product_data"]["product_name"]}
                    for x in raw["device"]
                    if any(s["rtype"] == "button" for s in x.get("services", []))},
        "groups": {x["id"]: {"name": x["metadata"]["name"], "type": t}
                   for t in ("room", "zone") for x in raw[t] if x["id"] in blob},
        "scenes": {x["id"]: {"name": x["metadata"]["name"], "type": t}
                   for t in ("scene", "smart_scene") for x in raw[t] if x["id"] in blob},
    }
