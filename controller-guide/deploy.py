#!/usr/bin/env python3
"""Publish dist/ into Home Assistant and keep a "Controllers" sidebar entry.

    python3 build.py && python3 deploy.py

1. Mirrors dist/ to $HA_CONFIG_PATH/www/controller-guide/ (the config share
   must be mounted; /local/ serves that folder, no restart needed). Files
   that are no longer in dist/ are removed from the target.
2. Creates the storage dashboard `controller-guide` if it doesn't exist
   (title Controllers, mdi:remote, in the sidebar, not admin-only) and sets
   its config to the iframe strategy pointing at the new build. Re-running
   is safe: it only updates the version in the URL.

Note: files under /local/ are served without authentication to anyone who
can reach Home Assistant. The guide holds nothing secret.
"""
from __future__ import annotations

import asyncio
import filecmp
import pathlib
import shutil
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from guide.ha_api import HAClient, load_env  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
DIST = HERE / "dist"
TARGET_NAME = "controller-guide"
DASHBOARD = {"url_path": "controller-guide", "title": "Controllers", "icon": "mdi:remote",
             "show_in_sidebar": True, "require_admin": False}


def preflight(src: pathlib.Path, www: pathlib.Path, dst: pathlib.Path) -> None:
    """Refuse anything that could redirect writes or deletes outside dst."""
    if www.is_symlink() or dst.is_symlink():
        sys.exit(f"refusing to deploy: {www if www.is_symlink() else dst} is a symlink")
    if dst.exists() and dst.resolve() != (www.resolve() / TARGET_NAME):
        sys.exit(f"refusing to deploy: {dst} resolves outside {www}")
    for tree in (src, dst):
        if tree.exists():
            links = [p for p in tree.rglob("*") if p.is_symlink()]
            if links:
                sys.exit(f"refusing to deploy: symlink(s) inside {tree}: {links[:3]}")


def looks_like_ha_config(config: pathlib.Path) -> bool:
    return (config / "configuration.yaml").is_file() and (config / ".storage").is_dir()


def mirror(src: pathlib.Path, dst: pathlib.Path) -> tuple[int, int]:
    """Copy changed files, delete files that vanished. Returns (copied, removed)."""
    copied = removed = 0
    dst.mkdir(parents=True, exist_ok=True)
    wanted = {p.relative_to(src) for p in src.rglob("*") if p.is_file()}
    for rel in sorted(wanted):
        s, d = src / rel, dst / rel
        if d.exists() and filecmp.cmp(s, d, shallow=False):
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)
        copied += 1
    for p in sorted(dst.rglob("*"), reverse=True):
        rel = p.relative_to(dst)
        if p.is_file() and rel not in wanted:
            p.unlink()
            removed += 1
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    return copied, removed


async def ensure_dashboard(version: str) -> str:
    env = load_env()
    async with HAClient(env) as ha:
        dashboards = await ha.ws("lovelace/dashboards/list")
        existing = next((d for d in dashboards if d.get("url_path") == DASHBOARD["url_path"]), None)
        if existing is None:
            await ha.ws("lovelace/dashboards/create", mode="storage", **DASHBOARD)
            action = "created"
        else:
            action = "updated"
        await ha.ws("lovelace/config/save", url_path=DASHBOARD["url_path"], config={
            "strategy": {"type": "iframe", "url": f"/local/{TARGET_NAME}/index.html?v={version}",
                         "title": "Controllers"},
        })
        return f"{action} sidebar dashboard /{DASHBOARD['url_path']}"


def served_version(env, version: str) -> str | None:
    """version.txt as Home Assistant serves it right now (uncached)."""
    url = f"{env.url}/local/{TARGET_NAME}/version.txt?t={version}-{int(time.time())}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read().decode().strip()
    except OSError as err:
        print(f"check failed: {url}: {err}", file=sys.stderr)
        return None


def main() -> int:
    if not (DIST / "index.html").exists():
        sys.exit("dist/ is empty: run build.py first")
    env = load_env()
    config = pathlib.Path(env.config_path or "/Volumes/config")
    www = config / "www"
    if not looks_like_ha_config(config) or not www.is_dir():
        sys.exit(f"{config} doesn't look like the Home Assistant config share (no configuration.yaml, "
                 ".storage/ or www/): mount it first (Finder > Go > Connect to Server, smb://<ha-ip>/config)")
    dst = www / TARGET_NAME
    preflight(DIST, www, dst)
    version = (DIST / "version.txt").read_text().strip()
    copied, removed = mirror(DIST, dst)
    print(f"www/{TARGET_NAME}: {copied} file(s) copied, {removed} removed (build {version})")

    # Only point the dashboard at the new build once HA is really serving it,
    # which also proves the mounted share is this HA instance's config.
    served = served_version(env, version)
    if served != version:
        print(f"HA serves version {served!r}, expected {version!r}: the mounted share may not be "
              f"{env.url}'s config. Dashboard NOT updated.", file=sys.stderr)
        return 1
    print(asyncio.run(ensure_dashboard(version)))
    print(f"check: {env.url}/local/{TARGET_NAME}/ serves build {served}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
