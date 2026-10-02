#!/usr/bin/env python3
"""Equivalence replay: the pre-2026-09-30 window_advice state template vs
decide() in custom_templates/window_advisor.jinja, rendered by HA itself over
random inputs clustered on every threshold. Usage (after sourcing .env): python3 logic-view/replay-window-advisor.py [N]"""
import json, os, random, re, sys, urllib.request, pathlib, datetime as dt

ROOT = pathlib.Path(__file__).resolve().parent.parent
env = os.environ  # run as: set -a; source .env; set +a; python3 ...
URL = f"http://{env['HA_IP']}:8123/api/template"

# Old logic: the state template as it was in climate/window-advisor-templates.yaml
# (git-less repo, so a frozen copy lives next to this script).
old = (ROOT / 'logic-view' / 'window-advice-v1.jinja').read_text()
old = re.sub(r"\{#-INPUTS-#\}.*?\{#-END-#\}", "", old, flags=re.S)

def render(tpl):
    req = urllib.request.Request(URL, data=json.dumps({"template": tpl}).encode(),
        headers={"Authorization": "Bearer " + env['HA_TOKEN'], "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=120).read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HA {e.code}: {e.read().decode()[:800]}")

def jlit(o):
    # JSON null would parse as an undefined Jinja name; real HA data has None.
    return re.sub(r'\bnull\b', 'none', json.dumps(o))

def near(t, spread):
    return round(t + random.uniform(-spread, spread), random.choice([0, 1, 2]))

def case(now_ts):
    # Mostly "deep" cases (early gates pass) so every later threshold is hit.
    deep = random.random() < 0.8
    raw = {'ot': near(random.choice([55, 52, 74, 70, 66]), 8), 'odp': near(random.choice([57, 60, 55]), 5),
           'it': near(random.choice([68, 66, 72]), 5), 'idp': near(55, 5), 'irh': near(random.choice([60, 65]), 6),
           'pm': random.uniform(0, 15) if deep else near(random.choice([20, 35]), 8),
           'rr': 0 if deep else random.choice([0, 0.01, 0.2]),
           'gust': random.uniform(0, 20) if deep else near(25, 8)}
    raw = {k: (random.choice(['unavailable', 'unknown', '']) if random.random() < (0.005 if deep else 0.05) else str(v))
           for k, v in raw.items()}
    nh = 12 if deep else random.choice([12, 4, 2])
    start = 0 if deep else random.choice([-2, -1, 0])
    wet = 0.03 if deep else 0.2
    hours = [{'t': dt.datetime.fromtimestamp(now_ts + 3600 * (start + j), dt.timezone.utc).isoformat(),
              'temp': 70, 'dp': 55, 'precip': 0.1 if random.random() < wet else random.choice([0, 0, None])}
             for j in range(nh)]
    # Some hours missing the precip key entirely (review finding).
    for h in hours:
        if random.random() < 0.05: del h['precip']
    if not deep and random.random() < 0.05: hours = None
    age = random.choice([5, 30, 60]) if deep else random.choice([5, 89, 95, 200])
    fetched = None if (not deep and random.random() < 0.05) else \
        dt.datetime.fromtimestamp(now_ts - 60 * age, dt.timezone.utc).isoformat()
    return dict(raw=raw, hours=hours, fetched=fetched, now_ts=now_ts,
                stay=random.random() < 0.5, rr_recent=(not deep) and random.random() < 0.2)

n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
random.seed(7)
now_ts = dt.datetime.now(dt.timezone.utc).timestamp()
cases = [case(now_ts) for _ in range(n)]
tpl = ("{% from 'window_advisor.jinja' import decide %}"
       "{% macro old_logic(raw, hours, fetched, now_ts, stay, raining_recently) %}" + old + "{% endmacro %}"
       "{% set cases = " + jlit(cases) + " %}{% set out = namespace(l=[]) %}"
       "{% for c in cases %}{% set o = old_logic(c.raw, c.hours, c.fetched, c.now_ts, c.stay, c.rr_recent) | trim %}"
       "{% set d = decide(c.raw, c.hours, c.fetched, c.now_ts, c.stay, c.rr_recent) | from_json %}"
       "{% set out.l = out.l + [[o, d.state]] %}{% endfor %}{{ out.l | to_json }}")
try:
    res = json.loads(render(tpl))
except RuntimeError as e:
    # Find the first case that fails to render on its own.
    for c in cases:
        one = tpl.replace(jlit(cases), jlit([c]))
        try:
            render(one)
        except RuntimeError as e1:
            sys.exit(f"{e1}\ncase: {json.dumps(c)}")
    sys.exit(str(e))
bad = [(i, a, b) for i, (a, b) in enumerate(res) if a != b]
from collections import Counter
print(f"{len(res)} cases, {len(bad)} mismatches")
print(Counter(a.split(' (')[0] for a, _ in res).most_common())
for i, a, b in bad[:10]:
    print('MISMATCH', i, repr(a), '!=', repr(b), json.dumps(cases[i])[:400])
sys.exit(1 if bad else 0)
