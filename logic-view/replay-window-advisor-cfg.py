#!/usr/bin/env python3
"""Equivalence replay (2026-10-09): decide() with the new `cfg` argument left at
its defaults vs the frozen v2 macro (window-advisor-v2.jinja, live 2026-10-08),
both rendered by HA. Random cases are clustered on every threshold, with
moving forecast curves, rain, gaps and both modes. The only allowed difference
is the new trend.hours key. Usage (after sourcing .env):
    python3 logic-view/replay-window-advisor-cfg.py [N]"""
import json, os, random, re, sys, urllib.request, pathlib, datetime as dt

ROOT = pathlib.Path(__file__).resolve().parent.parent
env = os.environ
URL = f"http://{env['HA_IP']}:8123/api/template"
OLD = (ROOT / 'logic-view' / 'window-advisor-v2.jinja').read_text()
NEW = (ROOT / 'climate' / 'window_advisor.jinja').read_text()


def render(tpl):
    req = urllib.request.Request(URL, data=json.dumps({"template": tpl}).encode(),
        headers={"Authorization": "Bearer " + env['HA_TOKEN'], "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=120).read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HA {e.code}: {e.read().decode()[:800]}")


def jlit(o):
    return re.sub(r'\bnull\b', 'none', json.dumps(o))


def near(t, spread):
    return round(t + random.uniform(-spread, spread), random.choice([0, 1]))


def case():
    now = dt.datetime(2026, 10, 8, 3, random.choice([0, 15, 30, 59]), tzinfo=dt.timezone.utc).timestamp()
    h0 = now - now % 3600 - random.choice([0, 0, 3600])
    it = near(random.choice([68, 66, 72, 74]), 4)
    raw = {'ot': near(random.choice([55, 52, it - 2, 74, 70]), 5), 'odp': near(random.choice([58, 60, 55]), 4),
           'it': it, 'idp': near(55, 4), 'irh': near(random.choice([60, 65, 52]), 5),
           'pm': near(random.choice([5, 20, 35]), 6), 'rr': random.choice([0, 0, 0, 0.02]),
           'gust': near(random.choice([5, 25]), 6)}
    raw = {k: ('unavailable' if random.random() < 0.01 else str(v)) for k, v in raw.items()}
    t0, d0 = float(near(66, 10)), float(near(56, 5))
    st, sd = random.uniform(-3, 3), random.uniform(-2, 2)
    hrs = []
    for k in range(random.choice([12, 12, 12, 4, 3])):
        h = {'t': dt.datetime.fromtimestamp(h0 + 3600 * k, dt.timezone.utc).isoformat(),
             'temp': round(t0 + st * k + random.uniform(-1, 1), 1), 'dp': round(d0 + sd * k, 1),
             'precip': random.choice([0, 0, 0, 0, 0.1, None])}
        r = random.random()
        if r < 0.04: del h['dp']
        elif r < 0.06: del h['precip']
        hrs.append(h)
    fetched = dt.datetime.fromtimestamp(now - 60 * random.choice([5, 30, 89, 95]), dt.timezone.utc).isoformat()
    return raw, hrs, fetched, now, random.random() < 0.5, random.random() < 0.05


def strip(d):
    d = json.loads(d)
    d.get('trend', {}).pop('hours', None)
    return d


n = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
random.seed(11)
cases = [case() for _ in range(n)]
diffs = 0
for i in range(0, n, 20):
    chunk = cases[i:i + 20]
    calls = ''.join(f"{{{{ decide({jlit(r)}, {jlit(h)}, {jlit(f)}, {now}, {str(s).lower()}, {str(rr).lower()}) }}}}~~SEP~~"
                    for r, h, f, now, s, rr in chunk)
    old = render(OLD + calls).split('~~SEP~~')
    new = render(NEW + calls).split('~~SEP~~')
    for k, (a, b) in enumerate(zip(old, new)):
        if not a.strip():
            continue
        if strip(a) != strip(b):
            diffs += 1
            if diffs <= 3:
                print('DIFF case', i + k, chunk[k][0], '\n old', a[:300], '\n new', b[:300])
print(f'{n} cases, {diffs} diffs')
sys.exit(1 if diffs else 0)
