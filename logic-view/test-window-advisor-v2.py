#!/usr/bin/env python3
"""Unit cases for window advisor v2 (2026-10-08): decide() in
climate/window_advisor.jinja rendered by HA itself via /api/template, with
synthetic station readings and forecast hours. Covers the enthalpy gate, the
58/60 dew point cap, the bias-corrected projection, the outlook gate,
good_until and opens_around. Usage (after sourcing .env):
    python3 logic-view/test-window-advisor-v2.py"""
import json, math, os, re, sys, urllib.request, pathlib, datetime as dt

ROOT = pathlib.Path(__file__).resolve().parent.parent
env = os.environ
URL = f"http://{env['HA_IP']}:8123/api/template"
SRC = (ROOT / 'climate' / 'window_advisor.jinja').read_text()


def render(tpl):
    req = urllib.request.Request(URL, data=json.dumps({"template": tpl}).encode(),
        headers={"Authorization": "Bearer " + env['HA_TOKEN'], "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=60).read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HA {e.code}: {e.read().decode()[:800]}")


def jlit(o):
    return re.sub(r'\bnull\b', 'none', json.dumps(o))


def enth(t, dp):
    c = (dp - 32) * 5 / 9
    pv = 6.112 * math.exp(17.67 * c / (c + 243.5))
    w = 0.622 * pv / (1013.25 - pv)
    return 0.240 * t + w * (1061 + 0.444 * t)


# Fixed "now" on the half hour so interpolation is exercised; hours start at
# the top of the current hour like the real forecast.
NOW = dt.datetime(2026, 10, 8, 3, 30, tzinfo=dt.timezone.utc).timestamp()
H0 = NOW - 1800


def hours(temps, dps, precip=None):
    precip = precip or [0] * len(temps)
    return [{'t': dt.datetime.fromtimestamp(H0 + 3600 * k, dt.timezone.utc).isoformat(),
             'temp': t, 'dp': d, 'precip': p} for k, (t, d, p) in enumerate(zip(temps, dps, precip))]


# A cool, dry evening: everything passes in "open" mode.
BASE = {'ot': 64, 'odp': 52, 'it': 74, 'idp': 55, 'irh': 52, 'pm': 5, 'rr': 0, 'gust': 5}
FLAT = hours([64] * 12, [52] * 12)


def decide(raw=None, hrs=None, stay=False, now=NOW, rr_recent=False):
    raw = {k: str(v) for k, v in (raw or BASE).items()}
    hrs = FLAT if hrs is None else hrs
    fetched = dt.datetime.fromtimestamp(now - 600, dt.timezone.utc).isoformat()
    tpl = SRC + (f"{{{{ decide({jlit(raw)}, {jlit(hrs)}, {jlit(fetched)}, {now}, "
                 f"{'true' if stay else 'false'}, {'true' if rr_recent else 'false'}) }}}}")
    return json.loads(render(tpl))


def gate(d, k):
    return next(g for g in d['gates'] if g['k'] == k)


fails = 0


def check(name, cond, detail=''):
    global fails
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'  -- {detail}'))
    fails += not cond


# --- baseline -----------------------------------------------------------
d = decide()
check('baseline Good', d['state'] == 'Good', d['state'])
check('baseline good_until none (flat, holds 12 h)', d['good_until'] is None, d['good_until'])
check('baseline opens_around none while Good', d['opens_around'] is None)
check('baseline outlook_ok true, forecast_through = last hour', d['outlook_ok'] is True and d['forecast_through'] == FLAT[-1]['t'], (d['outlook_ok'], d['forecast_through']))
check('proj starts at station reading', d['proj'][0]['temp'] == 64 and d['proj'][0]['dp'] == 52, d['proj'][0])

# --- enthalpy gate --------------------------------------------------------
h_in = enth(74, 55)
e = gate(d, 'enthalpy')
check('enthalpy values match python', abs(e['v'] - round(enth(64, 52), 1)) < 0.06 and abs(e['vs'] - round(h_in, 1)) < 0.06, e)
# Warm-ish but dry out vs. humid in: pick odp so h_out sits just above / below h_in - 0.5.
for odp, want in [(56.0, None), (58.0, None)]:
    raw = dict(BASE, ot=70, odp=odp, it=74, idp=55)
    dd = decide(raw, hours([70] * 12, [odp] * 12))
    hv = enth(70, odp)
    exp_fail = hv > h_in - 0.5
    check(f'enthalpy fail={exp_fail} at 70/{odp} (h_out {hv:.2f} vs limit {h_in - 0.5:.2f})',
          gate(dd, 'enthalpy')['fail'] == exp_fail, gate(dd, 'enthalpy'))
# Stay mode limit is h_in + 0.5
raw = dict(BASE, ot=72, odp=56, it=74, idp=55)
dd = decide(raw, hours([72] * 12, [56] * 12), stay=True)
check('enthalpy stay limit = h_in + 0.5', abs(gate(dd, 'enthalpy')['t'] - round(h_in + 0.5, 1)) < 0.06, gate(dd, 'enthalpy'))
# The old "drier than inside" case: 62/57 outside vs 74/55 inside now passes.
raw = dict(BASE, ot=62, odp=57, it=74, idp=55)
dd = decide(raw, hours([62] * 12, [57] * 12))
check('62/57 vs 74/55 is Good (was blocked by drier-than-inside)', dd['state'] == 'Good', dd['state'])

# --- dew point cap --------------------------------------------------------
for odp, stay, want in [(58.0, False, False), (58.5, False, True), (60.0, True, False), (60.5, True, True)]:
    raw = dict(BASE, ot=60, odp=odp, it=76, idp=60, irh=55)
    dd = decide(raw, hours([60] * 12, [odp] * 12), stay=stay)
    check(f'humid cap {"stay" if stay else "open"} odp {odp} fail={want}', gate(dd, 'humid')['fail'] == want, gate(dd, 'humid'))

# --- projection / bias ----------------------------------------------------
# Forecast 60 at H0, 62 at H0+1h -> 61 at NOW (half past). Station reads 65 -> bias +4.
hrs = hours([60, 62, 64, 66] + [66] * 8, [50, 50, 51, 52] + [52] * 8)
raw = dict(BASE, ot=65, odp=52)
dd = decide(raw, hrs)
check('bias interpolated to now', dd['trend']['bias_temp'] == 4.0 and dd['trend']['bias_dp'] == 2.0, dd['trend'])
# now+2h = H0+2.5h -> forecast 65 -> projected 69; Δ +4
check('temp_2h from interpolated projection', dd['trend']['temp_2h'] == 4.0, dd['trend'])
check('proj hour shifted by bias', dd['proj'][1]['temp'] == 66.0 and dd['proj'][1]['dp'] == 52.0, dd['proj'][1])
# Now before the first hour: use the first hour.
dd = decide(raw, hours([60] * 12, [50] * 12), now=H0 - 600)
check('now before first hour uses first hour', dd['trend']['bias_temp'] == 5.0, dd['trend'])
# Projected dew point can't exceed projected temperature.
dd = decide(dict(BASE, ot=56, odp=55), hours([60, 50, 50] + [50] * 9, [50, 56, 56] + [56] * 9))
check('proj dp clamped to temp', all(p['dp'] <= p['temp'] for p in dd['proj']), dd['proj'][:3])
# Hours missing dp are skipped, not fatal.
hm = hours([64] * 12, [52] * 12)
for h in hm[3:5]: del h['dp']
dd = decide(None, hm)
check('hours missing dp tolerated', dd['state'] == 'Good' and len(dd['proj']) == 1 + 9, (dd['state'], len(dd['proj'])))

# --- outlook gate ----------------------------------------------------------
# Muggy air arrives within 2 h: dp 52 -> 62 by the second hour.
dd = decide(None, hours([64] * 12, [52, 56, 64] + [64] * 9))
o = gate(dd, 'outlook')
check('outlook fails when dp > 60 within 2 h', o['fail'] is True and 'too humid' in dd['state'], (o, dd['state']))
# Warming fast: 64 -> 80 in 2 h (inside 74 -> stay limit 75 / >74).
dd = decide(None, hours([64, 70, 80] + [80] * 9, [52] * 12))
check('outlook fails when too warm within 2 h', gate(dd, 'outlook')['fail'] is True and 'too warm' in dd['state'], dd['state'])
# Stay mode never checks the outlook.
dd = decide(None, hours([64] * 12, [52, 56, 64] + [64] * 9), stay=True)
check('outlook not checked in stay mode', gate(dd, 'outlook')['fail'] is False and dd['state'] == 'Good', (gate(dd, 'outlook'), dd['state']))
check('outlook_ok reported false in stay mode too', dd['outlook_ok'] is False, dd['outlook_ok'])
check('stay mode good_until = when it turns humid', dd['good_until'] is not None, dd['good_until'])
# Outlook only reports; the ladder still stops at the first earlier failure.
dd = decide(dict(BASE, ot=80), hours([80] * 12, [52] * 12))
check('earlier gate decides before outlook', gate(dd, 'warm')['fail'] and dd['decided'] == [g['k'] for g in dd['gates']].index('warm'), dd['decided'])

# --- opens_around -----------------------------------------------------------
# Warm now (78 > 72), cooling to 66 by +4 h and staying there, dry.
cool = hours([78, 76, 74, 71, 68, 66, 65, 64, 64, 64, 64, 64], [55] * 12)
dd = decide(dict(BASE, ot=78, odp=55), cool)
# Station 78 vs forecast 77 interpolated to :30 -> bias +1.
# Projected temps by hour: H0+3 = 70.5 -> first <= it−2 = 72 -> but the
# enthalpy check (h <= h_in − 0.5) and next-2-h stay must hold too.
exp = next(h['t'] for k, h in enumerate(cool) if k >= 1 and h['temp'] + 1 <= 72
           and enth(h['temp'] + 1, 55) <= enth(74, 55) - 0.5)
check('opens_around = first qualifying hour', dd['opens_around'] == exp, (dd['opens_around'], exp))
print('     opens_around =', dd['opens_around'], ' (proj temps', [p['temp'] for p in dd['proj']][:7], ')')
# Rain in the hour after -> pushed later.
wet = hours([78, 76, 74, 71, 68, 66, 65, 64, 64, 64, 64, 64], [55] * 12, [0, 0, 0, 0, 0, 0.1, 0, 0, 0, 0, 0, 0])
dd2 = decide(dict(BASE, ot=78, odp=55), wet)
check('rain near the window pushes opens_around later',
      dd2['opens_around'] is None or dd2['opens_around'] > (dd['opens_around'] or ''), (dd['opens_around'], dd2['opens_around']))
# Live hazard suppresses it.
dd = decide(dict(BASE, ot=78, odp=55, gust=30), cool)
check('opens_around none during a hazard', dd['opens_around'] is None, dd['opens_around'])
# House already cool -> no window will make sense.
dd = decide(dict(BASE, ot=78, odp=55, it=66), cool)
check('opens_around none when house is cool', dd['opens_around'] is None, dd['opens_around'])

# A forecast hour inside the window is checked, not just +1 h / +2 h:
# spike to 62 only at H0+2h (= now + 1.5 h), back to 52 after.
dd = decide(None, hours([64] * 12, [52, 52, 66, 52] + [52] * 8))
check('outlook catches a forecast hour between +1 h and +2 h', gate(dd, 'outlook')['fail'] is True, gate(dd, 'outlook'))
# Not a full dew point rise yet at +2 h -> holds.
dd = decide(None, hours([64] * 12, [52, 52, 57, 62] + [62] * 8))
check('outlook holds when dp only reaches 59.5 by +2 h', gate(dd, 'outlook')['fail'] is False and dd['state'] == 'Good', dd['state'])
check('reason text is stable (no clock)', 'within 2 h' in decide(None, hours([64] * 12, [52, 56, 64] + [64] * 9))['state'])

# --- rain intervals (Codex impl review) -----------------------------------
# At :30 open mode looks 3 h ahead -> rain in the hour starting H0+3 (= now+2.5 h) counts.
wet3 = hours([64] * 12, [52] * 12, [0, 0, 0, 0.1] + [0] * 8)
dd = decide(None, wet3)
check('open mode: rain starting now+2.5 h blocks', dd['state'] == 'Rain in the forecast', dd['state'])
# Exactly on the hour, the expired previous interval isn't counted.
prev = [{'t': dt.datetime.fromtimestamp(H0 - 3600, dt.timezone.utc).isoformat(), 'temp': 64, 'dp': 52, 'precip': 0.3}] + FLAT
dd = decide(None, prev, now=H0)
check('on the hour: previous wet interval ignored', dd['state'] == 'Good', dd['state'])
# Stay mode, rain in 90 min: still Good (2 h window, rain at H0+2 = now+1.5 h is inside!) -> check 2.5 h instead.
dd = decide(None, hours([64] * 12, [52] * 12, [0, 0, 0, 0.1] + [0] * 8), stay=True)
check('stay mode: rain at now+2.5 h -> Good but outlook ok', dd['state'] == 'Good' and dd['outlook_ok'] is True, (dd['state'], dd['outlook_ok']))
check('stay mode: good_until = start of the wet hour', dd['good_until'] == hours([64] * 4, [52] * 4)[3]['t'], dd['good_until'])
dd = decide(None, hours([64] * 12, [52] * 12, [0, 0, 0.1] + [0] * 9), stay=True)
check('stay mode: rain at now+1.5 h -> outlook_ok false', dd['outlook_ok'] is False and dd['state'] == 'Rain in the forecast', (dd['state'], dd['outlook_ok']))
# An hour missing its dew point still carries its rain.
hm = hours([64] * 12, [52] * 12, [0, 0, 0, 0, 0, 0.2] + [0] * 6)
del hm[5]['dp']
dd = decide(None, hm, stay=True)
check('rain kept on an hour missing dp (good_until)', dd['good_until'] == hm[5]['t'], dd['good_until'])
# Unknown rain inside the 2-h window -> outlook_ok unknown (blocks the push).
dd = decide(None, hours([64] * 12, [52] * 12, [0, None, 0] + [0] * 9), stay=True)
check('unknown rain in 2 h -> outlook_ok none', dd['outlook_ok'] is None and dd['state'] == 'Good', (dd['state'], dd['outlook_ok']))
# opens_around needs consecutive hours: drop the dp of the hour after the candidate.
gap = [dict(h) for h in cool]
del gap[5]['dp']
dd = decide(dict(BASE, ot=78, odp=55), gap)
check('opens_around skips a candidate whose hold spans a gap', dd['opens_around'] != cool[4]['t'], dd['opens_around'])
# No rain data at all -> Blind, not Good.
dd = decide(None, [dict(h, precip=None) for h in FLAT])
check('all-null precip -> Blind', dd['state'] == 'Blind: forecast has no rain data', dd['state'])
# Stay mode 75 out / 76 in passes live, breaks projected >74 now: good_until must not be "now".
dd = decide(dict(BASE, ot=75, it=76, idp=55), hours([75] * 12, [52] * 12), stay=True)
check('good_until never the synthetic now point', dd['state'] == 'Good' and dd['good_until'] != dd['proj'][0]['t'] and dd['good_until'] == dd['proj'][1]['t'], (dd['state'], dd['good_until']))
# opens_around uses the open PM limit (20) even in stay mode.
dd = decide(dict(BASE, ot=78, odp=55, pm=25), cool, stay=True)
check('opens_around none with PM 25', dd['opens_around'] is None, (dd['state'], dd['opens_around']))
# Fetch age boundary.
def aged(m):
    raw = {k: str(v) for k, v in BASE.items()}
    f = dt.datetime.fromtimestamp(NOW - 60 * m, dt.timezone.utc).isoformat()
    return json.loads(render(SRC + f"{{{{ decide({jlit(raw)}, {jlit(FLAT)}, {jlit(f)}, {NOW}, false, false) }}}}"))['state']
check('fetched 90 min ago still live, 91 stale', aged(90) == 'Good' and aged(91) == 'Blind: forecast is stale', (aged(90), aged(91)))

# --- blind / stale ----------------------------------------------------------
dd = decide(dict(BASE, odp='unavailable'))
check('missing input -> Blind, no opens_around', dd['state'].startswith('Blind') and dd['opens_around'] is None, dd['state'])
dd = decide(None, hours([64] * 2, [52] * 2))
check('2 forecast hours -> stale Blind', dd['state'] == 'Blind: forecast is stale', dd['state'])

hn = [{k: v for k, v in h.items() if k != 'dp'} for h in FLAT]
dd = decide(None, hn)
check('forecast without dew points -> Blind', dd['state'] == 'Blind: forecast projection unavailable', dd['state'])
# Coverage must reach now + 2 h: 3 hours from H0 end at H0+2h = now+1.5h.
dd = decide(None, hours([64] * 3, [52] * 3))
check('forecast ending before now+2h -> Blind', dd['state'] == 'Blind: forecast projection unavailable', dd['state'])
dd = decide(None, hours([64] * 4, [52] * 4))
check('forecast reaching now+2h is enough', dd['state'] == 'Good', dd['state'])

# --- sensor.window_forecast parsing (variables block rendered in HA) --------
import yaml
blk = yaml.safe_load((ROOT / 'climate' / 'window-advisor-templates.yaml').read_text())[0]['action'][2]['variables']
ts0 = 1791468000
nbm = {'status': 200, 'content': {'hourly': {'time': [ts0 + 3600 * k for k in range(14)],
       'temperature_2m': [70.0] * 14, 'dew_point_2m': [55.0] * 14,
       'precipitation': [0.5, 0, 0.2] + [0] * 11}}}
out = render(f"{{% set nbm = {jlit(nbm)} %}}{blk['nbm_hours']}")
check('NBM precip shifted to the following hour', "'precip': 0.2" in out.split('},')[1] and out.count("'t'") == 12, out[:240])
fc = {'weather.forecast_home': {'forecast': [{'datetime': '2026-10-08T14:00:00+00:00', 'temperature': 70, 'humidity': 60},
       {'temperature': 70, 'humidity': 60}, 'junk', {'datetime': '2026-10-08T15:00:00+00:00', 'temperature': 71, 'humidity': 60, 'precipitation': 0.1}]}}
out = render(f"{{% set nbm_hours = [] %}}{{% set fc = {jlit(fc)} %}}{blk['met_hours']}")
check('met.no fallback skips malformed hours, keeps missing precip as none', out.count("'t'") == 2 and "'precip': None" in out, out)
out = render(f"{{% set nbm_hours = [] %}}{{% set fc = {jlit({'weather.forecast_home': {}})} %}}{blk['met_hours']}")
check('met.no response without forecast list -> empty', out.strip() == '[]', out)

print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
