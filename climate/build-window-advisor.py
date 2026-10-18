#!/usr/bin/env python3
"""Copies decide() and its helpers from climate/window_advisor.jinja into the
window-advisor.yaml blueprint, between the BEGIN/END decide markers
(blueprints can't ship custom_templates). A wrapper macro that reads live
entities, if one is appended to the jinja file after the WRAPPER comment, is
left out.

    python3 climate/build-window-advisor.py          # rewrite the blueprint
    python3 climate/build-window-advisor.py --check  # exit 1 if out of date
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'climate' / 'window_advisor.jinja'
DST = ROOT / 'window-advisor.yaml'
BEGIN = re.compile(r'^( *)\{#- BEGIN decide .*-#\}$', re.M)
END_MARK = '{#- END decide -#}'
WRAPPER = '{#- Gathers the live inputs and decides.'


def body() -> str:
    src = SRC.read_text()
    cut = src.find(WRAPPER)
    return (src[:cut] if cut >= 0 else src).rstrip() + '\n'


def build(text: str) -> str:
    m = BEGIN.search(text)
    if not m:
        raise SystemExit(f'{DST.name}: BEGIN decide marker not found')
    indent = m.group(1)
    end = text.find(indent + END_MARK, m.end())
    if end < 0:
        raise SystemExit(f'{DST.name}: END decide marker not found')
    lines = [(indent + ln) if ln.strip() else '' for ln in body().splitlines()]
    return text[:m.end()] + '\n' + '\n'.join(lines) + '\n' + text[end:]


def main() -> None:
    old = DST.read_text()
    new = build(old)
    if '--check' in sys.argv:
        if new != old:
            print(f'{DST.name} is out of date: run climate/build-window-advisor.py')
            sys.exit(1)
        print(f'{DST.name}: decide() matches {SRC.name}')
        return
    if new != old:
        DST.write_text(new)
        print(f'{DST.name}: decide() updated from {SRC.name}')
    else:
        print(f'{DST.name}: already up to date')


if __name__ == '__main__':
    main()
