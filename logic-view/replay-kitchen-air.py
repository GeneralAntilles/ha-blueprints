#!/usr/bin/env python3
"""Equivalence replay: the pre-2026-09-30 kitchen exhaust start/end conditions
(copied verbatim from climate_kitchen_air_dry_weather_exhaust, inputs injected)
vs decide() in custom_templates/kitchen_air.jinja, rendered by HA itself.
Usage (after sourcing .env): python3 logic-view/replay-kitchen-air.py [N]"""
import json, os, random, re, sys, time, urllib.request, urllib.error

URL = f"http://{os.environ['HA_IP']}:8123/api/template"

def render(tpl):
    req = urllib.request.Request(URL, data=json.dumps({"template": tpl}).encode(),
        headers={"Authorization": "Bearer " + os.environ['HA_TOKEN'], "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=120).read().decode()
    except urllib.error.HTTPError as e:
        sys.exit(f"HA {e.code}: {e.read().decode()[:800]}")

def jlit(o):
    return re.sub(r'\bnull\b', 'none', json.dumps(o))

# Verbatim old logic: variables spike_new / laundry_busy / active / owned /
# elapsed and the two choose conditions (trigger.id == 'check' assumed).
OLD = """{% macro old(run, now_ts, pm, base, odp, spike_on, spike_changed_ts, steamer_on, laundry_rh) %}
{% set active = run.s is defined %}
{% set owned = run.f | default([]) %}
{% set elapsed = now_ts - (run.s | default(now_ts) | int) %}
{% set spike_new = spike_on and spike_changed_ts > (run.e | default(0) | float) %}
{% set laundry_busy = 'switch.laundry_room_fan' in owned
     and (steamer_on or laundry_rh | float(0) >= 72) %}
{% set start = not active and spike_new and is_number(odp) and odp | float < 60 %}
{% set end = active
     and not (laundry_busy and elapsed < 10800)
     and (run.x is defined
          or owned | length == 0
          or elapsed >= 3600
          or not is_number(odp) or odp | float >= 62
          or (elapsed >= 600 and is_number(pm)
              and pm | float <= (run.b | default(0) | float) + 3)) %}
{{ [start, end] | to_json }}{% endmacro %}"""

FANS = ['switch.downstairs_bathroom_fan', 'switch.laundry_room_fan']

def val():
    # Automation variables are native-typed: numbers arrive as floats, the rest as strings.
    return random.choice([round(random.uniform(0, 80), 1), random.choice([10, 13, 15, 57, 59.9, 60, 61.9, 62, 70]),
                          'unavailable', 'unknown', ''])

def case(now_ts):
    kind = random.choice(['idle', 'idle', 'active', 'active', 'active', 'empty'])
    if kind == 'empty':
        run = {}
    elif kind == 'idle':
        run = {'e': now_ts - random.choice([30, 600, 7200, 86400])}
    else:
        run = {'s': now_ts - random.choice([30, 599, 600, 1200, 3599, 3600, 5000, 10799, 10800, 12000]),
               'b': random.choice([3, 8.5, 12]), 'f': random.sample(FANS, random.randint(0, 2))}
        if random.random() < 0.15: run['x'] = now_ts - random.choice([60, 700])
        if random.random() < 0.5:
            # "Clean" run: every other end condition passes, so the PM2.5
            # clearing term (baseline + 3 after 10 min) decides.
            run.pop('x', None); run['f'] = [FANS[0]]
            run['s'] = now_ts - random.choice([300, 599, 600, 601, 1800, 3500])
            return dict(run=run, now=now_ts, pm=random.choice([run['b'] + 2.9, run['b'] + 3, run['b'] + 3.1, 'unavailable', 40.0]),
                        base=5.0, odp=55.0, spike=False, changed=now_ts - 90000, steamer=False, rh=50)
    changed = now_ts - random.choice([10, 300, 4000, 90000])
    return dict(run=run, now=now_ts, pm=val(), base=val(), odp=val(), spike=random.random() < 0.5,
                changed=changed, steamer=random.random() < 0.2,
                rh=random.choice(['unavailable', 60, 71.9, 72, 80, round(random.uniform(40, 90), 1)]))

n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
random.seed(5)
now_ts = int(time.time())
cases = [case(now_ts) for _ in range(n)]
tpl = ("{% from 'kitchen_air.jinja' import decide %}" + OLD +
       "{% set out = namespace(l=[]) %}{% for c in " + jlit(cases) + " %}"
       "{% set o = old(c.run, c.now, c.pm, c.base, c.odp, c.spike, c.changed, c.steamer, c.rh) | trim | from_json %}"
       "{% set d = decide(c.run, c.now, c.pm, c.base, c.odp, c.spike, c.changed, c.steamer, c.rh) | from_json %}"
       "{% set out.l = out.l + [[o, [d.start, d.end], d.state]] %}{% endfor %}{{ out.l | to_json }}")
res = json.loads(render(tpl))
bad = [(i, r) for i, r in enumerate(res) if r[0] != r[1]]
from collections import Counter
print(f"{len(res)} cases, {len(bad)} mismatches; start {sum(r[0][0] for r in res)}, end {sum(r[0][1] for r in res)}")
print(Counter(r[2].split(' (')[0] for r in res).most_common())
for i, r in bad[:8]:
    print('MISMATCH', r, json.dumps(cases[i]))
sys.exit(1 if bad else 0)
