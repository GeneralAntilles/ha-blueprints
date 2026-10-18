#!/usr/bin/env python3
"""Sequence tests for the window-advisor.yaml template blueprint (2026-10-18):
renders the blueprint's per-tick `out` template in HA (/api/template) with
fake sensor readings, feeding each tick's result back in as the previous
attributes the way the sensor does. Covers the debounce (20 min on / 10 min
off, 19 vs 20, 9 vs 10), Blind mid-good, the restart-gap reset, the
forgotten-window alarm (15 min on, immediate off), hazard re-arming on a
change of kind, °C sensors and RH-derived dew points, and the build check.
Usage (after sourcing .env):
    python3 logic-view/test-window-advisor-blueprint.py"""
import ast, json, os, re, subprocess, sys, urllib.request, pathlib, datetime as dt
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
env = os.environ
URL = f"http://{env['HA_IP']}:8123/api/template"


class L(yaml.SafeLoader):
    pass


L.add_constructor('!input', lambda l, n: {'!input': l.construct_scalar(n)})
BP = yaml.load((ROOT / 'window-advisor.yaml').read_text(), Loader=L)
OUT = next(a['variables']['out'] for a in BP['actions'] if 'variables' in a and 'out' in a['variables'])
# Fake sensors: the blueprint reads every sensor through S() / U(); swap those.
OUT = OUT.replace("{%- macro S(e) -%}{{ states(e) if e else 'unavailable' }}{%- endmacro -%}",
                  "{%- macro S(e) -%}{{ FAKE.get(e, 'unavailable') if e else 'unavailable' }}{%- endmacro -%}", 1)
OUT = OUT.replace("{%- macro U(e) -%}{{ state_attr(e, 'unit_of_measurement') if e else '' }}{%- endmacro -%}",
                  "{%- macro U(e) -%}{{ FAKE_U.get(e, '') if e else '' }}{%- endmacro -%}", 1)
OUT = OUT.replace("{%- macro A(e, k) -%}{{ state_attr(e, k) }}{%- endmacro -%}",
                  "{%- macro A(e, k) -%}{{ FAKE_A.get(e ~ '|' ~ k) }}{%- endmacro -%}", 1)
assert OUT.count('FAKE') == 3, 'fake substitution drifted from the blueprint'


def render(tpl):
    req = urllib.request.Request(URL, data=json.dumps({"template": tpl}).encode(),
        headers={"Authorization": "Bearer " + env['HA_TOKEN'], "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=60).read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HA {e.code}: {e.read().decode()[:800]}")


def lit(v):
    return re.sub(r'\bnull\b', 'none', re.sub(r'\btrue\b', 'true', json.dumps(v)))


T0 = dt.datetime(2026, 10, 8, 3, 30, tzinfo=dt.timezone.utc).timestamp()


def hours(now, temps=None, dps=None):
    h0 = now - now % 3600
    temps = temps or [64] * 12
    dps = dps or [52] * 12
    return [{'t': dt.datetime.fromtimestamp(h0 + 3600 * k, dt.timezone.utc).isoformat(),
             'temp': t, 'dp': d, 'precip': 0} for k, (t, d) in enumerate(zip(temps, dps))]


GOOD = {'sensor.ot': '64', 'sensor.odp': '52', 'sensor.it': '74', 'sensor.idp': '55', 'sensor.irh': '52'}
WARM = {**GOOD, 'sensor.ot': '80'}
VARS = dict(key='test', units='F', ot_e='sensor.ot', odp_e='sensor.odp', orh_e='', it_e='sensor.it',
            idp_e='sensor.idp', irh_e='sensor.irh', rr_e=[], rrecent_e=[], gust_e=[], pm_e=[],
            stats_e=[], stat_t_e=[], on_s=1200, off_s=600,
            limits_in={k: None for k in ['cold_open', 'gust', 'gust_stay']}, extreme_in={'hot': None, 'cold': None, 'dp': None})


def tick(prev, now, fake, fu=None, hrs=None, **over):
    v = {**VARS, **over, 'prev': prev, 'now_ts': now, 'FAKE': fake, 'FAKE_U': fu or {}, 'FAKE_A': over.pop('fa', {}),
         'hours': hrs if hrs is not None else hours(now), 'fetched_at': dt.datetime.fromtimestamp(now - 600, dt.timezone.utc).isoformat()}
    pre = ''.join(f"{{% set {k} = {lit(x)} %}}" for k, x in v.items())
    out = ast.literal_eval(render(pre + OUT).strip())
    # The attributes the sensor publishes, as the next tick's prev.
    nxt = {**out['sm'], 'last_tick': now, 'hazard_reason': out['hazard_reason'],
           'hazard_reason_since': out['hazard_reason_since'], 'extreme': out['extreme'],
           'extreme_since': out['extreme_since'], 'extreme_pending_since': out['extreme_pending_since'],
           'samples': out['samples']}
    return out, nxt


def run(seq, prev=None, start=T0, **kw):
    """seq: list of (minutes, fake); ticks every minute through each span."""
    prev = prev or {}
    now = start
    log = []
    for mins, fake in seq:
        for _ in range(mins):
            out, prev = tick(prev, now, fake, **kw)
            log.append((now, out))
            now += 60
    return log, prev, now


fails = 0


def check(name, cond, detail=''):
    global fails
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'  -- {detail}'))
    fails += not cond


r = subprocess.run([sys.executable, str(ROOT / 'climate' / 'build-window-advisor.py'), '--check'], capture_output=True, text=True)
check('blueprint decide() == climate/window_advisor.jinja', r.returncode == 0, r.stdout + r.stderr)

log, prev, now = run([(21, GOOD)])
check('good: pending on, not yet good at 19 min', log[19][1]['sm']['good'] is False and log[19][1]['sm']['pending'] == 'on', log[19][1]['sm'])
check('good: on at 20 min, good_since set', log[20][1]['sm']['good'] is True and log[20][1]['sm']['good_since'] == T0 + 1200, log[20][1]['sm'])
check('mode switches to stay on the transition tick', log[20][1]['d']['mode'] == 'stay', log[20][1]['d']['mode'])
check('first tick (no history) is false, not none', log[0][1]['sm']['good'] is False, log[0][1]['sm'])
log2, prev2, now2 = run([(11, WARM)], prev=prev, start=now)
check('bad: still good at 9 min', log2[9][1]['sm']['good'] is True and log2[9][1]['sm']['pending'] == 'off', log2[9][1]['sm'])
check('bad: off at 10 min, bad_since set', log2[10][1]['sm']['good'] is False and log2[10][1]['sm']['bad_since'] == now + 600, log2[10][1]['sm'])
check('mode back to open on the off tick', log2[10][1]['d']['mode'] == 'open', log2[10][1]['d']['mode'])
# Blind mid-good: missing indoor temp.
blind = {**GOOD, 'sensor.it': 'unavailable'}
log3, prev3, now3 = run([(2, blind), (2, GOOD)], prev=prev, start=now)
check('Blind: good -> none at once', log3[0][1]['sm']['good'] is None and log3[0][1]['sm']['blind_since'] == now, log3[0][1]['sm'])
check('after Blind: false and pending on again (no carry-over)', log3[2][1]['sm']['good'] is False and log3[2][1]['sm']['pending'] == 'on', log3[2][1]['sm'])
# Restart gap: 10 min pending, then a 5-min gap.
log4, prev4, now4 = run([(10, GOOD)])
out, _ = tick(prev4, now4 + 300, GOOD)
check('gap > 3 min resets pending', out['sm']['pending'] == 'on' and out['sm']['pending_since'] == now4 + 300, out['sm'])
# Blip: good 10 min, one bad tick, good again -> pending restarts.
log5, _, _ = run([(10, GOOD), (1, WARM), (21, GOOD)])
check('one bad tick restarts the on-timer', log5[30][1]['sm']['good'] is False and log5[31][1]['sm']['good'] is True, (log5[30][1]['sm'], log5[31][1]['sm']))
# Extreme: house 81 °F for 15 min, then 79.
hot = {**WARM, 'sensor.it': '81'}
log6, prev6, now6 = run([(16, hot), (1, {**hot, 'sensor.it': '79'})])
check('extreme off at 14 min', log6[14][1]['extreme'] is False and log6[14][1]['extreme_reason'] == 'House is 81°F', log6[14][1])
check('extreme on at 15 min', log6[15][1]['extreme'] is True and log6[15][1]['extreme_since'] == T0 + 900, log6[15][1]['extreme'])
check('extreme off immediately', log6[16][1]['extreme'] is False and log6[16][1]['extreme_since'] is None, log6[16][1]['extreme'])
# Hazards: rain then gusts -> the since stamp moves on a change of kind only.
hz = dict(rr_e=['sensor.rr'], gust_e=['sensor.gust'])
rain = {**GOOD, 'sensor.rr': '0.1', 'sensor.gust': '5'}
gusty = {**GOOD, 'sensor.rr': '0', 'sensor.gust': '35'}
log7, _, _ = run([(2, rain), (2, gusty), (1, {**gusty, 'sensor.gust': '5'})], **hz)
check('hazard rain, since stays put', log7[0][1]['hazard_reason'] == "It's raining" and log7[1][1]['hazard_reason_since'] == T0, [x[1]['hazard_reason_since'] for x in log7])
check('hazard changes kind -> new since', log7[2][1]['hazard_reason'] == 'Strong wind gusts' and log7[2][1]['hazard_reason_since'] == T0 + 120, log7[2][1])
check('hazard clears', log7[4][1]['hazard'] is False and log7[4][1]['hazard_reason_since'] is None, log7[4][1])
out, _ = tick({}, T0, {**GOOD, 'sensor.rr': '0', 'sensor.gust': '27'}, **hz)
check('27 mph is no hazard (stay limit 30)', out['hazard'] is False, out['hazard_reason'])
out, _ = tick({}, T0, {**GOOD, 'sensor.rr': '0', 'sensor.gust': '45'}, fu={'sensor.gust': 'km/h'}, **hz)
check('gust sensor in km/h: 45 km/h (28 mph) no hazard, decided in mph', out['hazard'] is False and out['d']['gates'][1]['unit'] == 'km/h', (out['hazard'], out['d']['gates'][1]))
# °C sensors, °F display: same decision as the °F readings.
cel = {'sensor.ot': '17.78', 'sensor.odp': '11.11', 'sensor.it': '23.33', 'sensor.idp': '12.78', 'sensor.irh': '52'}
cu = {k: '°C' for k in ['sensor.ot', 'sensor.odp', 'sensor.it', 'sensor.idp']}
f_, _ = tick({}, T0, GOOD)
c_, _ = tick({}, T0, cel, fu=cu)
check('°C sensors decide like °F', f_['d']['level'] == c_['d']['level'] and f_['d']['state'] == c_['d']['state'], (f_['d']['state'], c_['d']['state']))
# RH-derived dew point (no dew point sensors).
rh = {'sensor.ot': '64', 'sensor.orh': '65', 'sensor.it': '74', 'sensor.irh': '52'}
o, _ = tick({}, T0, rh, odp_e='', orh_e='sensor.orh', idp_e='')
odp = next(g for g in o['d']['gates'] if g['k'] == 'humid')['v']
check('outdoor dew point from RH (64 °F, 65 % -> ~52 °F)', abs(odp - 52.1) < 0.6 and not o['d']['state'].startswith('Blind'), (odp, o['d']['state']))
o, _ = tick({}, T0, {k: v for k, v in GOOD.items() if k != 'sensor.irh'}, irh_e='', idp_e='')
check('no indoor dew point and no RH -> Blind', o['d']['state'].startswith('Blind'), o['d']['state'])
# °C units: thresholds in °C, text in °C.
o, _ = tick({}, T0, {**GOOD, 'sensor.ot': '53'}, units='C', limits_in={'cold_open': 12.0})
check('°C: cold_open 12 °C (53.6 °F) blocks 53 °F, text in °C', o['d']['state'] == 'Too cold outside (12°C)', o['d']['state'])
o, _ = tick({}, T0, {**GOOD, 'sensor.ot': '54'}, limits_in={'cold_open': None})
check('empty threshold = default (55 °F blocks 54)', o['d']['state'] == 'Too cold outside (54°F)', o['d']['state'])

# --- review round 2 (2026-10-18) ---------------------------------------------
two = dict(rr_e=['sensor.rr1', 'sensor.rr2'], gust_e=['sensor.g1', 'sensor.g2'])
out, _ = tick({}, T0, {**GOOD, 'sensor.rr1': '0', 'sensor.rr2': '0.2', 'sensor.g1': '5', 'sensor.g2': 'unavailable'}, **two)
check('two rain sensors: the wet one counts', out['hazard_reason'] == "It's raining" and out['d']['state'] == 'Raining', (out['hazard_reason'], out['d']['state']))
out, _ = tick({}, T0, {**GOOD, 'sensor.rr1': '0', 'sensor.rr2': '0', 'sensor.g1': 'unavailable', 'sensor.g2': 'unavailable'}, **two)
check('all gust sensors unavailable -> Blind', out['d']['state'].startswith('Blind'), out['d']['state'])
rec = dict(rrecent_e=['binary_sensor.rained'])
out, _ = tick({}, T0, {**GOOD, 'binary_sensor.rained': 'unavailable'}, **rec)
check('rained-recently configured but unavailable -> Blind', out['d']['state'].startswith('Blind'), out['d']['state'])
out, _ = tick({}, T0, {**GOOD, 'binary_sensor.rained': 'on'}, **rec)
check('rained-recently on -> Raining', out['d']['state'] == 'Raining' and out['hazard'] is True, out['d']['state'])
out, _ = tick({}, T0, {**GOOD, 'binary_sensor.rained': 'off'}, **rec)
check('rained-recently off -> Good path', out['d']['state'] == 'Good', out['d']['state'])
_, p_ = tick({'good': None, 'bad_since': T0 - 99999, 'blind_since': T0 - 600, 'last_tick': T0 - 60}, T0, WARM)
check('back from Blind into blocked: new bad_since', p_['bad_since'] == T0 and p_['good'] is False, p_)
_, p_ = tick({'good': False, 'bad_since': T0 - 99999, 'last_tick': T0 - 60}, T0, WARM)
check('still blocked: bad_since kept', p_['bad_since'] == T0 - 99999, p_)
out, _ = tick({'extreme_pending_since': T0 - 3600, 'last_tick': T0 - 3500}, T0, {**WARM, 'sensor.it': '81'})
check('extreme pending does not survive a gap', out['extreme'] is False and out['extreme_pending_since'] == T0, out)
# forecast adapter: an hour without dew point or humidity keeps its rain
FRESH = next(a['variables']['fresh'] for a in BP['actions'] if 'variables' in a and 'fresh' in a['variables'])
fc = {'weather.x': {'forecast': [{'datetime': f'2026-10-08T0{k}:00:00+00:00', 'temperature': 64, 'humidity': 60, 'precipitation': 0} for k in range(4)]
                     + [{'datetime': '2026-10-08T04:00:00+00:00', 'temperature': 63, 'precipitation': 0.3}]}}
rows = ast.literal_eval(render(f"{{% set fetch = true %}}{{% set weather_e = 'weather.x' %}}{{% set fc = {lit(fc)} %}}" + FRESH).strip())
check('forecast: rainy hour without humidity kept (no dp key)', len(rows) == 5 and rows[-1]['precip'] == 0.3 and 'dp' not in rows[-1], rows[-1])

# --- heat headroom (moved from the hand-written sensor's tests) ---------------
STAT = {'climate.a': 'heat_cool', 'climate.b': 'heat_cool'}
FA = {'climate.a|target_temp_low': 68, 'climate.b|target_temp_low': 67, 'climate.a|friendly_name': 'Downstairs',
      'climate.b|friendly_name': 'Upstairs', 'climate.a|hvac_action': 'idle', 'climate.b|hvac_action': 'idle'}
def heat_run(temps_a, temps_b=None, fa=FA, mins=5, fake_extra=None, prev=None, **kw):
    """One tick every `mins` minutes; temps lists give each tick's reading (°F)."""
    prev = prev or {}
    now = T0
    out = None
    for k, ta in enumerate(temps_a):
        fake = {**WARM, **STAT, 'sensor.ta': str(ta), 'sensor.tb': str((temps_b or temps_a)[k]), **(fake_extra or {})}
        out, prev = tick(prev, now, fake, stats_e=['climate.a', 'climate.b'], stat_t_e=['sensor.ta', 'sensor.tb'], fa=fa, **kw)
        now += mins * 60
    return out, prev
line = [round(70 - 0.6 * k * 300 / 3600, 2) for k in range(19)]
o, _ = heat_run(line)
a_ = next(x for x in o['thermostats'] if x['name'] == 'Downstairs')
check('heat: least-squares rate', abs(a_['rate'] + 0.6) < 0.02 and o['heat_complete'], a_)
check('heat: proj = head + rate·1h', abs(a_['proj'] - (a_['head'] + a_['rate'])) < 0.02, a_)
check('heat: the decide input is the thermostat closest to heat', o['heat']['proj'] == min(x['proj'] for x in o['thermostats']), o['heat'])
o, _ = heat_run(line[:4])
check('heat: < 45 min of samples -> none (cold rule)', o['heat'] is None and not o['heat_complete'], o['heat'])
o, _ = heat_run(line, fake_extra={'sensor.tb': 'unavailable'})
check('heat: one thermostat without readings -> none', o['heat'] is None and not o['heat_complete'], (o['heat'], o['thermostats']))
o, _ = heat_run(line, fa={**FA, 'climate.a|hvac_action': 'cooling', 'climate.b|hvac_action': 'cooling'})
check('heat: AC ran in the window -> rate 0', all(x['rate'] == 0 and x['ac'] for x in o['thermostats']), o['thermostats'])
drop = [70.0] * 17 + [68.0, 68.0]
o, _ = heat_run(drop)
check('heat: reading never above the latest sample', a_ and next(x for x in o['thermostats'] if x['name'] == 'Downstairs')['temp'] == 68.0, o['thermostats'])
o2, _ = heat_run([72.0] * 19, fake_extra={'sensor.ot': '50', 'sensor.odp': '45', 'sensor.it': '72'})
check('heat: cold outside + headroom = Crack them', o2['d']['level'] == 'crack' and o2['d']['state'].startswith('Crack them'), o2['d']['state'])
o, _ = heat_run(line, fa={**FA, 'climate.a|target_temp_low': None}, fake_extra={'climate.a': 'off'})
check('heat: thermostat off is ignored, the other still counts', o['heat_complete'] and [x['name'] for x in o['thermostats']] == ['Upstairs'], o['thermostats'])
o, _ = heat_run([round((70 - 32) / 1.8 - 0.6 / 1.8 * k * 300 / 3600, 3) for k in range(19)], units='C',
                fa={**FA, 'climate.a|target_temp_low': 20, 'climate.b|target_temp_low': 19.4}, fu={'sensor.ta': '°C', 'sensor.tb': '°C'})
a_ = next(x for x in o['thermostats'] if x['name'] == 'Downstairs')
check('heat in °C: setpoint 20 °C = 68 °F, rate in °F/h inside', abs(a_['set'] - 68) < 0.01 and abs(a_['rate'] + 0.6) < 0.03, a_)
print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
