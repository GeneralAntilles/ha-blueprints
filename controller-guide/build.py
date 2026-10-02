#!/usr/bin/env python3
"""Build the controller guide from data/snapshot.json + data/overlay.yaml.

    python3 build.py                       # writes dist/ and dist/build-report.txt
    python3 build.py --strict              # exit 1 if there are any warnings
    python3 build.py --pdf                 # also write dist/pdf/*.pdf (headless Chrome)
    python3 build.py --mark-printed all    # record the current card revisions as printed
    python3 build.py --mark-printed kitchen-remote office-cube
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from guide.extract import Extractor  # noqa: E402
from guide.render import render_site, segno  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"
DIST = HERE / "dist"
PRINTED = DATA / "printed.json"
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "chromium", "chromium-browser",
)
PDF_DOCS = {
    "letter": "print/letter.html",
    "cards-6x4": "print/card.html",
    "cards-2up-letter": "print/card-2up.html",
    "labels-3.5x2": "print/mini.html",
    "labels-10up-letter": "print/mini-10up.html",
    "cheatsheet": "cheatsheet.html",
}


def find_chrome() -> str | None:
    for c in CHROME_CANDIDATES:
        if pathlib.Path(c).exists() or shutil.which(c):
            return c
    return None


def write_pdfs(out: pathlib.Path) -> list[str]:
    chrome = find_chrome()
    if not chrome:
        return ["--pdf: Chrome/Chromium not found; no PDFs written"]
    (out / "pdf").mkdir(exist_ok=True)
    problems = []
    for name, rel in PDF_DOCS.items():
        target = out / "pdf" / f"{name}.pdf"
        cmd = [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
               "--virtual-time-budget=3000", f"--print-to-pdf={target}", (out / rel).resolve().as_uri()]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if run.returncode != 0 or not target.exists():
            problems.append(f"--pdf: {name} failed: {run.stderr.strip()[:200]}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="exit non-zero on any warning")
    ap.add_argument("--pdf", action="store_true", help="write dist/pdf/*.pdf with headless Chrome")
    ap.add_argument("--mark-printed", nargs="+", metavar="SLUG",
                    help="record these cards (or 'all') as printed at their current revision")
    ap.add_argument("--snapshot", type=pathlib.Path, default=DATA / "snapshot.json")
    ap.add_argument("--overlay", type=pathlib.Path, default=DATA / "overlay.yaml")
    ap.add_argument("--out", type=pathlib.Path, default=DIST)
    args = ap.parse_args()

    if not args.snapshot.exists():
        sys.exit(f"{args.snapshot} missing: run fetch.py first")
    snapshot = json.loads(args.snapshot.read_text())
    overlay = yaml.safe_load(args.overlay.read_text()) or {}
    printed = json.loads(PRINTED.read_text()) if PRINTED.exists() else {}

    ex = Extractor(snapshot, overlay)
    controllers = ex.run()

    if args.mark_printed:
        today = dt.date.today().isoformat()
        wanted = {c.slug for c in controllers} if args.mark_printed == ["all"] else set(args.mark_printed)
        unknown = wanted - {c.slug for c in controllers}
        if unknown:
            sys.exit(f"unknown slugs: {sorted(unknown)}")
        for c in controllers:
            if c.slug in wanted:
                printed[c.slug] = {"rev": c.rev, "date": today}
        PRINTED.write_text(json.dumps(dict(sorted(printed.items())), indent=1) + "\n")
        print(f"marked {len(wanted)} card(s) as printed on {today}")

    site = {"title": "House Controllers", "base_url": "", **(overlay.get("site") or {})}
    version = render_site(controllers, site, args.out, printed)
    if segno is None:
        ex.report.warn("QR", "segno is not installed; printed cards have no QR codes (pip install segno)")
    if args.pdf:
        for problem in write_pdfs(args.out):
            ex.report.warn("PDF", problem)

    broken = [w for w in ex.report.warnings if "BROKEN" in w]
    other = [w for w in ex.report.warnings if "BROKEN" not in w]
    stale = [c for c in controllers if c.slug in printed and printed[c.slug]["rev"] != c.rev]
    never = [c for c in controllers if c.slug not in printed and not c.disabled]
    lines = [f"build {version}: {len(controllers)} controllers "
             f"({sum(c.disabled for c in controllers)} disabled)", ""]
    lines += [f"  {c.slug:<24} rev {c.rev}  {c.title} ({c.location})"
              + ("  [has broken bindings]" if c.has_broken else "")
              + ("  [printed card out of date]" if c in stale else "") for c in controllers]
    lines += ["", f"REPRINT ({len(stale)}): printed card no longer matches"]
    lines += [f"  - {c.slug}: printed {printed[c.slug]['date']} as rev {printed[c.slug]['rev']}, "
              f"now rev {c.rev}" for c in stale]
    if printed:
        lines += [f"  (never printed: {', '.join(c.slug for c in never) or 'none'})"]
    lines += ["", f"BROKEN BINDINGS ({len(broken)})"] + [f"  - {w}" for w in broken]
    lines += ["", f"WARNINGS ({len(other)})"] + [f"  - {w}" for w in other]
    (args.out / "build-report.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {args.out}")
    return 1 if (args.strict and ex.report.warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
