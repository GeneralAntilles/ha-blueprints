"""Render controllers to static HTML."""
from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import math
import pathlib
import shutil
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup

from .model import Controller

HERE = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = HERE / "templates"
STATIC = HERE / "static"

try:
    import segno
except ImportError:          # QR codes are optional
    segno = None


def build_hash(controllers: list[Controller], site: dict[str, Any], printed: dict[str, Any]) -> str:
    """Changes whenever any rendered output could change: used as ?v= cache buster."""
    h = hashlib.sha256()
    for c in controllers:
        h.update(c.rev.encode())
        h.update(c.slug.encode())
    h.update(json.dumps([site, printed], sort_keys=True, default=str).encode())
    for f in sorted(p for p in STATIC.rglob("*") if p.is_file()):
        h.update(f.read_bytes())
    for f in sorted(p for p in TEMPLATES.rglob("*") if p.is_file()):
        h.update(f.read_bytes())
    return h.hexdigest()[:8]


def qr_svg(url: str) -> Markup:
    """Inline SVG QR code (black modules, no quiet zone: the card margin is the border)."""
    if segno is None or not url:
        return Markup("")
    qr = segno.make(url, error="m")
    svg = qr.svg_inline(scale=1, border=1, dark="#000", light="#fff", omitsize=True,
                        svgclass="qr", title=None)
    return Markup(svg.replace("<svg ", '<svg role="img" aria-label="QR code: open this controller\'s '
                                        'page on your phone" ', 1))


def make_env(version: str) -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "j2", "svg"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tier"] = lambda gestures, max_tier: [g for g in gestures if g.tier <= max_tier]
    env.filters["density"] = density
    env.filters["cos"] = lambda a: round(math.cos(a), 3)
    env.filters["sin"] = lambda a: round(math.sin(a), 3)
    # Every internal link carries the build version so Home Assistant's /local
    # caching can never serve an old page next to new ones.
    env.filters["v"] = lambda url: f"{url}{'&' if '?' in url else '?'}v={version}"
    return env


def density(c: Controller, max_tier: int, roomy: int, dense: int) -> str:
    """CSS class for how full a fixed-size card will be: fewer rows get bigger type."""
    rows = sum(1 for ctl in c.controls for g in ctl.gestures if g.tier <= max_tier)
    rows += sum(1 for ctl in c.controls for g in ctl.gestures
                if g.tier <= max_tier and len(g.short) > 26)      # wraps to a second line
    if rows <= roomy:
        return "roomy"
    if rows <= dense:
        return ""
    return "dense"


def by_location(controllers: list[Controller]) -> list[tuple[str, list[Controller]]]:
    """Group by floor, preserving the extractor's sort order."""
    active = [c for c in controllers if not c.disabled]
    return [(floor, list(items)) for floor, items in
            itertools.groupby(active, key=lambda c: c.floor or "Other")]


def print_status(controllers: list[Controller], printed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """slug -> {date, rev, stale} for controllers that have a printed card on record."""
    out = {}
    for c in controllers:
        rec = printed.get(c.slug)
        if rec:
            out[c.slug] = {"date": rec.get("date"), "rev": rec.get("rev"), "stale": rec.get("rev") != c.rev}
    return out


def render_site(controllers: list[Controller], site: dict[str, Any], out: pathlib.Path,
                printed: dict[str, Any] | None = None) -> str:
    version = build_hash(controllers, site, printed or {})
    env = make_env(version)
    # Empty dist/ in place rather than deleting it, so a server or mount
    # pointed at the folder keeps working across rebuilds.
    out.mkdir(parents=True, exist_ok=True)
    for child in out.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    (out / "controllers").mkdir()
    (out / "print").mkdir()
    shutil.copytree(STATIC, out / "static")

    for c in controllers:
        if not (TEMPLATES / "devices" / f"{c.drawing}.svg.j2").exists():
            c.drawing = "generic"

    base = (site.get("base_url") or "").rstrip("/")
    common = {
        "site": site,
        "v": version,
        "built": dt.date.today().isoformat(),
        "controllers": controllers,
        "active": [c for c in controllers if not c.disabled],
        "floors": by_location(controllers),
        "disabled": [c for c in controllers if c.disabled],
        "qr": {c.slug: qr_svg(f"{base}/controllers/{c.slug}.html" if base else "") for c in controllers},
        "printed": print_status(controllers, printed or {}),
    }

    def write(rel: str, template: str, **ctx: Any) -> None:
        depth = rel.count("/")
        html = env.get_template(template).render(root="../" * depth, **common, **ctx)
        (out / rel).write_text(html)

    write("index.html", "index.html.j2", page_title="Controllers")
    write("cheatsheet.html", "cheatsheet.html.j2", page_title="Cheat sheet")
    for c in controllers:
        write(f"controllers/{c.slug}.html", "controller.html.j2", page_title=c.title, c=c)
    write("print/letter.html", "print/letter.html.j2", page_title="Letter sheets")
    write("print/card.html", "print/card.html.j2", page_title="6x4 cards")
    write("print/mini.html", "print/mini.html.j2", page_title="Mini labels")
    write("print/card-2up.html", "print/card-2up.html.j2", page_title="6x4 cards, 2 per Letter sheet")
    write("print/mini-10up.html", "print/mini-10up.html.j2", page_title="Mini labels, 10 per Letter sheet")
    (out / "version.txt").write_text(version + "\n")
    return version
