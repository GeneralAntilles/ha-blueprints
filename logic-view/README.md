# Logic view (2026-09-30)

The Home dashboard's **Logic** tab shows how the house's heuristics decide, not
just what they decided. Each heuristic publishes a `*_trace` sensor: every check in
order with its live value, the threshold in force, the other mode's threshold,
and which check decided. `logic-trace-card.js` draws any such trace, and has
no thresholds of its own, so the view can't drift from the logic.

## Pieces
- `logic-trace-card.js`: custom card (plain JS, no build). Deployed to
  `/config/www/logic-view/`, Lovelace resource `/local/logic-view/logic-trace-card.js?v=N`.
  **Bump `v`** on every change (`lovelace/resources/update`); /local is cached for 31 days.
  Responsive: one tall column below 760 px of card width, ladder + side panel above; rows go
  name | rail | value once the ladder is ≥ 540 px. `legend: open` expands the rails key.
- Traces are recorder-excluded by the `sensor.*_trace` glob in configuration.yaml
  (added 2026-09-30, takes effect on the next HA restart).

## Traced so far
| Heuristic | Decision source | Trace |
|---|---|---|
| Window advisor | `climate/window_advisor.jinja` → `/config/custom_templates/` (`homeassistant.reload_custom_templates`) | `sensor.window_advice_trace` |
| Intake filter clock | `hvac-monitor/intake_filter.jinja` → `/config/custom_templates/` | `sensor.fresh_air_intake_filter_trace` (`kind: clock`) |
| Kitchen air exhaust | `climate/kitchen_air.jinja` (decide() pure + live()); the automation's start/end conditions call it (`d.start` / `d.end`) | `sensor.kitchen_air_exhaust_trace` (ladder; idle = start checks, running = keep-running checks) |
| HVAC health monitor | the detector automation itself (`hvac_monitor_cooling_cycles`), whose events echo the constants each decision tested | `sensor.hvac_cycle_trace` (`kind: cycle`) |
| Upstairs bath fan, laundry steamer | the blueprint automations themselves, **unchanged**: the card reads each automation's latest run trace (`trace/list` + `trace/get` over the websocket; admin only) | none: card `entity: automation.*` |

**Blueprint layout** (`entity: automation.*`). HA stores each run's evaluated variables block on
the trigger step (e.g. `trigger/23`, 91 variables for the bathroom controller) plus the room's
resolved `blueprint_inputs`. The card takes thresholds from those (variables first, since they carry
defaults; then inputs), live values from `hass.states`, and shows the blueprint's own
`humidity_settled_now` / `settled_now` from that run as the authority. The per-signal on/off
comparisons (bath > on, bath − reference > on offset, rate > rise; ≤ off / ≤ off offset) are drawn
by the card from those numbers; they mirror the blueprint's trigger templates, which can't be traced
individually. Refetches when the automation's `last_triggered` changes or every 60 s. Downstairs
bath has no humidity sensor configured (fan = manual timeout only), so it has no card.

`sensor.window_advice` and its trace both call `window_advice()`, the same macro.
`replay-intake-filter.py` does the same for the filter clock's `step()`/`life()` against
`intake-filter-v1.yaml` (1500 cases, 0 mismatches); the load, life-used and trace sensors all call `live()`.

`replay-kitchen-air.py` checks decide().start/end against the verbatim old conditions (2000 cases incl.
targeted PM-clearing cases, 0 mismatches).

`replay-window-advisor.py` checks `decide()` against the frozen pre-macro template
(`window-advice-v1.jinja`), with HA rendering both: 1500 random cases clustered on
every threshold, 0 mismatches. It pins v1 behaviour: since window advisor v2
(2026-10-08: enthalpy gate, 58/60 dew point cap, station-anchored forecast trend,
outlook gate, rain intervals) it no longer matches by design.
`test-window-advisor-v2.py` holds the v2 unit cases (51, rendered by HA). Re-run it
after editing the ladder.

## Trace shape (per gate)
`k, q, fail (true/false/null), reason, v, unit, t, t_alt, cmp ('>', '>=', '<'), lo, hi`,
plus optional `vs`/`vs_label` (the indoor value a moving limit is pinned to),
`rule`/`rule_alt` (plain-language moving limit), `hours` (per-hour pills), and `extra`.
Top level: `state, mode ('open'|'stay'), decided (index, -1 = Good/Blind), gates`.

## Layouts
- **Ladder** (default): ordered checks, first failing one stops it (window advisor).
- **Cycle** (`trace.kind == 'cycle'`): 90-min two-leg power plot fetched from HA history
  (`history/history_during_period`, cached 60 s) with cooling-call shading, detected-running bars
  and start/stop markers; the latest cycle's detector events as rows (start step vs `need_w`,
  start power vs the outdoor-temp model ±1σ, stop drop vs `need_w`, classification, blower vs
  `min_w`); today's run-length histogram with the zone panel's 4-min minimum.
- **Clock** (`trace.kind == 'clock'`): gates (blower AND intake) → air weight rail → per-minute
  increment → usage vs calendar bars. Accent: grey paused, green counting, red due.

## HVAC detector change (2026-09-30)
The detector's constants are now named once at the top of its `out` template (START_W 400,
BAL 0.35, STOP_MIN_W 300, STOP_FRAC 0.6, MODEL_A 23.0, MODEL_B 21, MODEL_SD 172, BLOWER_MIN_W 60)
and echoed in `start` / `start_measured` / `stop` / `blower` events. Decision logic unchanged:
old vs new rendered by HA on live data with stale-record replay (start, start_measured, stop,
blower, mid_call_stop all identical) before the push.

## Review (2026-09-30, Codex gpt-6.1-sol + Grok 4.5 on a scratchpad bundle)
Grok: adopted #1 (load accumulator falls back to a `last_good` attribute instead of resetting to 0 when
its state is non-numeric) and #2 (load/life call `step_live()`/`life_live()` only). Declined #3 (the bare
300 W settled-step floor is a different quantity from STOP_MIN_W; renaming needs another live detector
check), #8 (trace rendered fine on first trigger).
Codex: #1 already covered by Grok #2. Adopted #2 (a forecast hour missing its `precip` key put
Undefined into the window JSON; now `none`, and the replay generates missing keys; note
`map(attribute=..., default=none)` does NOT work, Jinja treats a None default as unset), #3 (minute
bucket in the card's render key so time-based text doesn't freeze when attributes are unchanged),
#4 (no_start/no_restart shown in the HVAC header), #5 (partial-trace guards), #6 (escaped ids).
Detector sampler final: 740 renders over 45 min, 0 mismatches (start 19, start_measured 124, stop 6,
blower 22, mid_call_stop 110).
