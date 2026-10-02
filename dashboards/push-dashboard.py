#!/usr/bin/env python3
"""Push a dashboard YAML file to Home Assistant (storage-mode) via WebSocket.

Usage (from repo root or dashboards/):
    python3 dashboards/push-dashboard.py home-dashboard.yaml dashboard-home

The dashboard must already exist (Settings -> Dashboards, or
lovelace/dashboards/create). This overwrites its stored config with the
YAML file's content, so the file stays the source of truth.
"""
import asyncio
import json
import pathlib
import socket
import sys
import urllib.parse

import websockets
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env() -> tuple[str, str, str | None]:
    url = token = ip = None
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line.startswith("HA_URL="):
            url = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("HA_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("HA_IP="):
            ip = line.split("=", 1)[1].strip().strip('"')
    if not url or not token:
        sys.exit("HA_URL/HA_TOKEN not found in .env")
    return url, token, ip


async def connect_ws(url: str, ip: str | None):
    """Connect to HA's websocket; if the hostname doesn't resolve (ha.local
    mDNS flakes on this network), retry with HA_IP from .env."""
    ws_url = url.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
    try:
        return await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
    except socket.gaierror:
        if not ip:
            raise
        parsed = urllib.parse.urlparse(ws_url)
        fallback = ws_url.replace(parsed.hostname, ip)
        print(f"{parsed.hostname} not resolving; falling back to {ip}", file=sys.stderr)
        return await websockets.connect(fallback, max_size=50 * 1024 * 1024)


async def push(config: dict, url_path: str) -> None:
    url, token, ip = load_env()
    async with await connect_ws(url, ip) as ws:
        assert json.loads(await ws.recv())["type"] == "auth_required"
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"
        await ws.send(json.dumps({
            "id": 1, "type": "lovelace/config/save",
            "url_path": url_path, "config": config,
        }))
        resp = json.loads(await ws.recv())
        if not resp.get("success"):
            sys.exit(f"save failed: {resp.get('error')}")
        print(f"pushed to {url_path}")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    yaml_file = pathlib.Path(sys.argv[1])
    if not yaml_file.exists():
        yaml_file = REPO_ROOT / "dashboards" / sys.argv[1]
    config = yaml.safe_load(yaml_file.read_text())
    asyncio.run(push(config, sys.argv[2]))


if __name__ == "__main__":
    main()
