"""Minimal, read-mostly Home Assistant API helpers.

Reads HA_URL / HA_TOKEN / HA_IP / HA_CONFIG_PATH from the repo-root .env
(values may be double-quoted). REST and WebSocket calls fall back from the
hostname to HA_IP when mDNS (ha.local) fails to resolve or connect.
"""
from __future__ import annotations

import json
import pathlib
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import websockets

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class HAEnv:
    url: str
    token: str
    ip: str | None
    config_path: str | None


def load_env(path: pathlib.Path | None = None) -> HAEnv:
    env_file = path or (REPO_ROOT / ".env")
    values: dict[str, str] = {}
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    url = values.get("HA_URL", "").rstrip("/")
    token = values.get("HA_TOKEN", "")
    if not url or not token:
        sys.exit(f"HA_URL/HA_TOKEN not found in {env_file}")
    return HAEnv(url, token, values.get("HA_IP") or None, values.get("HA_CONFIG_PATH") or None)


def _with_ip(url: str, ip: str) -> str:
    parsed = urllib.parse.urlparse(url)
    netloc = ip + (f":{parsed.port}" if parsed.port else "")
    return parsed._replace(netloc=netloc).geturl()


class HAClient:
    """REST + WebSocket client. Use as `async with HAClient(env) as ha:`."""

    def __init__(self, env: HAEnv) -> None:
        self.env = env
        self.base = env.url
        self._ws: Any = None
        self._next_id = 1

    # ---------- REST ----------
    def get(self, path: str) -> Any:
        headers = {"Authorization": f"Bearer {self.env.token}"}
        try:
            return self._get(self.base + path, headers)
        except urllib.error.URLError as err:
            if self.env.ip and self.base == self.env.url and isinstance(
                err.reason, (socket.gaierror, OSError)
            ):
                print(f"{self.env.url} unreachable ({err.reason}); retrying via {self.env.ip}",
                      file=sys.stderr)
                self.base = _with_ip(self.env.url, self.env.ip)
                return self._get(self.base + path, headers)
            raise

    @staticmethod
    def _get(url: str, headers: dict[str, str]) -> Any:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    # ---------- WebSocket ----------
    async def __aenter__(self) -> "HAClient":
        ws_url = self.base.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
        try:
            self._ws = await websockets.connect(ws_url, max_size=64 * 1024 * 1024)
        except (socket.gaierror, OSError):
            if not self.env.ip:
                raise
            print(f"websocket to {self.base} failed; retrying via {self.env.ip}", file=sys.stderr)
            self.base = _with_ip(self.env.url, self.env.ip)
            ws_url = _with_ip(ws_url, self.env.ip)
            self._ws = await websockets.connect(ws_url, max_size=64 * 1024 * 1024)
        if json.loads(await self._ws.recv())["type"] != "auth_required":
            raise RuntimeError("unexpected websocket greeting")
        await self._ws.send(json.dumps({"type": "auth", "access_token": self.env.token}))
        if json.loads(await self._ws.recv())["type"] != "auth_ok":
            raise RuntimeError("websocket auth failed (check HA_TOKEN)")
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._ws is not None:
            await self._ws.close()

    async def ws(self, msg_type: str, **fields: Any) -> Any:
        msg_id = self._next_id
        self._next_id += 1
        await self._ws.send(json.dumps({"id": msg_id, "type": msg_type, **fields}))
        while True:
            resp = json.loads(await self._ws.recv())
            if resp.get("id") == msg_id and resp.get("type") == "result":
                break
        if not resp.get("success"):
            raise RuntimeError(f"{msg_type} failed: {resp.get('error')}")
        return resp.get("result")
