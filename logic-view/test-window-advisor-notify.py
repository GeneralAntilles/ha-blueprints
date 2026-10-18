#!/usr/bin/env python3
"""Notification matrix for window-advisor-notify.yaml (2026-10-18): renders
each choose-branch condition (in order, first match wins) and the quiet /
home / tag templates in HA via /api/template with synthetic variables. No
pushes are sent. Usage (after sourcing .env):
    python3 logic-view/test-window-advisor-notify.py"""
import json, os, re, sys, urllib.request, pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
env = os.environ
URL = f"http://{env['HA_IP']}:8123/api/template"


class L(yaml.SafeLoader):
    pass


L.add_constructor('!input', lambda l, n: {'!input': l.construct_scalar(n)})
BP = yaml.load((ROOT / 'window-advisor-notify.yaml').read_text(), Loader=L)
CHOOSE = next(a for a in BP['actions'] if 'choose' in a)['choose']
NAMES = ['button', 'hazard', 'extreme', 'blind', 'away', 'close', 'open']
VARS = next(a for a in BP['actions'] if 'variables' in a)['variables']


def render(tpl):
    req = urllib.request.Request(URL, data=json.dumps({"template": tpl}).encode(),
        headers={"Authorization": "Bearer " + env['HA_TOKEN'], "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=60).read().decode().strip()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HA {e.code}: {e.read().decode()[:600]}")


def lit(v):
    return re.sub(r'\btrue\b', 'true', re.sub(r'\bnull\b', 'none', json.dumps(v)))


NOW = 1_800_000_000
BASE = {'trigger': {'id': 'check', 'event': {'data': {'action': ''}}}, 'now_ts': NOW, 'stamp': NOW,
        'is_open': True, 'open_since': NOW - 7200, 'good': False, 'bad': True,
        'good_since': NOW - 20000, 'bad_since': NOW - 600, 'hazard': False, 'hazard_reason': None,
        'hazard_since': 0, 'extreme': False, 'extreme_since': 0, 'blind_since': 0, 'quiet': False, 'home': True,
        'sent': {'advice': 0, 'close': 0, 'hazard': 0, 'extreme': 0, 'blind': 0}, 'a': {'open_ok': True},
        'IK': 'HOME', 'ik': 'home'}


def branch(**over):
    v = {**BASE, **over}
    pre = ''.join(f"{{% set {k} = {lit(x)} %}}" for k, x in v.items())
    for name, b in zip(NAMES, CHOOSE):
        c = b['conditions']
        if isinstance(c, list):   # the button branch: condition: trigger
            ok = v['trigger']['id'] == 'button'
        else:
            ok = render(pre + c) == 'True'
        if ok:
            return name
    return None


fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'  -- got {got!r}, want {want!r}'))
    fails += not ok


check('bad while open, not yet sent -> close', branch(), 'close')
check('close already sent this episode -> nothing', branch(sent={**BASE['sent'], 'close': NOW - 300}), None)
check('close suppressed 45 min after a hazard push', branch(sent={**BASE['sent'], 'hazard': NOW - 1000}), None)
check('close again at the end of quiet hours', branch(trigger={'id': 'morning'}, sent={**BASE['sent'], 'close': NOW - 4000}), 'close')
check('opened during a bad episode -> close for the new open', branch(open_since=NOW - 60, sent={**BASE['sent'], 'close': NOW - 300}), 'close')
check('closed windows -> no close push', branch(is_open=False), None)
check('flag flipped, advisor not caught up -> wait', branch(trigger={'id': 'switch'}, open_since=NOW - 5, a={'open_ok': True, 'windows_open': False, 'windows_tracked': True}), None)
check('flag flipped, advisor caught up and still bad -> close', branch(trigger={'id': 'switch'}, open_since=NOW - 5, a={'open_ok': True, 'windows_open': True, 'windows_tracked': True}), 'close')
check('flag flipped, advisor does not track the toggle -> close now', branch(trigger={'id': 'switch'}, open_since=NOW - 5, a={'open_ok': True, 'windows_open': False, 'windows_tracked': False}), 'close')
check('flag flipped, pre-upgrade advisor (no attributes) -> close now', branch(trigger={'id': 'switch'}, open_since=NOW - 5, a={'open_ok': True}), 'close')
check('blind 30 min while open', branch(trigger={'id': 'blind'}, bad=False, blind_since=NOW - 1800), 'blind')
check('blind caught by the 15-min check (trigger lost to a reload)', branch(bad=False, blind_since=NOW - 4000), 'blind')
check('blind already sent this spell -> nothing', branch(bad=False, blind_since=NOW - 4000, sent={**BASE['sent'], 'blind': NOW - 2000}), None)
check('blind under 30 min -> nothing', branch(bad=False, blind_since=NOW - 1700), None)
check('hazard while open -> hazard first', branch(hazard=True, hazard_reason="It's raining", hazard_since=NOW - 30), 'hazard')
check('hazard sent, same kind -> nothing (and no close)', branch(hazard=True, hazard_since=NOW - 900, sent={**BASE['sent'], 'hazard': NOW - 600}), None)
check('hazard changed kind after the push -> again', branch(hazard=True, hazard_since=NOW - 60, sent={**BASE['sent'], 'hazard': NOW - 600}), 'hazard')
check('extreme while open', branch(extreme=True, extreme_since=NOW - 30), 'extreme')
check('extreme repeats after 2 h', branch(extreme=True, extreme_since=NOW - 9000, sent={**BASE['sent'], 'extreme': NOW - 7300}), 'extreme')
check('extreme within 2 h of the last -> falls to close', branch(extreme=True, extreme_since=NOW - 9000, sent={**BASE['sent'], 'extreme': NOW - 3600}), 'close')
check('away while open', branch(trigger={'id': 'away'}, bad=False), 'away')
OPEN = dict(is_open=False, good=True, bad=False, good_since=NOW - 300, sent={**BASE['sent'], 'advice': NOW - 20000})
check('good, closed, open_ok, home -> open', branch(**OPEN), 'open')
check('open_ok false (crack / stay limits) -> no open push', branch(**{**OPEN, 'a': {'open_ok': False}}), None)
check('quiet hours -> no open push', branch(**OPEN, quiet=True), None)
check('away from home -> no open push', branch(**OPEN, home=False), None)
check('already sent this episode -> no open push', branch(**{**OPEN, 'sent': {**BASE['sent'], 'advice': NOW - 200}}), None)
check('3 h floor between open pushes', branch(**{**OPEN, 'good_since': NOW - 60, 'sent': {**BASE['sent'], 'advice': NOW - 3600}}), None)
check('button: opened (matching stamp) -> button branch', branch(trigger={'id': 'button', 'event': {'data': {'action': 'HOME_WINDOWS_OPENED_5'}}}), 'button')

# button sub-conditions
sub = CHOOSE[0]['sequence'][1]['choose']
def btn(act, **over):
    v = {**BASE, **over, 'act': act}
    pre = ''.join(f"{{% set {k} = {lit(x)} %}}" for k, x in v.items())
    return [render(pre + s['conditions']) == 'True' for s in sub]
check('opened button: latest stamp, closed, < 6 h', btn('HOME_WINDOWS_OPENED_1799999000', is_open=False, sent={**BASE['sent'], 'advice': 1799999000}), [True, False])
check('opened button: stale stamp ignored', btn('HOME_WINDOWS_OPENED_1799990000', is_open=False, sent={**BASE['sent'], 'advice': 1799999000}), [False, False])
check('opened button: other instance ignored', btn('ATTIC_WINDOWS_OPENED_1799999000', is_open=False, sent={**BASE['sent'], 'advice': 1799999000}), [False, False])
check('closed button while open', btn('HOME_WINDOWS_CLOSED'), [False, True])
check('closed button: other instance ignored', btn('ATTIC_WINDOWS_CLOSED'), [False, False])

# quiet hours / home / instance key templates
def var(name, **v):
    pre = ''.join(f"{{% set {k} = {lit(x)} %}}" for k, x in v.items())
    return render(pre + VARS[name])
for t, qs, qe, want in [('23:00:00', '22:00:00', '07:00:00', 'True'), ('06:59:59', '22:00:00', '07:00:00', 'True'),
                        ('07:00:00', '22:00:00', '07:00:00', 'False'), ('14:00:00', '13:00:00', '15:00:00', 'True'),
                        ('16:00:00', '13:00:00', '15:00:00', 'False')]:
    tpl = VARS['quiet'].replace("now().strftime('%H:%M:%S')", repr(t))
    check(f'quiet {qs}-{qe} at {t}', render(f"{{% set qs = {qs!r} %}}{{% set qe = {qe!r} %}}" + tpl), want)
check('home: no presence entities = home', var('home', presence_e=[]), 'True')
check('home: anyone home counts', render("{% set presence_e = ['zone.home', 'person.zz_nobody'] %}" + VARS['home'].replace("states(e)", "({'zone.home': '1'}.get(e, 'not_home'))")), 'True')
check('home: nobody home', render("{% set presence_e = ['zone.home'] %}" + VARS['home'].replace("states(e)", "'0'")), 'False')
check('instance key sanitised', render("{% set ik_in = 'My Attic-2' %}{% set this = {'entity_id': 'automation.x'} %}" + BP['variables']['ik']), 'my_attic_2')
check('instance key defaults to the automation id', render("{% set ik_in = '' %}{% set this = {'entity_id': 'automation.climate_window_advisor'} %}" + BP['variables']['ik']), 'climate_window_advisor')

print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
