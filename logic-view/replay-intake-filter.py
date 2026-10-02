#!/usr/bin/env python3
"""Equivalence replay: the pre-2026-09-30 inline intake-filter templates
(frozen in intake-filter-v1.yaml; logic copied below with inputs injected) vs
step()/life() in custom_templates/intake_filter.jinja, rendered by HA itself.
Usage (after sourcing .env): python3 logic-view/replay-intake-filter.py [N]"""
import json, os, random, re, sys, urllib.request, urllib.error

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

OLD_LOAD = """{% macro old_load(prev_state, trig_id, actions, intake_on, pm_raw) %}
{% set prev = prev_state | float(0) %}
{% if trig_id == 'reset' %}0
{% else %}
  {% set blower = actions | select('in', ['cooling', 'heating', 'fan']) | list | count > 0 %}
  {% if blower and intake_on %}
    {% set w = [[pm_raw | float(10) / 10, 0.5] | max, 3] | min %}
    {{ (prev + w / 720) | round(4) }}
  {% else %}{{ prev | round(4) }}{% endif %}
{% endif %}{% endmacro %}"""

OLD_LIFE = """{% macro old_life(load_raw, target_raw, changed_raw, now_ts) %}
{% set load = load_raw | float(0) %}
{% set target = target_raw | float(180) %}
{% set changed = changed_raw | float(0) %}
{% set age = (now_ts - changed) / 86400 if changed > 946684800 else 0 %}
{% set state = ([load / target, age / 365] | max * 100) | round(0) %}
{% set age_days = ((now_ts - changed) / 86400) | int if changed > 946684800 else none %}
{% set limit = 'calendar' if age / 365 > load / target else 'usage' %}
{{ [state, age_days, limit] | to_json }}{% endmacro %}"""

def case(now_ts):
    acts = ['idle', 'cooling', 'heating', 'fan', 'off', None]
    return dict(prev=random.choice(['0', '0.0', '12.3456', '179.99', 'unknown', 'unavailable', str(round(random.uniform(0, 400), 4))]),
                trig=random.choice(['0', '0', '0', 'reset']),
                actions=[random.choice(acts), random.choice(acts)],
                intake=random.random() < 0.6,
                pm=random.choice(['unavailable', '', '0', '4.9', '5', '10', '29.9', '30', '31', '120', str(round(random.uniform(0, 60), 2))]),
                target=random.choice(['180', '90', '400', 'unknown', '30']),
                changed=random.choice([None, 946684800.0, 0, now_ts - random.uniform(0, 800) * 86400]),
                now=now_ts)

n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
random.seed(11)
import time
now_ts = time.time()
cases = [case(now_ts) for _ in range(n)]
tpl = ("{% from 'intake_filter.jinja' import step, life %}" + OLD_LOAD + OLD_LIFE +
       "{% set out = namespace(l=[]) %}{% for c in " + jlit(cases) + " %}"
       "{% set o1 = old_load(c.prev, c.trig, c.actions, c.intake, c.pm) | trim | float %}"
       "{% set s = step(c.actions, c.intake, c.pm) | from_json %}"
       "{% set n1 = 0 if c.trig == 'reset' else (c.prev | float(0) + s.inc) | round(4) %}"
       "{% set o2 = old_life(c.prev, c.target, c.changed, c.now) | trim | from_json %}"
       "{% set l = life(c.prev, c.target, c.changed, c.now) | from_json %}"
       "{% set out.l = out.l + [[o1, n1 | float, o2, [l.pct, l.age_days, l.limit], s.counting]] %}"
       "{% endfor %}{{ out.l | to_json }}")
res = json.loads(render(tpl))
bad = [(i, r) for i, r in enumerate(res) if r[0] != r[1] or r[2] != r[3]]
print(f"{len(res)} cases, {len(bad)} mismatches; counting in {sum(r[4] for r in res)}; "
      f"calendar-limited {sum(r[2][2] == 'calendar' for r in res)}")
for i, r in bad[:8]:
    print('MISMATCH', r, json.dumps(cases[i]))
sys.exit(1 if bad else 0)
