/*
 * Logic Trace Card (2026-09-30) - draws a heuristic's decision ladder from the
 * `trace` attribute its template publishes (see climate/window_advisor.jinja).
 * The card holds no thresholds of its own: everything it shows comes from the
 * trace, so it can't drift from the logic it explains.
 *
 * Source: ha-blueprints/logic-view/. Deployed to /config/www/logic-view/ and
 * registered as a Lovelace module resource (/local/logic-view/logic-trace-card.js?v=N;
 * bump v on every change - /local is cached for 31 days).
 *
 *   type: custom:logic-trace-card
 *   entity: sensor.window_advice_trace
 *   title: Window Advisor            # optional eyebrow
 *   legend: open                     # optional: start with the rails legend expanded
 */

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const isNum = (x) => typeof x === 'number' && isFinite(x);

// Unit -> [formatter, caption under the value].
const UNITS = {
  'in/h': [(v) => v.toFixed(2), 'in/h rain'],
  'mph': [(v) => Math.round(v), 'mph gusts'],
  'µg/m³ PM2.5': [(v) => Math.round(v), 'PM2.5 µg/m³'],
  'wet hours': [(v) => Math.round(v), 'wet hours'],
  '°F out': [(v) => `${Math.round(v)}°`, 'outside'],
  '°F in': [(v) => `${Math.round(v)}°`, 'inside'],
  '°F dew pt out': [(v) => `${Math.round(v)}°`, 'dew point outside'],
  '% RH in': [(v) => `${Math.round(v)}%`, 'humidity inside'],
  'BTU/lb out': [(v) => v.toFixed(1), 'BTU/lb outside (heat + moisture)'],
  '° over heat set': [(v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}°`, 'over heat setpoint in 1 h'],
  'µg/m³ rise': [(v) => `+${Math.round(v)}`, 'µg/m³ over 1-h low'],
  'min': [(v) => Math.round(v), 'minutes running'],
  'fans': [(v) => Math.round(v), 'fans owned'],
};
// Unit suffix for "value > limit" comparisons where the number alone is bare.
const SUFFIX = { 'mph': ' mph', 'µg/m³ PM2.5': ' µg/m³', 'in/h': ' in/h' };
const OPS = { '>': '>', '>=': '≥', '<': '<', '<=': '≤' };
const fmt = (v, unit) => (isNum(v) ? (UNITS[unit]?.[0] ?? ((x) => Math.round(x * 10) / 10))(v) : '—');
const caption = (unit) => UNITS[unit]?.[1] ?? unit;

// Terse "label (value > limit)" for the header's also-blocking list. Falls back
// to the long reason for traces without a short label.
const brief = (g) => {
  if (!g.short) return g.reason;
  if (!isNum(g.v) || !isNum(g.t) || (g.t === 0 && g.cmp === '>')) return g.short;
  return `${g.short} (${fmt(g.v, g.unit)} ${OPS[g.cmp] ?? g.cmp} ${fmt(g.t, g.unit)}${SUFFIX[g.unit] ?? ''})`;
};

class LogicTraceCard extends HTMLElement {
  static getStubConfig() {
    return { entity: 'sensor.window_advice_trace', title: 'Window Advisor' };
  }

  setConfig(config) {
    if (!config?.entity) throw new Error('logic-trace-card: entity is required');
    this._config = config;
    this._key = null;
    // Legend open/closed survives the once-a-minute redraw and page reloads
    // (per browser; storage can be unavailable, so it's best-effort).
    try { const v = localStorage.getItem(LEGEND_KEY); if (v !== null) this._legendOpen = v === '1'; } catch (e) { /* ignore */ }
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
      // The trace updates about once a minute and each render rebuilds the
      // card, which would kill an open tooltip. Hold updates while the
      // pointer is over the card; apply the latest one when it leaves.
      this.addEventListener('pointerenter', () => { this._hover = true; });
      this.addEventListener('pointerleave', () => {
        this._hover = false;
        if (this._pending) { const st = this._pending; this._pending = null; this._render(st); }
      });
    }
    if (this._hass) this.hass = this._hass;
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    // The minute bucket keeps time-based text (running minutes, the plot's
    // "now") fresh even when the trace's attributes don't change, since HA
    // doesn't bump last_updated for an identical re-render.
    const watch = (this._bpWatch ?? []).map((e) => hass.states[e]?.last_updated ?? '').join(',');
    const key = st ? `${st.last_updated}|${hass.themes?.darkMode}|${Math.floor(Date.now() / 60000)}|${watch}` : 'missing';
    if (key === this._key) return;
    this._key = key;
    if (this._hover && this.shadowRoot.firstChild) { this._pending = st; return; }
    this._render(st);
  }

  getCardSize() { return 14; }
  getGridOptions() { return { columns: 'full', min_columns: 6 }; }

  _render(st) {
    if (st?.entity_id?.startsWith('automation.')) { this._renderBlueprint(st); return; }
    const trace = st?.attributes?.trace;
    if (trace?.kind === 'clock' && trace.step && trace.life && isNum(trace.step.w) && isNum(trace.life.load)) {
      this._renderClock(st, trace); return;
    }
    if (trace?.kind === 'cycle') { this._renderCycle(st, trace); return; }
    if (!Array.isArray(trace?.gates) || typeof trace.state !== 'string'
        || trace.gates.some((g) => !g || typeof g !== 'object')) {
      this.shadowRoot.innerHTML = `${STYLE}<ha-card><ha-alert alert-type="info" title="No trace yet">
        ${esc(this._config.entity)} has no <code>trace</code> attribute. Check that its template published one.</ha-alert></ha-card>`;
      return;
    }
    const a = st.attributes;
    const { gates, decided, mode } = trace;
    const blind = trace.state.startsWith('Blind');
    const tone = trace.tone ?? (blind ? 'blind' : decided < 0 ? 'good' : 'blocked');
    const also = decided >= 0 ? gates.slice(decided + 1).filter((g) => g.fail) : [];
    const passed = gates.filter((g) => g.fail === false).length;

    // Traces may name their own kicker/icon/mode text; the window advisor
    // (the first ladder) relies on these defaults.
    const kicker = trace.kicker ?? { good: 'Open the windows', blocked: 'Keep them closed', blind: "Can't tell right now" }[tone];
    const headline = trace.kicker ? trace.state : tone === 'good' ? 'Every check passes' : trace.state;
    const icon = trace.icon ?? { good: 'mdi:window-open-variant', crack: 'mdi:window-open', blocked: 'mdi:window-closed-variant', blind: 'mdi:eye-off-outline' }[tone];
    const allPass = decided < 0 && !blind;

    const modeText = trace.mode_text ?? (mode === 'stay'
      ? '<b>Staying open</b> — windows are already good, so the looser stay-open limits apply. The gap between the two sets keeps the advice from flapping.'
      : '<b>Deciding whether to open</b> — windows aren’t open-worthy yet, so the stricter opening limits apply. They relax once conditions hold for 20 min.');

    const rows = gates.map((g, i) => this._row(g, i, decided, mode, a)).join('');
    const animate = !this._drawn;
    this._drawn = true;

    this.shadowRoot.innerHTML = `${STYLE}
<ha-card class="tone-${tone}${animate ? ' animate' : ''}">
  <header>
    <div class="emblem"><ha-icon icon="${icon}"></ha-icon></div>
    <div class="head">
      <div class="eyebrow">${esc(this._config.title ?? 'Logic')}</div>
      <div class="kicker">${kicker}</div>
      <h1>${esc(headline)}</h1>
      ${also.length ? `<p class="also-line"><span>Also blocking:</span> ${also.map((g) => esc(brief(g))).join(' <i>·</i> ')}</p>` : ''}
      ${(trace.summary ?? a.summary) ? `<p class="summary">${esc(trace.summary ?? a.summary)}</p>` : ''}
    </div>
  </header>
  ${blind ? `<ha-alert alert-type="warning" title="Flying blind">${esc(trace.state.replace(/^Blind: /, ''))}. The advisor won’t guess,
    so there’s no advice until that data is back. Checks it can’t evaluate show a dashed <b>?</b>.</ha-alert>` : ''}

  <div class="cols">
  <div class="mode mode-${esc(mode)}"><span class="chip">${esc(trace.mode_label ?? (mode === 'stay' ? 'STAY MODE' : 'OPEN MODE'))}</span><span>${modeText}</span></div>

  <div class="board"><div class="scoreboard">
    <span><b>${gates.length}</b> checks, top to bottom</span>
    <span class="sb-pass"><b>${passed}</b> pass</span>
    <span class="sb-fail"><b>${gates.filter((g) => g.fail).length}</b> fail</span>
    <span>stops at the first <b class="x">✕</b></span>
  </div>

  </div>
  <ol class="ladder">${rows}
    <li class="gate terminal ${allPass ? 's-pass decider' : 's-na after'}">
      <span class="node"></span>
      <div class="body"><div class="qcell"><span class="q">${esc(trace.terminal ?? 'All clear → “Good”')}</span></div>
      <span class="val muted">${allPass ? 'reached' : 'not reached'}</span></div>
    </li>
  </ol>

  <div class="side">${this._strip(a, gates, tone === 'good' || tone === 'crack', trace)}${key(this._legendOpen ?? this._config.legend === 'open')}</div>
  </div>

  <footer>
    Live from <code>${esc(this._config.entity)}</code> · updated <ha-relative-time></ha-relative-time>
  </footer>
</ha-card>`;
    this._hooks(st);
  }

  // After any render: legend state + relative time.
  _hooks(st) {
    this.shadowRoot.querySelector('details.key')?.addEventListener('toggle', (e) => {
      this._legendOpen = e.target.open;
      try { localStorage.setItem(LEGEND_KEY, e.target.open ? '1' : '0'); } catch (err) { /* ignore */ }
    });
    const rel = this.shadowRoot.querySelector('ha-relative-time');
    if (rel) { rel.hass = this._hass; rel.datetime = new Date(st.last_updated); }
  }

  // Blueprint automations (entity: automation.*): the card reads the
  // automation's latest run trace, which records every variable the
  // blueprint evaluated plus the room's resolved inputs, so the blueprint
  // itself stays untouched. Live sensor values come from hass.states.
  async _loadBp(st) {
    if (this._bpLoading) return;
    this._bpLoading = true;
    try {
      const id = st.attributes.id;
      const list = await this._hass.callWS({ type: 'trace/list', domain: 'automation', item_id: id });
      const last = [...list].sort((a, b) => (a.timestamp.start < b.timestamp.start ? -1 : 1)).at(-1);
      if (!last) throw new Error('no stored runs yet');
      const t = await this._hass.callWS({ type: 'trace/get', domain: 'automation', item_id: id, run_id: last.run_id });
      // The variables block is recorded on the trigger step with the most variables.
      let vars = {};
      for (const [path, steps] of Object.entries(t.trace ?? {})) {
        const cv = steps?.[0]?.changed_variables;
        if (path.startsWith('trigger') && cv && Object.keys(cv).length > Object.keys(vars).length) vars = cv;
      }
      const ub = t.blueprint_inputs?.use_blueprint ?? {};
      this._bp = { at: Date.now(), lt: st.attributes.last_triggered, run: last.timestamp.start,
        trigger: last.trigger, path: ub.path ?? '', inputs: ub.input ?? {}, vars };
      this._bpErr = null;
    } catch (e) {
      this._bpErr = e.message ?? String(e);
      this._bp = this._bp ?? null;
    } finally {
      this._bpLoading = false;
      this._render(this._hass.states[this._config.entity]);
    }
  }

  _renderBlueprint(st) {
    const stale = !this._bp || this._bp.lt !== st.attributes.last_triggered || Date.now() - this._bp.at > 60e3;
    if (stale) this._loadBp(st);
    if (!this._bp) {
      this.shadowRoot.innerHTML = `${STYLE}<ha-card>${this._bpErr
        ? `<ha-alert alert-type="warning" title="Can’t read this automation’s runs">${esc(this._bpErr)}</ha-alert>`
        : '<div class="pw-wait">Reading the automation’s last run…</div>'}</ha-card>`;
      return;
    }
    const { vars: V, inputs: I, path } = this._bp;
    const hs = this._hass.states;
    const num = (e) => (e && isNum(parseFloat(hs[e]?.state)) ? parseFloat(hs[e].state) : null);
    const pick = (...xs) => xs.find((x) => x !== undefined && x !== null && x !== '');
    const steamer = path.includes('steamer');
    const animate = !this._drawn;
    this._drawn = true;

    // Inputs as the blueprint resolved them (variables carry defaults; inputs only what's set).
    const humEnts = pick(V.humidity_sensors, V.tv_humidity_sensors, I.humidity_sensors) ?? [];
    const refEnt = pick(V.reference_humidity_sensor, V.tv_reference, I.reference_humidity_sensor) ?? '';
    const derEnt = pick(V.humidity_derivative_sensor, V.tv_derivative, I.humidity_derivative_sensor) ?? '';
    const onThr = parseFloat(pick(V.tv_on_threshold, I.humidity_on_threshold));
    const offThr = parseFloat(pick(V.humidity_off_threshold, V.tv_off_threshold, I.humidity_off_threshold));
    const refOn = parseFloat(pick(V.tv_ref_on_offset, I.reference_on_offset));
    const refOff = parseFloat(pick(V.reference_off_offset, V.tv_ref_off_offset, I.reference_off_offset));
    const rise = parseFloat(pick(V.derivative_rise_rate, V.tv_rise_rate, I.derivative_rise_rate));
    const fanEnts = pick(V.fan_entities, I.fan_entities) ?? [];
    const flag = pick(V.fan_auto_flag, I.fan_auto_flag) ?? '';
    const purge = parseFloat(pick(I.fan_purge_minutes, V.fan_purge_minutes));
    const minRt = parseFloat(pick(V.fan_min_runtime, I.fan_min_runtime));
    const maxRt = parseFloat(pick(V.fan_max_runtime, I.fan_max_runtime));
    const manualTo = parseFloat(pick(V.tv_fan_manual_timeout, I.fan_manual_timeout, 0));
    const showerFlag = pick(V.shower_active_flag, I.shower_active_flag) ?? '';
    this._bpWatch = [...humEnts, refEnt, derEnt, ...fanEnts, flag, showerFlag,
      V.power_sensor, V.running_flag, V.plug_cut_flag, V.plug_switch, ...(V.motion_sensors ?? [])].filter(Boolean);

    // Live values
    const humVals = humEnts.map(num).filter(isNum);
    const bath = humVals.length ? Math.max(...humVals) : null;
    const ref = num(refEnt);
    const rate = num(derEnt);
    const fansOn = fanEnts.map((e) => hs[e]).filter((s) => s?.state === 'on');
    const fanOn = fansOn.length > 0;
    const fanMin = fanOn ? (Date.now() - Math.max(...fansOn.map((s) => Date.parse(s.last_changed)))) / 60e3 : 0;
    const owned = flag && hs[flag]?.state === 'on';
    const settledRun = pick(V.humidity_settled_now, V.settled_now);
    const runAt = new Date(this._bp.run).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    const fanConfigured = V.fan_configured !== false && fanEnts.length > 0;
    const humidityConfigured = humEnts.length > 0;

    // One humidity signal with hysteresis: fail zone above "on", settled zone at/below "off".
    const signal = (i, key, q, v, on, off, unit, lo, hi, what) => {
      const hasOff = isNum(off);
      const zone = !isNum(v) ? 's-na' : v > on ? 's-fail' : hasOff ? (v <= off ? 's-pass' : 's-op') : 's-pass';
      const state = !isNum(v) ? 'no data' : v > on ? 'wants the fan' : hasOff && v > off ? 'between' : 'settled';
      const pct = (x) => clamp(((x - lo) / (hi - lo)) * 100, 0, 100);
      const f = (x) => `${Math.round(x * 10) / 10}${unit}`;
      const id = (p) => esc(`b-${key}-${p}`);
      const viz = `<div class="track"><span class="rail"></span>
        <span class="zone" style="left:${pct(on)}%;width:${100 - pct(on)}%"></span>
        ${hasOff ? `<span class="zone ok" style="left:0;width:${pct(off)}%"></span><span class="tick alt" id="${id('off')}" style="left:${pct(off)}%"></span>` : ''}
        <span class="tick" id="${id('on')}" style="left:${pct(on)}%"></span>
        ${isNum(v) ? `<span class="dot ${zone === 's-fail' ? '' : zone === 's-pass' ? '' : 'neutral'}" id="${id('v')}" style="left:${pct(v)}%"></span>` : ''}</div>
        <ha-tooltip for="${id('on')}" placement="top">Turns the fan on above <b>${f(on)}</b></ha-tooltip>
        ${hasOff ? `<ha-tooltip for="${id('off')}" placement="top">Settled at or below <b>${f(off)}</b></ha-tooltip>` : ''}
        ${isNum(v) ? `<ha-tooltip for="${id('v')}" placement="top">Now: <b>${f(v)}</b></ha-tooltip>` : ''}`;
      return `
    <li class="gate ${zone} before" style="--i:${i}">
      <span class="node">${zone === 's-fail' ? '↑' : zone === 's-pass' ? '✓' : zone === 's-op' ? '~' : '?'}</span>
      <div class="body"><div class="qcell"><span class="q">${q}</span><span class="badge ${zone === 's-fail' ? '' : zone === 's-pass' ? 'ok' : 'mid'}">${state}</span></div>
        <span class="val">${isNum(v) ? f(v) : '—'}<small>${esc(what)}</small></span><div class="viz">${viz}</div>
        <div class="meta">on above <b>${f(on)}</b>${hasOff ? ` · settled at or below <b>${f(off)}</b>` : ''}</div></div>
    </li>`;
    };
    const plain = (i, cls, sym, q, val, cap, viz, meta, badge = '') => `
    <li class="gate ${cls} before" style="--i:${i}"><span class="node">${sym}</span>
      <div class="body"><div class="qcell"><span class="q">${q}</span>${badge}</div>
        <span class="val">${val}<small>${cap}</small></span><div class="viz">${viz}</div><div class="meta">${meta}</div></div></li>`;
    const railMin = (id, v, marks, hi) => {
      const pct = (x) => clamp((x / hi) * 100, 0, 100);
      return `<div class="track"><span class="rail"></span>
        ${marks.map((m) => `<span class="tick ${m.alt ? 'alt' : ''}" id="${esc(id + m.k)}" style="left:${pct(m.t)}%"></span>${m.zone ? `<span class="zone" style="left:${pct(m.t)}%;width:${100 - pct(m.t)}%"></span>` : ''}`).join('')}
        <span class="dot neutral" style="left:${pct(v)}%"></span></div>
        ${marks.map((m) => `<ha-tooltip for="${esc(id + m.k)}" placement="top">${m.tip}</ha-tooltip>`).join('')}`;
    };

    const rows = [];
    let i = 0;
    // ---- steamer: is it running, and would it be cut? ----
    let steamerHead = null;
    if (steamer) {
      const pw = num(V.power_sensor), onW = parseFloat(V.on_watts), idleW = parseFloat(V.idle_watts);
      const running = hs[V.running_flag]?.state === 'on';
      const cut = hs[V.plug_cut_flag]?.state === 'on';
      const runMin = running ? (Date.now() - Date.parse(hs[V.running_flag].last_changed)) / 60e3 : 0;
      const ms = (V.motion_sensors ?? []).map((e) => hs[e]).filter(Boolean);
      const motionOn = ms.some((m) => m.state === 'on');
      const idleMin = motionOn || !ms.length ? 0 : (Date.now() - Math.max(...ms.map((m) => Date.parse(m.last_changed)))) / 60e3;
      const noMo = parseFloat(V.no_motion_minutes), maxS = parseFloat(V.steamer_max_runtime);
      rows.push(`<li class="section-h">${esc(V.appliance_name ?? 'Appliance')}</li>`);
      rows.push(plain(i++, isNum(pw) && pw > onW ? 's-pass' : 's-op', isNum(pw) && pw > onW ? '⚡' : '·', 'Drawing power',
        isNum(pw) ? `${Math.round(pw)} W` : '—', 'plug meter', railMin('s-pw', pw ?? 0, [
          { k: 'on', t: onW, tip: `Running above <b>${onW} W</b>` }, { k: 'idle', t: idleW, alt: true, tip: `Idle below <b>${idleW} W</b>` }], Math.max(onW * 3, (pw ?? 0) * 1.1)),
        `running above <b>${onW} W</b> · stops after ${V.off_delay} s below <b>${idleW} W</b>`));
      rows.push(plain(i++, running ? 's-pass' : 's-op', running ? '✓' : '·', 'Running', running ? `${Math.round(runMin)} min` : 'No', running ? 'since start' : '',
        running ? railMin('s-rt', runMin, [{ k: 'max', t: maxS, zone: true, tip: `Plug cut at <b>${maxS} min</b>` }], maxS * 1.15) : '',
        `plug cut if it runs past <b>${maxS} min</b>`));
      rows.push(plain(i++, !running ? 's-op' : idleMin >= noMo ? 's-fail' : 's-pass', motionOn ? '✓' : '·', 'Someone nearby', motionOn ? 'Motion' : `${Math.round(idleMin)} min`, motionOn ? 'now' : 'since motion',
        running ? railMin('s-mo', idleMin, [{ k: 'cut', t: noMo, zone: true, tip: `Cut after <b>${noMo} min</b> without motion while running` }], noMo * 1.5) : '',
        `while running, the plug is cut after <b>${noMo} min</b> with no motion${running ? '' : ' (only matters while running)'}`));
      rows.push(plain(i++, cut ? 's-fail' : 's-pass', cut ? '✕' : '✓', 'Plug', cut ? 'Cut' : 'On', cut ? 'abandon cutoff' : '',
        '', cut ? 'the next person in the room re-enables it (probe first)' : 'normally on; the appliance’s own switch stays the control'));
      steamerHead = cut ? ['Plug cut', 'Steamer was left running'] : running ? ['Steaming', `Running ${Math.round(runMin)} min`] : null;
    }
    // ---- fan ----
    if (fanConfigured) {
      rows.push(`<li class="section-h">Exhaust fan</li>`);
      if (humidityConfigured) {
        const sensorName = (e) => (hs[e]?.attributes?.friendly_name ?? e).replace(/ (Current )?Humidity$/i, '');
        rows.push(signal(i++, 'hum', 'Humidity', bath, onThr, offThr, '%', 30, 100, 'in the room'));
        if (refEnt && isNum(refOn)) rows.push(signal(i++, 'ref', 'Above reference', isNum(bath) && isNum(ref) ? bath - ref : null, refOn, refOff, ' pts', -10, 40,
          `vs ${isNum(ref) ? Math.round(ref) + '%' : '—'} ${sensorName(refEnt).replace(/ (Thermostat|Sensor).*$/i, '')}`));
        if (derEnt && isNum(rise)) rows.push(signal(i++, 'der', 'Rising', rate, rise, null, '%/min', -2, rise * 3, 'rate'));
        rows.push(plain(i++, settledRun ? 's-pass' : 's-op', settledRun ? '✓' : '~', 'Settled', settledRun ? 'Yes' : 'Not yet', `at ${runAt}`, '',
          `the blueprint’s own check at its last run${steamer ? ' (needs the steamer stopped too)' : ''} · the fan turns off once this holds ${isNum(purge) ? `${purge} min` : 'for the purge time'}`));
      }
      rows.push(plain(i++, fanOn ? 's-pass' : 's-op', fanOn ? '✓' : '·', 'Fan on', fanOn ? `${Math.round(fanMin)} min` : 'Off', fanOn ? 'running' : '',
        fanOn && isNum(maxRt) ? railMin('f-rt', fanMin, [
          ...(isNum(minRt) ? [{ k: 'min', t: minRt, alt: true, tip: `Can’t turn off before <b>${minRt} min</b>` }] : []),
          { k: 'max', t: maxRt, zone: true, tip: `Turns off at <b>${maxRt} min</b> regardless` }], maxRt * 1.1) : '',
        `${isNum(minRt) ? `not turned off before <b>${minRt} min</b> · ` : ''}${isNum(maxRt) ? `off at <b>${maxRt} min</b> regardless` : ''}`));
      rows.push(plain(i++, owned ? 's-pass' : fanOn ? 's-op' : 's-op', owned ? '✓' : '·', 'Who turned it on', owned ? 'Automation' : fanOn ? 'Someone' : '—', '',
        '', owned ? 'it will turn the fan off when the checks above say so'
          : `a fan someone turns on by hand is left alone${manualTo > 0 ? `, except the <b>${manualTo}-min</b> manual timeout` : ''}`));
      if (showerFlag) {
        const hold = hs[showerFlag]?.state === 'on';
        const holdMin = hold ? (Date.now() - Date.parse(hs[showerFlag].last_changed)) / 60e3 : 0;
        rows.push(plain(i++, hold ? 's-pass' : 's-op', hold ? '🚿' : '·', 'Shower hold', hold ? `${Math.round(holdMin)} min` : 'Off', hold ? 'held' : '',
          '', hold ? `holding the fan; released once humidity settles${isNum(minRt) ? ` (not before ${minRt} min)` : ''}` : 'set by the shower buttons or rising humidity'));
      }
    }

    const tone = steamerHead?.[0] === 'Plug cut' ? 'blocked' : fanOn || steamerHead ? 'good' : 'paused';
    const wants = humidityConfigured && ((isNum(bath) && bath > onThr) || (refEnt && isNum(bath) && isNum(ref) && bath - ref > refOn) || (derEnt && isNum(rate) && rate > rise));
    const kicker = steamerHead ? steamerHead[0] : steamer && !fanOn ? `${V.appliance_name ? V.appliance_name[0].toUpperCase() + V.appliance_name.slice(1) : 'Appliance'} idle` : fanOn ? (owned ? 'Fan running' : 'Fan on by hand') : 'Fan off';
    const headline = steamerHead ? steamerHead[1]
      : fanOn ? (owned ? (settledRun ? 'Humidity settled, purging' : 'Waiting for humidity to settle') : manualTo > 0 ? `Manual, off after ${manualTo} min` : 'Manual, left alone')
      : wants ? 'Humidity is high' : fanConfigured ? 'Nothing needs the fan' : 'No humidity control here';
    const summary = [isNum(bath) && `Humidity ${Math.round(bath)}%`, isNum(ref) && `reference ${Math.round(ref)}%`,
      `last run ${runAt} (${esc(this._bp.trigger ?? '')})`].filter(Boolean).join(' · ');

    this.shadowRoot.innerHTML = `${STYLE}
<ha-card class="tone-${tone}${animate ? ' animate' : ''}">
  <header>
    <div class="emblem"><ha-icon icon="${steamer ? 'mdi:iron-outline' : 'mdi:fan'}"></ha-icon></div>
    <div class="head">
      <div class="eyebrow">${esc(this._config.title ?? st.attributes.friendly_name ?? 'Logic')}</div>
      <div class="kicker">${esc(kicker)}</div>
      <h1>${esc(headline)}</h1>
      <p class="summary">${summary}</p>
    </div>
  </header>
  <div class="cols bp">
    <ol class="ladder">${rows.join('')}</ol>
    <div class="side"><div class="explain"><div class="key-title">How it decides</div>
      ${steamer ? `<p>The plug stays on and the steamer’s own switch is the control. Power above <b>${V.on_watts} W</b> marks it running. If it keeps running with nobody around, the plug is cut.</p>` : ''}
      ${humidityConfigured ? `<p>Each humidity signal has two limits: above the <b>solid</b> tick it turns the fan on, at or below the <b>dotted</b> tick it counts as settled. In between it holds whatever it’s doing, so the fan doesn’t flap.</p>` : ''}
      <p>Read from the automation’s own run trace: the values its blueprint evaluated plus this room’s settings, so this view uses exactly what the automation used.</p>
    </div></div>
  </div>
  <footer>From <code>${esc(st.entity_id)}</code>’s last run · updated <ha-relative-time></ha-relative-time></footer>
</ha-card>`;
    this._hooks({ last_updated: this._bp.run });
  }

  // Compressor cycle (kind: 'cycle'): the detector's own events for the
  // latest cycle, each shown against the threshold the detector echoed,
  // plus a power plot from HA history and today's run-length histogram.
  _renderCycle(st, tr) {
    const ev = (Array.isArray(tr.events) ? tr.events : []).filter((e) => e?.data && typeof e.data === 'object');
    const rec = tr.rec ?? {};
    const running = rec.p === 'r';
    const now = Date.now() / 1000;
    const animate = !this._drawn;
    this._drawn = true;

    // Latest cycle = the last 'start' and everything after it.
    const si = ev.map((e) => e.kind).lastIndexOf('start');
    const cyc = si >= 0 ? ev.slice(si) : [];
    const find = (k) => cyc.find((e) => e.kind === k);
    const start = find('start'), meas = find('start_measured'), stop = find('stop');
    const verdictEv = cyc.find((e) => ['blower', 'mid_call_stop', 'changeover', 'uncertain_stop'].includes(e.kind));
    const blower = find('blower');
    const runMin = stop?.data?.run_min ?? find('uncertain_stop')?.data?.run_min;
    const runs = [...(tr.runs_today ?? [])].sort((x, y) => x - y);
    const median = runs.length ? runs[Math.floor(runs.length / 2)] : null;

    const verdict = !verdictEv ? null : {
      blower: ['Normal stop', 'the call had ended 150 s after the drop'],
      mid_call_stop: ['Stopped mid-call', 'the call was still on 150 s after the drop; usually the zone panel’s 40 °F supply-air cutoff'],
      changeover: ['Changeover', 'a heat call took over'],
      uncertain_stop: ['Uncertain stop', 'failsafe: the call had been off over 6 min with no clean drop'],
    }[verdictEv.kind];
    // A missed start/restart after the latest cycle outranks everything else.
    const fault = ev.slice(si + 1).filter((e) => ['no_start', 'no_restart'].includes(e.kind)).at(-1)
      ?? (si < 0 ? ev.filter((e) => ['no_start', 'no_restart'].includes(e.kind)).at(-1) : undefined);
    const tone = fault || (verdictEv && verdictEv.kind !== 'blower') ? 'blocked' : running ? 'good' : 'paused';
    const kicker = fault ? 'Compressor didn’t start' : running ? 'Compressor running' : 'Compressor idle';
    const headline = fault
      ? (fault.kind === 'no_start' ? `No start after ${fault.data.call_min ?? '?'} min of cooling call`
        : `No restart ${fault.data.since_min ?? '?'} min after a mid-call stop`)
      : running
      ? `Running ${Math.max(0, Math.round((now - rec.s) / 60))} min`
      : runMin != null ? `Last run ${runMin} min${verdict ? ` · ${verdict[0].toLowerCase()}` : ''}` : 'Waiting for a cycle';

    const W = (v) => `${Math.round(v)} W`;
    const pend = (i, q, why) => `
    <li class="gate s-na after" style="--i:${i}"><span class="node">·</span>
      <div class="body"><div class="qcell"><span class="q">${q}</span></div><span class="val muted">${why}</span></div></li>`;
    const row = (i, ok, q, val, cap, viz, meta, badge = '') => `
    <li class="gate ${ok === null ? 's-op' : ok ? 's-pass' : 's-fail'} before" style="--i:${i}">
      <span class="node">${ok === null ? '·' : ok ? '✓' : '✕'}</span>
      <div class="body"><div class="qcell"><span class="q">${q}</span>${badge}</div>
        <span class="val">${val}<small>${cap}</small></span><div class="viz">${viz}</div><div class="meta">${meta}</div></div>
    </li>`;
    // Rail with a "needs at least" tick: shaded below the need, dot at the value.
    const needRail = (id, v, need, hi) => {
      const pct = (x) => clamp((x / hi) * 100, 0, 100);
      return `<div class="track"><span class="rail"></span>
        ${isNum(need) ? `<span class="zone" style="left:0;width:${pct(need)}%"></span><span class="tick" id="${id}-t" style="left:${pct(need)}%"></span>` : ''}
        <span class="dot" id="${id}-v" style="left:${pct(v)}%"></span></div>
        ${isNum(need) ? `<ha-tooltip for="${id}-t" placement="top">Needs ≥ <b>${W(need)}</b></ha-tooltip>` : ''}
        <ha-tooltip for="${id}-v" placement="top">Measured <b>${W(v)}</b></ha-tooltip>`;
    };

    const rows = [];
    if (start) {
      const { rise_a: ra, rise_b: rb, need_w: need, bal_max: bal } = start.data;
      const lo = Math.min(ra, rb), imb = Math.abs(ra - rb) / Math.max(ra, rb);
      rows.push(row(0, true, 'Both legs stepped up', `+${W(lo)}`, 'smaller leg', needRail('c-st', lo, need, Math.max(2000, lo * 1.2)),
        `A +${W(ra)} · B +${W(rb)}` + (isNum(need) ? ` · needs ≥ ${W(need)} on each, within ${Math.round(bal * 100)}% of each other (were ${Math.round(imb * 100)}%)` : '')
        + ` · ${new Date(start.t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`));
    } else rows.push(pend(0, 'Both legs stepped up', 'no start recorded yet'));
    if (meas) {
      const d = meas.data, sd = d.model_sd;
      const hasModel = isNum(d.model_a);
      const lo = d.expected - 4 * (sd ?? 250), hi = d.expected + 4 * (sd ?? 250);
      const pct = (x) => clamp(((x - lo) / (hi - lo)) * 100, 0, 100);
      const viz = `<div class="track"><span class="rail"></span>
        ${isNum(sd) ? `<span class="zone flat" style="left:${pct(d.expected - sd)}%;width:${pct(d.expected + sd) - pct(d.expected - sd)}%"></span>` : ''}
        <span class="tick" id="c-m-t" style="left:${pct(d.expected)}%"></span><span class="dot neutral" id="c-m-v" style="left:${pct(d.watts)}%"></span></div>
        <ha-tooltip for="c-m-t" placement="top">Model: <b>${W(d.expected)}</b> at ${Math.round(d.tout)}°F</ha-tooltip>
        <ha-tooltip for="c-m-v" placement="top">Measured <b>${W(d.watts)}</b></ha-tooltip>`;
      rows.push(row(1, null, 'Start power vs model', W(d.watts), 'both legs',
        viz, (hasModel ? `model ${d.model_a} × ${Math.round(d.tout)}°F − ${d.model_b} = <b>${W(d.expected)}</b>` : `model <b>${W(d.expected)}</b> at ${Math.round(d.tout)}°F`)
          + ` · ${d.residual >= 0 ? '+' : '−'}${W(Math.abs(d.residual))}` + (isNum(sd) ? ` (${(d.residual / sd).toFixed(1)}σ; shaded ±1σ)` : '')));
    } else rows.push(pend(1, 'Start power vs model', running ? 'measured 60 s after the start' : '—'));
    if (stop) {
      const d = stop.data;
      if (isNum(d.drop_a)) {
        const lo = Math.min(d.drop_a, d.drop_b);
        rows.push(row(2, true, 'Both legs dropped', `−${W(lo)}`, 'smaller leg', needRail('c-sp', lo, d.need_w, Math.max(2000, lo * 1.2)),
          `A −${W(d.drop_a)} · B −${W(d.drop_b)} · needs ≥ max(${d.stop_min_w}, ${d.stop_frac} × ${W(d.step_w)} step) = ${W(d.need_w)} on each, held 30 s`));
      } else rows.push(row(2, true, 'Both legs dropped', `${d.run_min} min`, 'run', '', 'recorded before the detector echoed its thresholds'));
    } else rows.push(pend(2, 'Both legs dropped', running ? 'still running' : '—'));
    if (verdict) rows.push(row(3, verdictEv.kind === 'blower', verdict[0], runMin != null ? `${runMin} min` : '', 'run', '', verdict[1]));
    else rows.push(pend(3, 'Classified', stop ? 'at 150 s after the drop' : '—'));
    if (blower) {
      const d = blower.data;
      rows.push(row(4, d.confident ? d.watts >= (d.min_w ?? 60) : null, 'Blower wound down', W(d.watts), 'leg B', d.confident ? needRail('c-bl', d.watts, d.min_w, 400) : '',
        `leg B 5–40 s vs 65–110 s after the drop` + (d.confident ? ` · flagged missing below ${W(d.min_w ?? 60)} twice in a row (streak ${d.streak})` : ` · not counted: ${esc(d.why)}`)));
    } else rows.push(pend(4, 'Blower wound down', verdictEv && verdictEv.kind !== 'blower' ? 'only measured after a normal stop' : '—'));

    // Today's run lengths, 1-min bins, with the panel's fixed minimum marked.
    const maxBin = 20, bins = new Array(maxBin + 1).fill(0);
    runs.forEach((r) => { bins[Math.min(maxBin, Math.floor(r))] += 1; });
    const peak = Math.max(1, ...bins);
    const hist = `
  <section class="hist">
    <div class="key-title">Today’s runs</div>
    <div class="hist-sum"><b>${tr.starts_today ?? runs.length}</b> starts${median != null ? ` · median <b>${median} min</b>` : ''}
      <span>digest flags over ${tr.digest_starts}/day</span></div>
    <div class="hist-plot">
      ${bins.map((c, i) => `<span class="hb${i < tr.panel_min_on ? ' below' : ''}" style="height:${(c / peak) * 100}%" title="${i}${i === maxBin ? '+' : `–${i + 1}`} min: ${c}"></span>`).join('')}
      <span class="panel-line" style="left:${(tr.panel_min_on / (maxBin + 1)) * 100}%"><em>zone panel’s<br>${tr.panel_min_on}-min minimum</em></span>
    </div>
    <div class="hist-axis">${[0, 5, 10, 15, 20].map((m) => `<span style="left:${((m + 0.5) / (maxBin + 1)) * 100}%">${m === maxBin ? `${m}+ min` : m}</span>`).join('')}</div>
  </section>`;

    this.shadowRoot.innerHTML = `${STYLE}
<ha-card class="tone-${tone}${animate ? ' animate' : ''} cycle">
  <header>
    <div class="emblem"><ha-icon icon="mdi:heat-pump-outline"></ha-icon></div>
    <div class="head">
      <div class="eyebrow">${esc(this._config.title ?? 'Logic')}</div>
      <div class="kicker">${kicker}</div>
      <h1>${esc(headline)}</h1>
      <p class="also-line"><span>Detected from</span> whole-house power: the compressor is the only 240 V load that steps both legs together.</p>
    </div>
  </header>
  <div class="cols">
    <div class="ladder-wrap">
      <section class="power"><div class="strip-head"><span>Last 90 minutes</span>
        <span class="legend"><i class="lg-a"></i>leg A <i class="lg-b"></i>leg B <i class="lg-call"></i>cooling call <i class="lg-run"></i>detected running</span></div>
        <div class="pw" id="pw"><div class="pw-wait">loading history…</div></div></section>
      <ol class="ladder">${rows.join('')}</ol>
    </div>
    <div class="side">${hist}</div>
  </div>
  <footer>Live from <code>${esc(this._config.entity)}</code> · updated <ha-relative-time></ha-relative-time></footer>
</ha-card>`;
    this._hooks(st);
    this._power(tr);
  }

  // Power history for the plot, cached for a minute across the per-minute redraws.
  async _power(tr) {
    const draw = () => { const el = this.shadowRoot.getElementById('pw'); if (el && this._pw) el.innerHTML = this._powerSvg(tr, this._pw.data); };
    draw();
    if (this._pw && Date.now() - this._pw.at < 60e3) return;
    if (this._pwLoading) return;
    this._pwLoading = true;
    try {
      const end = new Date(), startT = new Date(end - 90 * 60e3);
      const ids = Object.values(tr.series);
      const res = await this._hass.callWS({ type: 'history/history_during_period', start_time: startT.toISOString(),
        end_time: end.toISOString(), entity_ids: ids, minimal_response: true, no_attributes: true });
      const pts = (id) => (res[id] ?? []).map((p) => [(p.lu ?? p.lc ?? Date.parse(p.last_updated ?? p.last_changed) / 1000), p.s ?? p.state]);
      this._pw = { at: Date.now(), data: { from: startT / 1000, to: end / 1000,
        a: pts(tr.series.a), b: pts(tr.series.b), call: pts(tr.series.call), run: pts(tr.series.running) } };
      draw();
    } catch (e) {
      const el = this.shadowRoot.getElementById('pw');
      if (el) el.innerHTML = `<div class="pw-wait">history unavailable (${esc(e.message ?? e)})</div>`;
    } finally { this._pwLoading = false; }
  }

  _powerSvg(tr, d) {
    const W = 600, H = 170, top = 8, bot = 150;
    const x = (t) => ((t - d.from) / (d.to - d.from)) * W;
    const num = (arr) => arr.map(([t, v]) => [t, parseFloat(v)]).filter(([, v]) => isNum(v));
    const A = num(d.a), B = num(d.b);
    if (!A.length || !B.length) return '<div class="pw-wait">no power history</div>';
    const ymax = Math.max(1000, ...A.map((p) => p[1]), ...B.map((p) => p[1])) * 1.08;
    const y = (v) => bot - (v / ymax) * (bot - top);
    // Step lines: each sample holds until the next one.
    const path = (arr) => arr.map(([t, v], i) => `${i ? `H${x(t).toFixed(1)}V` : `M${x(Math.max(t, d.from)).toFixed(1)},`}${y(v).toFixed(1)}`).join('') + `H${W}`;
    const spans = (arr, on) => {
      const out = []; let s0 = null;
      arr.forEach(([t, v]) => { const o = on(v); if (o && s0 === null) s0 = Math.max(t, d.from); if (!o && s0 !== null) { out.push([s0, t]); s0 = null; } });
      if (s0 !== null) out.push([s0, d.to]);
      return out;
    };
    const call = spans(d.call, (v) => parseFloat(v) >= 1).map(([a, b]) => `<rect class="call" x="${x(a)}" y="0" width="${Math.max(1, x(b) - x(a))}" height="${bot}"/>`).join('');
    const run = spans(d.run, (v) => v === 'on').map(([a, b]) => `<rect class="run" x="${x(a)}" y="${bot + 6}" width="${Math.max(1, x(b) - x(a))}" height="8" rx="2"/>`).join('');
    const marks = (tr.events ?? []).filter((e) => e.t >= d.from && ['start', 'stop', 'mid_call_stop', 'uncertain_stop'].includes(e.kind))
      .map((e) => `<line class="mk mk-${e.kind === 'start' ? 'start' : 'stop'}" x1="${x(e.t)}" x2="${x(e.t)}" y1="${top}" y2="${bot}"/>`).join('');
    const ticks = [0, 30, 60, 90].map((m) => `<span style="left:${(x(d.to - (90 - m) * 60) / W) * 100}%">${m === 90 ? 'now' : `−${90 - m} min`}</span>`).join('');
    const kw = (v) => (v >= 1000 ? `${(v / 1000).toFixed(1)} kW` : `${Math.round(v)} W`);
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      ${call}${run}
      <line class="grid" x1="0" x2="${W}" y1="${y(ymax / 2)}" y2="${y(ymax / 2)}"/>
      <path class="l-a" d="${path(A)}"/><path class="l-b" d="${path(B)}"/>${marks}
    </svg><span class="ylab" style="top:${(y(ymax / 2) / H) * 100}%">${kw(ymax / 2)}</span><div class="hours pw-axis">${ticks}</div>`;
  }

  // Usage clock (kind: 'clock'): is it loading -> how dirty is the air ->
  // what it adds -> usage vs calendar. Same row vocabulary as the ladder.
  _renderClock(st, tr) {
    const { step, life, thermostats } = tr;
    const due = life.pct >= 100;
    // Paused is a normal state (intake closed on purpose), so it gets a
    // neutral accent: green only while counting, red once a change is due.
    const tone = due ? 'blocked' : step.counting ? 'good' : 'paused';
    const running = (thermostats ?? []).filter((t) => ['cooling', 'heating', 'fan'].includes(t.action));
    const date = (ts) => (isNum(ts) ? new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) : '—');
    const animate = !this._drawn;
    this._drawn = true;

    const why = step.counting
      ? `Blower on (${running.map((t) => `${esc(t.name)} ${esc(t.action)}`).join(', ')}) and intake open, air ×${step.w.toFixed(2)}`
      : [!step.open && 'intake closed', !step.blower && 'blower off'].filter(Boolean).join(' and ');
    const kicker = due ? 'Change the filter' : step.counting ? 'Loading now' : 'Paused';

    const gateRow = (i, ok, q, val, viz, meta) => `
    <li class="gate ${ok ? 's-pass' : 's-fail'} ${step.counting ? 'before' : ok ? 'before' : 'decider'}" style="--i:${i}">
      <span class="node">${ok ? '✓' : '✕'}</span>
      <div class="body"><div class="qcell"><span class="q">${q}</span>${!ok ? '<span class="badge">pauses it</span>' : ''}</div>
        <span class="val">${val}</span><div class="viz">${viz}</div><div class="meta">${meta}</div></div>
    </li>`;
    const opRow = (i, sym, q, val, cap, viz, meta) => `
    <li class="gate s-op ${step.counting ? 'before' : 'after'}" style="--i:${i}">
      <span class="node">${sym}</span>
      <div class="body"><div class="qcell"><span class="q">${q}</span></div>
        <span class="val">${val}<small>${cap}</small></span><div class="viz">${viz}</div><div class="meta">${meta}</div></div>
    </li>`;

    const pills = (thermostats ?? []).map((t) => {
      const on = ['cooling', 'heating', 'fan'].includes(t.action);
      return `<span class="pill ${on ? 'on' : ''}"><ha-icon icon="${on ? 'mdi:fan' : 'mdi:fan-off'}"></ha-icon>${esc(t.name)}<small>${esc(t.action)}</small></span>`;
    }).join('');

    // PM weight rail: 0-40 µg/m³, floor and cap regions shaded, ×1 at the reference.
    const lo = 0, hi = 40, pct = (x) => clamp(((x - lo) / (hi - lo)) * 100, 0, 100);
    const floorAt = tr.ref_pm10 * tr.w_min, capAt = tr.ref_pm10 * tr.w_max;
    const pm = step.pm10;
    const weightViz = `<div class="track"><span class="rail"></span>
      <span class="zone flat" style="left:0;width:${pct(floorAt)}%"></span>
      <span class="zone flat" style="left:${pct(capAt)}%;width:${100 - pct(capAt)}%"></span>
      <span class="tick" id="m-ref" style="left:${pct(tr.ref_pm10)}%"></span>
      ${isNum(pm) ? `<span class="dot neutral" id="m-pm" style="left:${pct(pm)}%"></span>` : ''}</div>
      <ha-tooltip for="m-ref" placement="top">PM10 ${tr.ref_pm10}: counts ×1</ha-tooltip>
      ${isNum(pm) ? `<ha-tooltip for="m-pm" placement="top">Now: PM10 <b>${pm.toFixed(1)}</b> → ×${step.w.toFixed(2)}</ha-tooltip>` : ''}`;

    const perMin = step.w / tr.day_min;
    const bar = (label, have, of, unit, pctv, lead, note) => `
      <div class="bar ${lead ? 'lead' : ''}">
        <span class="bar-label">${label}${lead ? '<span class="badge">sets the clock</span>' : ''}</span>
        <span class="meter"><i style="width:${clamp(pctv, 0, 100)}%"></i></span>
        <span class="bar-val"><b>${Math.round(pctv)}%</b><small>${have} / ${of} ${unit}</small></span>
        ${note ? `<span class="bar-note">${note}</span>` : ''}
      </div>`;

    const main = `
  <ol class="ladder">
    ${gateRow(0, step.blower, 'Blower running', step.blower ? 'Yes' : 'No', `<div class="pills">${pills}</div>`,
      'either thermostat cooling, heating or running the fan')}
    ${gateRow(1, step.open, 'Intake open', step.open ? 'Open' : 'Closed', '',
      'manual toggle for now; the motorized damper will drive it')}
    ${opRow(2, '×', 'Outdoor air weight', `×${step.w.toFixed(2)}`, isNum(pm) ? `PM10 ${pm.toFixed(1)} µg/m³` : 'no PM data (×1)', weightViz,
      `PM10 ÷ ${tr.ref_pm10}, held between ×${tr.w_min} and ×${tr.w_max} (shaded ends)`)}
    ${opRow(3, '+', 'Adds', step.counting ? `+${perMin.toFixed(4)}` : '+0', 'eq-days / min', '',
      step.counting ? `one equivalent day per ${Math.round(tr.day_min / 60 / step.w)} h of blower at this air` : `nothing while paused (would be +${perMin.toFixed(4)})`)}
  </ol>
  <section class="bars">
    ${bar('Usage', life.load.toFixed(2), life.target, 'eq-days', life.usage_pct, life.limit === 'usage', '')}
    ${bar('Calendar', life.age_days ?? 0, tr.backstop_days, 'days', life.cal_pct, life.limit === 'calendar',
      life.due_by ? `due by ${date(life.due_by)} at the latest` : 'no change logged yet')}
    <div class="bars-foot">Change when either bar fills.</div>
  </section>`;

    const side = `
  <div class="explain">
    <div class="key-title">Equivalent days</div>
    <p>One equivalent day is a peak-summer day: <b>12 h of blower</b> with the intake open at <b>PM10 ${tr.ref_pm10}</b>.
      Dirtier air counts faster (up to ×${tr.w_max}), cleaner air slower (down to ×${tr.w_min}). Nothing counts while the intake is closed.</p>
    <p>Target <b>${life.target} eq-days</b>, about six months of summer. The ${tr.backstop_days}-day backstop covers a damp filter going musty before it loads up.</p>
  </div>`;

    this.shadowRoot.innerHTML = `${STYLE}
<ha-card class="tone-${tone}${animate ? ' animate' : ''} clock">
  <header>
    <div class="emblem"><ha-icon icon="mdi:air-filter"></ha-icon></div>
    <div class="head">
      <div class="eyebrow">${esc(this._config.title ?? 'Logic')}</div>
      <div class="kicker">${kicker}</div>
      <h1>${life.pct}% used</h1>
      <p class="also-line"><span>${step.counting ? 'Counting:' : 'Not counting:'}</span> ${why}</p>
      <p class="summary">Changed ${date(life.changed)} · ${life.age_days ?? 0} days ago</p>
    </div>
  </header>
  <div class="cols">${main}<div class="side">${side}</div></div>
  <footer>Live from <code>${esc(this._config.entity)}</code> · updated <ha-relative-time></ha-relative-time></footer>
</ha-card>`;
    this._hooks(st);
  }

  _row(g, i, decided, mode, attrs) {
    // soft: passes, but limits how far to open (window advisor "crack them").
    const status = g.fail === true ? 's-fail' : g.soft ? 's-soft' : g.fail === false ? 's-pass' : 's-na';
    const pos = decided < 0 ? 'before' : i < decided ? 'before' : i === decided ? 'decider' : 'after';
    const badge = pos === 'decider' ? '<span class="badge">stops here</span>'
      : pos === 'after' && g.fail ? '<span class="badge also">also blocks</span>'
      : g.soft ? '<span class="badge soft">crack only</span>' : '';
    const otherMode = mode === 'open' ? 'to stay open' : 'to open';

    let meta;
    if (!isNum(g.t)) {
      meta = esc(g.note ?? '');
    } else if (g.rule) {
      meta = `limit ${esc(g.rule)} = <b>${fmt(g.t, g.unit)}</b>`
        + (g.rule_alt !== g.rule ? ` <span class="alt">· ${mode === 'open' ? 'stay open' : 'open'}: ${esc(g.rule_alt)}</span>` : '');
    } else if (g.t === 0 && g.cmp === '>') {
      meta = g.k === 'forecast' ? 'any rain in the window fails' : 'any rain fails';
    } else {
      const word = { '>': 'fails above', '>=': 'fails at', '<': 'fails below', '<=': 'fails at or below' }[g.cmp] ?? g.cmp;
      meta = `${word} <b>${fmt(g.t, g.unit)}</b>` + (g.t_alt !== g.t ? ` <span class="alt">· ${fmt(g.t_alt, g.unit)} ${otherMode}</span>` : '');
    }
    if (g.note && isNum(g.t)) meta += ` <span class="alt">· ${esc(g.note)}</span>`;
    if (g.extra) meta += ` <span class="extra">${esc(g.extra)}</span>`;
    if (g.fail === null) meta = 'no data — the advice goes Blind rather than guess';

    const viz = Array.isArray(g.hours) ? this._hours(g, attrs) : this._track(g, mode);
    return `
    <li class="gate ${status} ${pos}" style="--i:${i}">
      <span class="node">${g.fail === true ? '✕' : g.soft ? '~' : g.fail === false ? '✓' : '?'}</span>
      <div class="body">
        <div class="qcell"><span class="q">${esc(g.q)}</span>${badge}</div>
        <span class="val">${fmt(g.v, g.unit)}<small>${esc(caption(g.unit))}</small></span>
        <div class="viz">${viz}</div>
        <div class="meta">${meta}</div>
      </div>
    </li>`;
  }

  // Number line: fail zone shaded, active limit solid, other mode's limit dashed.
  _track(g, mode) {
    if (!isNum(g.t)) return '';
    const span = g.hi - g.lo || 1;
    const pct = (x) => clamp(((x - g.lo) / span) * 100, 0, 100);
    const t = pct(g.t);
    const zone = g.cmp === '<' || g.cmp === '<=' ? `left:0;width:${t}%` : `left:${t}%;width:${100 - t}%`;
    const id = (part) => esc(`m-${g.k}-${part}`);
    const tips = [];
    const tip = (part, text) => tips.push(`<ha-tooltip for="${id(part)}" placement="top" show-delay="80">${text}</ha-tooltip>`);
    const other = mode === 'open' ? 'Stay-open limit' : 'Opening limit';

    tip('t', `Limit now: <b>${esc(fmt(g.t, g.unit))}</b>${g.rule ? ` (${esc(g.rule)})` : ''}`);
    let alt = '';
    if (isNum(g.t_alt) && g.t_alt !== g.t) {
      alt = `<span class="tick alt" id="${id('alt')}" style="left:${pct(g.t_alt)}%"></span>`;
      tip('alt', `${other}: <b>${esc(fmt(g.t_alt, g.unit))}</b>${g.rule_alt ? ` (${esc(g.rule_alt)})` : ''}`);
    }
    let vs = '';
    if (isNum(g.vs)) {
      vs = `<span class="vs" id="${id('vs')}" style="left:${pct(g.vs)}%"></span>`;
      tip('vs', `${esc(g.vs_label[0].toUpperCase() + g.vs_label.slice(1))}: <b>${esc(fmt(g.vs, g.unit))}</b>`);
    }
    let dot = '';
    if (isNum(g.v)) {
      const clipped = g.v < g.lo || g.v > g.hi ? ' clipped' : '';
      dot = `<span class="dot${clipped}" id="${id('v')}" style="left:${pct(g.v)}%"></span>`;
      tip('v', `Now: <b>${esc(fmt(g.v, g.unit))}</b> ${esc(caption(g.unit))}${clipped ? ' (off the scale)' : ''}`);
    }
    return `<div class="track"><span class="rail"></span><span class="zone" style="${zone}"></span>${alt}`
      + `<span class="tick" id="${id('t')}" style="left:${t}%"></span>${vs}${dot}</div>${tips.join('')}`;
  }

  // Forecast gate: one pill per hour in its look-ahead window.
  _hours(g, attrs) {
    const now = Date.now();
    const hours = (attrs.hours ?? []).filter((h) => Date.parse(h.t) >= now - 3600e3);
    const pills = g.hours.map((p, k) => {
      // v2 traces name each interval's start (hour_t); older ones align by index.
      const t = Array.isArray(g.hour_t) ? g.hour_t[k] : hours[k]?.t;
      const label = t && isFinite(Date.parse(t)) ? new Date(t).toLocaleTimeString([], { hour: 'numeric' }) : `+${k}h`;
      const wet = isNum(p) && p > 0;
      return `<span class="pill ${wet ? 'wet' : 'dry'}"><ha-icon icon="${wet ? 'mdi:weather-pouring' : 'mdi:weather-cloudy'}"></ha-icon>${esc(label)}${wet ? `<small>${p.toFixed(2)}″</small>` : ''}</span>`;
    }).join('');
    return `<div class="pills">${pills}</div>`;
  }

  // 12-hour strip: temperature and dew point on one °F axis, the dew point
  // limit, rain bars, and where "good until" falls. When the trace carries
  // `proj` (forecast shape anchored on the station's reading) that is drawn
  // instead of the raw forecast, with indoor temp / dew point as dashed
  // references, the 2-hour outlook window shaded and "likely good" marked.
  _strip(attrs, gates, showUntil, trace = {}) {
    const corrected = Array.isArray(trace.proj) && trace.proj.length >= 3;
    const hours = (corrected ? trace.proj : (attrs.hours ?? []).filter((h) => Date.parse(h.t) >= Date.now() - 3600e3))
      .filter((h) => isNum(h.temp) && isNum(h.dp) && isFinite(Date.parse(h.t))).slice(0, 13);
    if (hours.length < 3) return '';
    const humid = gates.find((g) => g.k === 'humid');
    const inT = trace.indoor?.temp, inD = trace.indoor?.dp;
    const vals = hours.flatMap((h) => [h.temp, h.dp]).concat([humid?.t, inT, inD].filter(isNum));
    const lo = Math.floor(Math.min(...vals) - 3), hi = Math.ceil(Math.max(...vals) + 3);
    const W = 600, H = 150, top = 12, bot = 118, n = hours.length;
    const t0 = Date.parse(hours[0].t), tN = Date.parse(hours[n - 1].t);
    const xt = (ms) => clamp(((ms - t0) / (tN - t0 || 1)) * W, 0, W);
    const x = (k) => xt(Date.parse(hours[k].t));
    const y = (v) => bot - ((v - lo) / (hi - lo)) * (bot - top);
    const line = (key) => hours.map((h, k) => `${k ? 'L' : 'M'}${x(k).toFixed(1)},${y(h[key]).toFixed(1)}`).join('');
    const area = (key) => `${line(key)}L${W},${bot}L0,${bot}Z`;
    const maxP = Math.max(0.1, ...hours.map((h) => (isNum(h.precip) ? h.precip : 0)));
    const bars = hours.map((h, k) => (isNum(h.precip) && h.precip > 0
      ? `<rect class="rain" x="${x(k) - 9}" y="${H - 4 - (h.precip / maxP) * 26}" width="18" height="${(h.precip / maxP) * 26}" rx="3"/>` : '')).join('');
    const hline = (v, cls) => (isNum(v) ? `<line class="${cls}" x1="0" x2="${W}" y1="${y(v)}" y2="${y(v)}"/>` : '');
    const limit = hline(humid?.t, 'limit');
    const refs = corrected ? hline(inT, 'ref ref-temp') + hline(inD, 'ref ref-dp') : '';
    const soon = corrected ? `<rect class="soon" x="0" y="${top - 8}" width="${xt(t0 + 2 * 3600e3)}" height="${bot - top + 8}"/>` : '';
    const mark = (t, cls) => {
      if (!t) return '';
      const k = hours.findIndex((h) => h.t === t || Date.parse(h.t) >= Date.parse(t));
      return k >= 0 ? `<line class="${cls}" x1="${x(k)}" x2="${x(k)}" y1="${top - 8}" y2="${H}"/>` : '';
    };
    const until = showUntil ? mark(trace.good_until ?? attrs.good_until, 'until') : '';
    const opens = !showUntil && corrected ? mark(trace.opens_around, 'opens') : '';
    const tr = trace.trend ?? {};
    const sgn = (v) => `${v >= 0 ? '+' : '−'}${Math.abs(Math.round(v))}°`;
    const sub = corrected && isNum(tr.bias_temp)
      ? `<p class="strip-sub">Forecast shape, anchored on the backyard station (${sgn(tr.bias_temp)} temp, ${sgn(tr.bias_dp)} dew pt vs ${esc(attrs.source === 'nbm' ? 'NBM' : attrs.source ?? 'forecast')})${
        isNum(tr.temp_2h) ? ` · next 2 h: outside ${sgn(tr.temp_2h)}, dew pt ${sgn(tr.dp_2h)}` : ''}${
        trace.opens_around ? ` · could open around <b>${esc(new Date(trace.opens_around).toLocaleTimeString([], { hour: 'numeric' }))}</b>` : ''}</p>` : '';
    const last = hours[n - 1];
    const labels = hours.map((h, k) => (k % 3 === 0 || k === n - 1)
      ? `<span style="left:${(x(k) / W) * 100}%">${esc(k === 0 ? 'now' : new Date(h.t).toLocaleTimeString([], { hour: 'numeric' }))}</span>` : '').join('');
    const tag = (v, cls, text) => `<span class="endtag ${cls}" style="top:${(y(v) / H) * 100}%">${text}</span>`;
    return `
  <section class="strip">
    <div class="strip-head"><span>Next ${Math.round((tN - t0) / 3600e3)} hours</span>
      <span class="legend"><i class="lg-temp"></i>temp <i class="lg-dp"></i>dew point <i class="lg-limit"></i>dew pt limit
      ${refs ? '<i class="lg-ref"></i>inside ' : ''}${soon ? '<i class="lg-soon"></i>next 2 h ' : ''}<i class="lg-rain"></i>rain
      ${until ? '<i class="lg-until"></i>stops being good' : ''}${opens ? '<i class="lg-opens"></i>could open' : ''}</span></div>
    ${sub}
    <div class="plot">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="gt" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--lt-temp)" stop-opacity=".28"/><stop offset="1" stop-color="var(--lt-temp)" stop-opacity="0"/></linearGradient>
          <linearGradient id="gd" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--lt-dp)" stop-opacity=".22"/><stop offset="1" stop-color="var(--lt-dp)" stop-opacity="0"/></linearGradient>
        </defs>
        <path d="${area('temp')}" fill="url(#gt)"/>
        <path d="${area('dp')}" fill="url(#gd)"/>
        ${soon}${refs}${limit}${until}${opens}
        <path class="l-temp" d="${line('temp')}"/>
        <path class="l-dp" d="${line('dp')}"/>
        ${bars}
      </svg>
      ${tag(last.temp, 't-temp', `${Math.round(last.temp)}°`)}
      ${tag(last.dp, 't-dp', `${Math.round(last.dp)}°`)}
      ${isNum(humid?.t) ? `<span class="limtag" style="top:${(y(humid.t) / H) * 100}%">${Math.round(humid.t)}° limit</span>` : ''}
    </div>
    <div class="hours">${labels}</div>
  </section>`;
  }
}

const LEGEND_KEY = 'logic-trace-card:legend-open';

// Legend for the rails, built from the same classes the rows use.
const key = (open) => `
  <details class="key"${open ? ' open' : ''}>
    <summary>How to read the rails</summary>
    <div class="key-row"><div class="track mini"><span class="rail"></span><span class="zone" style="left:55%;width:45%"></span><span class="tick" style="left:55%"></span><span class="dot" style="left:30%"></span></div>
      <span>The dot is the live value. Crossing into the <b>hatched</b> side fails the check.</span></div>
    <div class="key-row"><div class="track mini"><span class="rail"></span><span class="tick" style="left:40%"></span><span class="tick alt" style="left:65%"></span></div>
      <span><b>Solid</b> tick = the limit in force now; <b>dotted</b> = the other mode’s limit.</span></div>
    <div class="key-row"><div class="track mini"><span class="rail"></span><span class="vs" style="left:45%"></span></div>
      <span><b>Diamond</b> = the indoor reading a moving limit is pinned to.</span></div>
    <div class="key-row"><span class="node-demo"></span>
      <span>Checks run top to bottom and stop at the first <b class="x">✕</b>. Later checks still show, faded.</span></div>
  </details>`;

const STYLE = `<style>
:host {
  --lt-pass: var(--success-color, #2e9d6a);
  --lt-fail: var(--error-color, #e0533d);
  --lt-na: var(--disabled-text-color, #9a9a9a);
  --lt-crack: var(--warning-color, #d9921e);
  --lt-temp: #ef8a3c;
  --lt-dp: #3f8ff0;
  --lt-rain: #58a6e6;
  --lt-ink: var(--primary-text-color);
  --lt-soft: var(--secondary-text-color);
  --lt-line: var(--divider-color, rgba(127,127,127,.25));
  --lt-tone: var(--lt-fail);
}
ha-card { padding: 18px 20px 14px; position: relative; container-type: inline-size; }
.cols { display: grid; grid-template-areas: "mode" "board" "ladder" "side"; }
.mode { grid-area: mode; } .board { grid-area: board; } .ladder { grid-area: ladder; } .side { grid-area: side; }
@container (min-width: 760px) {
  .cols { grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr); column-gap: 28px;
    grid-template-areas: "board mode" "ladder mode" "ladder side"; grid-template-rows: auto auto 1fr; align-items: start; }
  .mode { margin-top: 8px; }
  .side { position: sticky; top: 72px; }
  .side .strip { margin-top: 12px; border-top: none; padding-top: 0; }
  h1 { font-size: 27px; }
}
ha-card.tone-good { --lt-tone: var(--lt-pass); }
ha-card.tone-crack { --lt-tone: var(--lt-crack); }
ha-card.tone-blind, ha-card.tone-paused { --lt-tone: var(--lt-na); }
/* No overflow: hidden on the card (it would clip tooltips); the tone bar
   rounds its own top corners to match the card instead. */
ha-card::before { content: ''; position: absolute; height: 4px; background: var(--lt-tone);
  inset: calc(-1 * var(--ha-card-border-width, 1px)) calc(-1 * var(--ha-card-border-width, 1px)) auto;
  border-radius: var(--ha-card-border-radius, 12px) var(--ha-card-border-radius, 12px) 0 0; }
ha-alert { display: block; margin-top: 12px; }
.track .tick, .track .vs, .track .dot { cursor: help; }
.track .tick::after { content: ''; position: absolute; inset: -4px -6px; }

header { display: flex; gap: 14px; align-items: flex-start; }
.emblem { flex: none; width: 48px; height: 48px; border-radius: 14px; display: grid; place-items: center;
  background: color-mix(in srgb, var(--lt-tone) 14%, transparent); color: var(--lt-tone); }
.emblem ha-icon { --mdc-icon-size: 26px; }
.head { min-width: 0; }
.eyebrow { font-size: 10.5px; letter-spacing: .12em; text-transform: uppercase; color: var(--lt-soft); font-weight: 600; }
.dot-sep { margin: 0 .5em; opacity: .6; }
.kicker { margin-top: 4px; font-size: 12.5px; font-weight: 700; color: var(--lt-tone); letter-spacing: .02em; }
h1 { margin: 1px 0 0; font-size: 23px; line-height: 1.15; font-weight: 700; color: var(--lt-ink); letter-spacing: -.01em; }
.also-line { margin: 6px 0 0; font-size: 13.5px; line-height: 1.4; color: var(--lt-ink); }
.also-line span { color: var(--lt-soft); }
.also-line i { font-style: normal; color: var(--lt-fail); margin: 0 .25em; }
.summary { margin: 4px 0 0; font-size: 12.5px; color: var(--lt-soft); font-variant-numeric: tabular-nums; }

.mode { display: flex; gap: 10px; align-items: baseline; margin: 14px 0 0; padding: 8px 10px; border-radius: 10px;
  background: color-mix(in srgb, var(--lt-ink) 4%, transparent); font-size: 12px; line-height: 1.45; color: var(--lt-soft); }
.mode b { color: var(--lt-ink); font-weight: 600; }
.chip { flex: none; font-size: 9.5px; font-weight: 800; letter-spacing: .1em; padding: 2px 6px; border-radius: 5px;
  color: var(--lt-ink); border: 1px solid var(--lt-line); }

.scoreboard { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 12px 0 4px; font-size: 12px; color: var(--lt-soft); }
.scoreboard b { color: var(--lt-ink); font-variant-numeric: tabular-nums; }
.sb-pass b { color: var(--lt-pass); } .sb-fail b, .scoreboard .x { color: var(--lt-fail); }

/* Ladder rows. Narrow: name | value, then rail, then limit text.
   Wide (ladder >= 540 px): name | rail | value on one line, limit text under the rail. */
.ladder { list-style: none; margin: 0; padding: 0; container: ladder / inline-size; }
.gate { position: relative; display: grid; grid-template-columns: 26px minmax(0, 1fr); gap: 10px; padding: 6px 6px 6px 2px; border-radius: 10px; }
.animate .gate { animation: rise .45s cubic-bezier(.2,.7,.2,1) both; animation-delay: calc(var(--i, 10) * 35ms); }
@keyframes rise { from { transform: translateY(8px); } }
.gate::before { content: ''; position: absolute; left: 14px; top: 31px; bottom: -7px; border-left: 2px solid var(--lt-line); }
.gate.before::before { border-left-color: color-mix(in srgb, var(--lt-pass) 55%, var(--lt-line)); }
.gate.after::before, .gate.decider::before { border-left-style: dashed; }
.gate.terminal::before { display: none; }
.node { position: relative; z-index: 1; box-sizing: border-box; width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center;
  font-size: 12px; font-weight: 800; color: #fff; background: var(--lt-na); margin-top: 1px; }
.s-pass .node { background: var(--lt-pass); }
.s-fail .node { background: var(--lt-fail); }
.s-soft .node { background: var(--lt-crack); }
.s-na .node { background: transparent; border: 2px dashed var(--lt-na); color: var(--lt-na); }
.terminal .node { background: transparent; border: 2px solid var(--lt-na); }
.terminal.s-pass .node { background: var(--lt-pass); border: none; }
.gate.decider { background: color-mix(in srgb, var(--lt-tone) 9%, transparent); }
.gate.decider .node { box-shadow: 0 0 0 4px color-mix(in srgb, var(--lt-tone) 22%, transparent); animation: pulse 2.4s ease-in-out infinite; }
@keyframes pulse { 50% { box-shadow: 0 0 0 8px color-mix(in srgb, var(--lt-tone) 8%, transparent); } }
.gate.after { opacity: .78; }
.gate.after.s-pass { opacity: .55; }

.body { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 12px; align-items: center;
  grid-template-areas: "q val" "viz viz" "meta meta"; }
.qcell { grid-area: q; display: flex; align-items: center; gap: 8px; min-width: 0; min-height: 26px; }
.viz { grid-area: viz; min-width: 0; }
.meta { grid-area: meta; }
.q { font-size: 14.5px; font-weight: 600; color: var(--lt-ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.val { grid-area: val; font-size: 16px; font-weight: 700; color: var(--lt-ink); font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; }
.val small { font-size: 10.5px; font-weight: 500; color: var(--lt-soft); margin-left: 5px; }
.val.muted { font-size: 12px; font-weight: 500; color: var(--lt-soft); }
.badge { flex: none; font-size: 9.5px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; padding: 2px 6px; border-radius: 999px;
  color: #fff; background: var(--lt-tone); }
.badge.ok { background: transparent; color: var(--lt-pass); border: 1px solid color-mix(in srgb, var(--lt-pass) 55%, transparent); }
.badge.mid { background: transparent; color: var(--lt-soft); border: 1px solid var(--lt-line); }
.badge.also { background: transparent; color: var(--lt-fail); border: 1px solid color-mix(in srgb, var(--lt-fail) 55%, transparent); }
.badge.soft { background: transparent; color: var(--lt-crack); border: 1px solid color-mix(in srgb, var(--lt-crack) 55%, transparent); }
.meta { margin-top: 2px; font-size: 11.5px; color: var(--lt-soft); font-variant-numeric: tabular-nums; }
.meta b { color: var(--lt-ink); font-weight: 600; }
.meta .alt { opacity: .8; }
.meta .extra { margin-left: 6px; padding: 1px 6px; border-radius: 6px; background: color-mix(in srgb, var(--lt-rain) 18%, transparent); color: var(--lt-ink); }

@container ladder (min-width: 540px) {
  .body { grid-template-columns: 170px minmax(0, 1fr) 96px; column-gap: 16px; grid-template-areas: "q viz val" "q meta val"; }
  .qcell { flex-direction: column; align-items: flex-start; justify-content: center; gap: 3px; align-self: center; }
  .val { align-self: center; }
  .val small { display: block; margin: 1px 0 0; }
  .viz .track, .viz .pills { margin-top: 2px; }
  .meta { margin-top: 1px; }
}

/* Cycle layout */
.cycle .cols { grid-template-areas: "main" "side"; }
.ladder-wrap { grid-area: main; min-width: 0; }
.power { margin: 14px 0 10px; }
.pw { position: relative; margin-top: 8px; min-height: 60px; }
.pw svg { display: block; width: 100%; height: 170px; overflow: visible; }
.pw-wait { font-size: 12px; color: var(--lt-soft); padding: 20px 0; }
.pw .call { fill: color-mix(in srgb, var(--lt-dp) 10%, transparent); }
.pw .run { fill: var(--lt-pass); opacity: .85; }
.pw .grid { stroke: var(--lt-line); stroke-dasharray: 3 4; vector-effect: non-scaling-stroke; }
.pw .l-a, .pw .l-b { fill: none; stroke-width: 1.8; vector-effect: non-scaling-stroke; stroke-linejoin: round; }
.pw .l-a { stroke: #b07cd8; } .pw .l-b { stroke: #2a9d8f; }
.pw .mk { stroke-width: 1.5; stroke-dasharray: 2 3; vector-effect: non-scaling-stroke; }
.pw .mk-start { stroke: var(--lt-pass); } .pw .mk-stop { stroke: var(--lt-fail); }
.pw .ylab { position: absolute; left: 2px; transform: translateY(-120%); font-size: 10px; color: var(--lt-soft); }
.pw-axis { margin: 4px 0 0; }
.lg-a { background: #b07cd8; } .lg-b { background: #2a9d8f; }
.lg-call { background: color-mix(in srgb, var(--lt-dp) 25%, transparent); height: 10px !important; width: 10px !important; border-radius: 2px !important; }
.lg-run { background: var(--lt-pass); height: 6px !important; }
.hist { padding: 10px 12px; border-radius: 10px; border: 1px solid var(--lt-line); }
.hist-sum { margin-top: 6px; font-size: 13px; color: var(--lt-ink); }
.hist-sum span { display: block; font-size: 11px; color: var(--lt-soft); margin-top: 2px; }
.hist-plot { position: relative; display: flex; align-items: flex-end; gap: 2px; height: 110px; margin-top: 12px; }
.hb { flex: 1; min-height: 1px; border-radius: 3px 3px 0 0; background: var(--lt-dp); opacity: .85; }
.hb.below { background: var(--lt-fail); }
.panel-line { position: absolute; top: -4px; bottom: 0; border-left: 2px dashed var(--lt-ink); opacity: .6; }
.panel-line em { position: absolute; right: 6px; top: -2px; font-size: 10px; font-style: normal; white-space: nowrap; color: var(--lt-ink); text-align: right; line-height: 1.25; }
.hist-axis { position: relative; height: 14px; font-size: 10px; color: var(--lt-soft); margin-top: 4px; }
.hist-axis span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
.hist-axis span:last-child { transform: translateX(-70%); }
@container (min-width: 760px) {
  .cycle .cols { grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); column-gap: 28px; grid-template-areas: "main side";
    grid-template-rows: auto; align-items: start; }
}

/* Blueprint layout */
.cols.bp { grid-template-areas: "ladder" "side"; }
.section-h { list-style: none; margin: 12px 0 2px; font-size: 10.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--lt-soft); }
.section-h:first-child { margin-top: 4px; }
.track .zone.ok { background: color-mix(in srgb, var(--lt-pass) 30%, transparent); }
@container (min-width: 760px) {
  .cols.bp { grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); column-gap: 28px; grid-template-areas: "ladder side"; grid-template-rows: auto; align-items: start; }
}

/* Clock layout */
.s-op .node { background: color-mix(in srgb, var(--primary-color, #03a9f4) 85%, transparent); font-size: 14px; }
.gate.s-op.after { opacity: .6; }
.track .zone.flat { background: color-mix(in srgb, var(--lt-ink) 14%, transparent); }
.track .dot.neutral { background: var(--primary-color, #03a9f4); }
.pill.on { color: var(--lt-ink); border-color: color-mix(in srgb, var(--lt-pass) 55%, transparent); background: color-mix(in srgb, var(--lt-pass) 12%, transparent); }
.pill.on ha-icon { color: var(--lt-pass); }
.clock .cols { grid-template-areas: "ladder" "bars" "side"; }
.bars { grid-area: bars; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--lt-line); display: grid; gap: 12px; }
.bar { display: grid; grid-template-columns: 150px minmax(0, 1fr) 120px; column-gap: 14px; align-items: center; }
.bar-label { font-size: 14px; font-weight: 600; color: var(--lt-ink); display: flex; flex-direction: column; align-items: flex-start; gap: 3px; }
.meter { position: relative; height: 10px; border-radius: 10px; background: var(--lt-line); overflow: hidden; }
.meter i { position: absolute; inset: 0 auto 0 0; border-radius: 10px; background: var(--lt-soft); min-width: 3px; }
.bar.lead .meter i { background: var(--lt-tone); }
.bar-val { text-align: right; font-variant-numeric: tabular-nums; }
.bar-val b { font-size: 16px; color: var(--lt-ink); }
.bar-val small { display: block; font-size: 10.5px; color: var(--lt-soft); }
.bar-note { grid-column: 2 / 4; font-size: 11.5px; color: var(--lt-soft); margin-top: 2px; }
.bars-foot { font-size: 11.5px; color: var(--lt-soft); }
.explain { padding: 10px 12px; border-radius: 10px; background: color-mix(in srgb, var(--lt-ink) 4%, transparent); font-size: 12px; line-height: 1.5; color: var(--lt-soft); }
.explain p { margin: 6px 0 0; } .explain b { color: var(--lt-ink); font-weight: 600; }
.key-title { font-size: 10.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--lt-soft); }
@container (min-width: 760px) {
  .clock .cols { grid-template-areas: "ladder side" "bars side"; grid-template-rows: auto 1fr; }
  .clock .side { position: static; }
}

/* Every marker is centred on the rail by its own middle (border-box), so
   nothing depends on hand-tuned offsets. */
.track { position: relative; height: 18px; margin: 4px 0 0; }
.track > * { position: absolute; top: 50%; box-sizing: border-box; }
.track .rail { left: 0; right: 0; height: 4px; border-radius: 4px; transform: translateY(-50%); background: var(--lt-line); }
.track .zone { height: 4px; border-radius: 4px; transform: translateY(-50%);
  background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--lt-fail) 55%, transparent) 0 4px, color-mix(in srgb, var(--lt-fail) 22%, transparent) 4px 8px); }
.track .tick { width: 2px; height: 14px; border-radius: 2px; transform: translate(-50%, -50%); background: var(--lt-ink); }
.track .tick.alt { background: none; border-left: 2px dotted var(--lt-soft); border-radius: 0; }
.track .vs { width: 10px; height: 10px; border-radius: 2px; transform: translate(-50%, -50%) rotate(45deg);
  background: var(--card-background-color, #fff); border: 2px solid var(--lt-soft); }
.track .dot { width: 14px; height: 14px; border-radius: 50%; transform: translate(-50%, -50%);
  background: var(--lt-pass); border: 2.5px solid var(--card-background-color, #fff); box-shadow: 0 1px 3px rgba(0,0,0,.28); }
.s-fail .track .dot { background: var(--lt-fail); }
.track .dot.clipped { border-style: dotted; }

.pills { display: flex; gap: 5px; margin: 4px 0 0; flex-wrap: wrap; }
.pill { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; font-weight: 600; padding: 1px 8px 1px 5px; border-radius: 999px;
  border: 1px solid var(--lt-line); color: var(--lt-soft); }
.pill ha-icon { --mdc-icon-size: 15px; }
.pill.wet { color: var(--lt-ink); border-color: color-mix(in srgb, var(--lt-rain) 60%, transparent); background: color-mix(in srgb, var(--lt-rain) 16%, transparent); }
.pill.wet ha-icon { color: var(--lt-rain); }
.pill small { font-weight: 500; color: var(--lt-soft); }

.strip { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--lt-line); }
.strip-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px; font-size: 12px; font-weight: 600; color: var(--lt-ink); }
.legend { font-weight: 500; color: var(--lt-soft); display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; }
.legend i { display: inline-block; width: 14px; height: 3px; border-radius: 2px; margin-left: 6px; vertical-align: middle; }
.lg-temp { background: var(--lt-temp); } .lg-dp { background: var(--lt-dp); }
.lg-limit { background: repeating-linear-gradient(90deg, var(--lt-dp) 0 3px, transparent 3px 6px); }
.lg-rain { background: var(--lt-rain); height: 8px !important; width: 8px !important; border-radius: 2px !important; }
.lg-until { background: var(--lt-pass); width: 3px !important; height: 12px !important; }
.lg-opens { background: repeating-linear-gradient(180deg, var(--lt-pass) 0 3px, transparent 3px 5px); width: 3px !important; height: 12px !important; }
.lg-ref { background: repeating-linear-gradient(90deg, var(--lt-soft) 0 2px, transparent 2px 5px); }
.lg-soon { background: color-mix(in srgb, var(--lt-ink) 12%, transparent); height: 10px !important; width: 12px !important; border-radius: 2px !important; }
.plot { position: relative; margin: 10px 34px 0 0; }
.plot svg { display: block; width: 100%; height: 124px; overflow: visible; }
.l-temp, .l-dp { fill: none; stroke-width: 2.5; stroke-linejoin: round; stroke-linecap: round; vector-effect: non-scaling-stroke; }
.l-temp { stroke: var(--lt-temp); } .l-dp { stroke: var(--lt-dp); }
.limit { stroke: var(--lt-dp); stroke-width: 1.5; stroke-dasharray: 5 5; opacity: .75; vector-effect: non-scaling-stroke; }
.until { stroke: var(--lt-pass); stroke-width: 2; vector-effect: non-scaling-stroke; }
.opens { stroke: var(--lt-pass); stroke-width: 2; stroke-dasharray: 4 3; vector-effect: non-scaling-stroke; }
.ref { stroke-width: 1.25; stroke-dasharray: 2 4; opacity: .7; vector-effect: non-scaling-stroke; }
.ref-temp { stroke: var(--lt-temp); } .ref-dp { stroke: var(--lt-dp); }
.soon { fill: color-mix(in srgb, var(--lt-ink) 6%, transparent); }
.strip-sub { margin: 4px 0 0; font-size: 11.5px; color: var(--lt-soft); font-variant-numeric: tabular-nums; }
.rain { fill: var(--lt-rain); opacity: .85; }
.endtag, .limtag { position: absolute; right: -34px; transform: translateY(-50%); font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; }
.t-temp { color: var(--lt-temp); } .t-dp { color: var(--lt-dp); }
.limtag { right: auto; left: 4px; transform: translateY(-120%); font-weight: 600; font-size: 10px; color: var(--lt-dp); opacity: .85; }
.hours { position: relative; height: 16px; margin: 6px 34px 0 0; }
.hours span { position: absolute; transform: translateX(-50%); font-size: 10.5px; color: var(--lt-soft); white-space: nowrap; }
.hours span:first-child { transform: none; } .hours span:last-child { transform: translateX(-100%); }

.key { margin-top: 14px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--lt-line); }
.key[open] { display: grid; gap: 9px; }
.key summary { cursor: pointer; font-size: 10.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--lt-soft); }
.key summary:hover { color: var(--lt-ink); }
.key-row { display: grid; grid-template-columns: 80px 1fr; gap: 12px; align-items: center; font-size: 11.5px; line-height: 1.4; color: var(--lt-soft); }
.key-row b { color: var(--lt-ink); font-weight: 600; } .key-row b.x { color: var(--lt-fail); }
.track.mini { margin: 0; }
.node-demo { justify-self: center; width: 20px; height: 20px; border-radius: 50%; background: var(--lt-fail);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--lt-fail) 22%, transparent); }
footer { margin-top: 12px; font-size: 11px; line-height: 1.5; color: var(--lt-soft); opacity: .85; }
footer code { font-size: 10.5px; padding: 1px 4px; border-radius: 4px; background: color-mix(in srgb, var(--lt-ink) 7%, transparent); }

@media (max-width: 480px) {
  ha-card { padding: 16px 12px 12px; }
  h1 { font-size: 20px; }
  .emblem { width: 40px; height: 40px; border-radius: 12px; }
  .q { font-size: 14px; }
}
@media (prefers-reduced-motion: reduce) { .gate, .gate.decider .node { animation: none; } }
</style>`;

if (!customElements.get('logic-trace-card')) {
  customElements.define('logic-trace-card', LogicTraceCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: 'logic-trace-card', name: 'Logic Trace', description: 'Shows a heuristic’s decision ladder from its trace attribute.' });
}
