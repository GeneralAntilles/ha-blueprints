# HVAC health monitor, staleness watchdog, daily digest

Built 2026-09-27. Plan, measured facts and review history:
`~/.claude/plans/hvac-health-monitor.md`.

## What it does
- **Cooling cycles** (`hvac-monitor-automations.yaml` → `hvac_monitor_cooling_cycles`): finds real
  compressor starts/stops in whole-house per-leg power (Shelly 3EM) and checks them against the
  ecobee calls. Emits `hvac_monitor` events: `start`, `start_measured` (watts vs. the
  23 W/°F × outdoor − 21 model), `stop`, `blower` (ramp-down watts on leg B ~45 s after the stop),
  `mid_call_stop`, `changeover`, `no_start`, `no_restart`, `uncertain_stop`, `blower_missing`.
- **Heat calls** (learning): furnace power response per heat call; alerts after ≥10 samples.
- **Alerts**: 🚨 critical push for blower missing twice and ≥2 mid-call stops within an hour;
  no-start / no-restart / single mid-call stop / weak heat response are sent immediately in the
  daytime or held for 07:00 (released early if the house passes 80 °F or drops under 60 °F).
- **Staleness** (`staleness-calibrate.py` + `staleness-templates.yaml`): per-sensor tier labels
  from 1.5 × the longest gap between changes; `sensor.stale_sensors` lists sensors whose
  `last_reported` is older than their tier, grouped by device.
- **Digest** (`house_health_daily_digest`, 08:00): quiet sensors, yesterday's HVAC incidents, heavy
  short cycling (> 60 starts), filter age vs `input_number.hvac_filter_life_days`. and the 12x12x1
  MERV 12 fresh-air intake filter (8" wall ventilator) once `sensor.fresh_air_intake_filter_life_used`
  hits 100 %: a usage clock (`sensor.fresh_air_intake_filter_load`, equivalent days of blower time
  with `input_boolean.fresh_air_intake_open` on, weighted by outdoor PM10) vs
  `input_number.fresh_air_intake_filter_load_target` (180), or 365 calendar days, whichever first.
  Filter dates are stamped by "Log … Change" buttons on the Health tab (`hvac_monitor_filters_changed`,
  `fresh_air_intake_filter_changed`); the 2000-01-01 sentinel means never logged. Silent when clean.

## State
- `sensor.hvac_leg_buffer` — last 60 [ts, A, B] samples (recorder-excluded).
- `input_text.hvac_cycle` — the whole cycle state as compact JSON (keys documented in the automation).
- `sensor.hvac_monitor_log` — today/yesterday counts, run list, recent incidents, held queue,
  heat responses.

## Deploy
Templates: replace the `hvac monitor` and `staleness` marker blocks in `/Volumes/config/templates.yaml`,
then `template.reload`. Automations: POST each item to `/api/config/automation/config/<id>`.
Staleness labels: `python3 hvac-monitor/staleness-calibrate.py` (dry run) then `--apply`; re-run
monthly or after adding devices.

## Validation
The detector was replayed over 3 days / 171 ecobee calls in Python (165 starts, 164 stops, 4 failsafe,
0 false no-starts or mid-call stops), then the HA Jinja itself was replayed over a real 90-minute window
(glitch ignored, blower 170–179 W) and synthetic no-start / mid-call-no-restart / no-blower cases.

## Known limits
- Power-only v1: a dead **condenser fan** needs a CT on its lead (pinned hardware task). The Aprilaire
  24 V taps (Y/G/W, damper NO/NC) will replace inferred calls with real ones.
- Tesla charging start/stop within ±3 min masks a measurement (no alert).
- A call already running at first deploy or across a restart can't raise a no-start.
