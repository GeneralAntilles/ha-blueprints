# HVAC instrumentation: parts list and build guide

Written 2026-09-27, revised 2026-09-28 after a senior review (Codex + Grok) and Ryan's answers.
This is phase 4 of the HVAC health monitor (`README.md`, `~/.claude/plans/hvac-health-monitor.md`).
It covers hardware only. The monitor's software stays as built, and every new signal below feeds an
existing event kind or adds a small new one (see §9).

> **How to read this.** There are six modules. Each one can be built and used by itself, and §2 gives
> the build order. **⚠** marks a caveat. **❓** marks something still unconfirmed; all of those are
> collected in §11. Prices are approximate USD as of 2026-09. **V** means I saw the price on a retailer
> or distributor page while writing this. Every other price is an estimate.

---

## 0. Equipment facts this doc relies on

| Item | Fact | Source |
|---|---|---|
| Location | **Furnace/air handler and zone panel are in the attic.** The condenser is outside, a short Cat6 run from the attic. There's a 120 V receptacle at the condenser | Ryan 2026-09-28 |
| Condenser | Lennox 14ACXS036-230A22, 3-ton, single-stage, R-410A; RLA 14.1 A, LRA 83 A; fan 1/6 HP, FLA 1.0 A | nameplate |
| Condenser safeties | **High-pressure switch S4 on the liquid line, manual reset (red button), opens at 590 ± 10 psig.** *Some* 14ACX units also have a compressor-mounted thermal switch **S173**, wired in series with the 24 V Y input | 14ACX IOM 506645-01 p. 28. ❓ That manual covers the 14ACX; this unit is a 14ACX**S**. Confirm both switches on the unit's own wiring diagram |
| Charging data | The IOM has TXV subcooling targets and normal-pressure tables for the −036. **Charging targets for this unit must come from its own label and the tech**, so the IOM values are context only | IOM Fig. 23, Table 4 |
| Indoor coil | CHX35-30B-6F-1, 2.5-ton horizontal cased coil. A LennoxPros listing says **TXV** | ❓ tech to confirm (deferred) |
| Furnace | EL180UH070E36B: 66k in / 53k out BTU/h; rise 40–70 °F; 5-tap constant-torque ECM; 40 VA transformer + 3 A 24 V breaker; speed taps 12–33 VAC, < 20 mA; fixed 45 s cool fan-off delay; heat blower 30 s after flame | EL180 spec + service lit. 1302f |
| Furnace control terminals | 24 VAC quick-connects **COOL, HEAT, FAN** (the speed tap being driven) and **24 COM**; thermostat strip R/C/W/Y/G | 1302f Table 3 |
| Zone panel | Aprilaire 6203, 2 zones used. HVAC side is RH/RC/W/Y/G. **There is no C on the HVAC side.** It runs on **its own transformer** (POWER R/C). 4-min min on/off, 20-min changeover, DAT cutoff at 40 °F (cooling) / 160 °F (heating), resumes after 10 °F | 6203 manual |
| Dampers | Honeywell **normally-open, power-close (spring-open) dampers, wired to NO + COM (2-wire)**. Per the 6203 manual, NO is used "to power close a normally open damper". **24 V on NO means the damper is commanded closed**; no voltage means open. A dead motor, broken wire or blown zone transformer leaves the zone **open** (fails safe for airflow). The leak during the other zone's calls is the powered stroke not seating the blade (motor, linkage or stop), not a spring | Ryan (actuator + terminal, 2026-10-02) + 6203 manual |
| Condensate | A condensate safety switch exists. ❓ Which conductor it interrupts (Y or R), and where, is unconfirmed. An attic air handler normally has a secondary pan and/or float (IRC M1411.3 auxiliary drain requirement) | Ryan |
| Power monitoring | **First-gen Shelly 3EM (SHEM-3, fw 1.13.1)** on the service conductors. The phase-C channel is unused, with its entities disabled | Ryan |

**Consequences for all 24 V wiring:**

- **Two transformers.** There are two separate 24 V transformers. Y/G/W/R are sensed against the
  **furnace C**. Damper and zone-panel power are sensed against the **6203 COM/C**. The two commons are
  never tied together.
- **Isolated inputs.** Every input is an isolated opto (or relay coil) wired across its own point pair.
- **Current limiting at the terminal.** Each pickup gets its current-limiting resistor right at the
  terminal (§3.3). That's what keeps a harness fault from bypassing a safety. The opto isolation alone
  doesn't protect against a short between conductors on the HVAC side.

---

## 1. Architecture

```
          Cat6 / PoE (injector or PoE switch port, not in the attic) ───► LAN ───► HA (ESPHome add-on)
                    │                                          │
 ┌──────────────────┴────────────────┐   ┌─────────────────────┴─────────────────────────┐
 │ NODE "HVAC Indoor"  (ATTIC)       │   │ NODE "HVAC Outdoor"                            │
 │ Olimex ESP32-POE-ISO (-IND pref.) │   │ Olimex ESP32-POE-ISO, NEMA 4X box on a wall/   │
 │ gasketed PC box on the RETURN     │   │ post beside the disconnect (not on the cabinet)│
 │ plenum side of the air handler    │   │                                                │
 │                                   │   │ M2  CT compressor common lead (0.333 V, 30 A)   │
 │ M1  MCP23017 + 12 AC optos:       │   │ M2  CT fan common lead (0.333 V, 5 A)           │
 │     furnace R (heartbeat), 6203 RC│   │ M2  opto: Y at unit, contactor coil             │
 │     6203 Y, furnace Y, G, W,      │   │ M5  DS18B20 coil entering / leaving air         │
 │     6203 R (heartbeat), Z1 NO,    │   │ M3  (deferred) ADS1115 + 2 transducers,         │
 │     Z2 NO, COOL/HEAT/FAN taps     │   │     DS18B20 suction / liquid line               │
 │ M2  CT furnace hot (0.333 V, 10 A)│   └────────────────────────────────────────────────┘
 │ M4  SDP810-500Pa ◄─ tubes         │
 │ M5  DS18B20 supply, SHT45 return  │   Shelly 3EM gen1 phase C = optional coarse furnace
 └───────────────────────────────────┘   on/off pattern only (§4.2)

 M6: the existing condensate switch stays in its 24 V circuit. Each side of it is read against the
 furnace C by M1 channels (never across it), plus an independent Zigbee leak puck in the secondary pan.
```

### 1.1 Attic realities (indoor node)

| Concern | Design response |
|---|---|
| **Heat.** An Austin attic runs about 130–150 °F (55–65 °C) on summer afternoons | PoE power, so there's no consumer USB adapter up there (most are rated 0–40 °C). Prefer the industrial-temperature Olimex variant (**ESP32-POE-ISO-IND**, −40…85 °C; ❓ confirm the part/rating with Olimex). Use ceramic/film caps, not electrolytics. Resistors are sized ≤ 30 % of rating (§3.3). Mount the box on the **return** plenum side, which is the coolest metal around while the system runs, and away from the flue and any roof deck in direct sun. Use a light-coloured polycarbonate box (PC stays stable well above ABS temperatures) |
| **Dust / insulation fibre** | Gasketed box (IP54 or better), cable glands on the bottom face, no vents. SDP810 tubing ends are sealed onto the tips, so no attic air gets in |
| **Access** | Every trip is a hot crawl, so: OTA updates, pluggable (pull-apart) terminal blocks, labelled pickups, photos of every terminal before and after, and all pickups (with their resistors and fuses) left in place so the box can be swapped without touching HVAC terminals. Work early in the morning |
| **Weight on ducts** | Mount on a truss or strap near the unit if the return plenum is flex or ductboard. Only screw into a sheet-metal plenum |

### 1.2 Boards and power

- **Both nodes: Olimex ESP32-POE-ISO.** It's $29.93–31.09 at Digi-Key (**V**, standard temperature
  range), with isolated PoE and native ESPHome support.
- **Ethernet block** (both nodes):
  `ethernet: { type: LAN8720, mdc_pin: GPIO23, mdio_pin: GPIO18, clk_mode: GPIO17_OUT, phy_addr: 0, power_pin: GPIO12 }`.
- **Pins.** Ethernet takes about 10 GPIOs, so the indoor opto inputs go through an **MCP23017** I/O
  expander on I²C.
  - I²C: GPIO13 (SDA) and GPIO16 (SCL), the board's UEXT pins.
  - 1-Wire: GPIO4.
  - Analog inputs: ADC1 only (GPIO35/36/39).
  - ⚠ GPIO34 is the on-board button. Check the Olimex schematic for jumper-selectable battery/power-sense
    pins before assigning GPIO35/39.
- **PoE source.** The 24-port PoE switch in the network corner, directly below the attic.

---

## 2. Build order (value per dollar and effort)

| # | Module | Unlocks | Parts ≈ | Effort | Depends on |
|---|---|---|---|---|---|
| 1 | **M1 24 V taps** | Real calls; "Y on + no compressor" = certain no-start; DAT cutoff vs. real mid-call stop; damper close commands; blower tap in use; transformer heartbeats; condensate-switch state | $175 | 1 evening build + 1–2 h attic install | none |
| 2 | **M6 condensate** (switch sensing is in M1) + leak puck | 🚨 condensate trip | $18 | 30 min | M1 |
| 3 | **M2 current** (compressor, fan, furnace CTs; outdoor Y/coil optos) | 🚨 compressor without fan current; safety-open vs. overload; direct blower watts | $207 | 1 day | M1 helps a lot |
| 4 | **M5 air temps** | Coil ΔT vs. Lennox target; confirms DAT cutoffs; heat rise → CFM; corroborates fan airflow | $43 | 2–3 h | M1 box, M2 box |
| 5 | **M4 static pressure** | TESP → CFM for the tap actually driven; filter/damper trend; damper repair before/after | $77 | 2 h | M1 box (+ tap channels) |
| 6 | **M3 refrigerant**, **DEFERRED** (no tech visit planned) | Superheat, subcooling, pressures | $130–490 + tech | tech 1 h + you 2–3 h | M2 box; after short cycling is fixed (§6.7) |

**If you build only two modules, build M1 and the M2 fan and compressor CTs.**

---

## 3. Module 1: Aprilaire 6203 / furnace 24 VAC taps

### 3.1 What the monitor gains

| Signal | Today (inferred) | With the tap |
|---|---|---|
| Cooling demand at the equipment | "either ecobee cooling", which lags and doesn't see the 4-min min-off | **Y at the furnace strip** (and 6203 Y out) |
| No-start | call + 5.5 min with no power step | **Y on ≥ 90 s and no compressor** (the panel's timers are already applied upstream of Y) |
| Mid-call stop | stop while an ecobee still calls → assumed DAT, held tier | **Y still on at the stop** → real protective stop. **Y dropped + G on + zone still calling** (gated, §3.6) → DAT cutoff. W or a heat call → changeover |
| Fan-only / purge | invisible | G without Y/W |
| Heat sequence | leg-B power response | W timing, plus which tap is driven. ⚠ **The HEAT tap being live is *not* ignition proof.** The furnace also drives the blower during limit/rollout faults with the gas valve closed. Ignition proof stays with heat rise (M5) and `heat_response` power |
| Dampers | invisible | **NO per zone energized = commanded closed** (actual blade position isn't sensed; §3.8) |
| Blower tap in use | assumed | **COOL / HEAT / FAN terminals** → which CFM table row applies (M4) |
| Sensing health | — | **Furnace R–C and 6203 R–C heartbeats**: if a sense fuse blows or a transformer dies, the monitor says "sensing lost / no 24 V" instead of silently reporting "no calls" |
| Condensate switch | invisible | the channels on either side of it disagree (§8) |

### 3.2 Measurement points

All furnace-side channels are referenced to the **furnace C (fuse F1)**. All zone-panel channels are
referenced to the **6203 COM/C (fuse F2)**. Put the two groups on **separate terminal barriers** inside
the box, run them in separate cables, and keep the two reference buses apart on the board.

| Ch | Name | Across (pickup / reference) | Group | Why |
|---|---|---|---|---|
| 1 | Furnace 24 V (heartbeat) | furnace strip **R** (transformer side) / furnace C | F | transformer + 3 A breaker + F1 alive |
| 2 | 6203 RC | 6203 HVAC **RC** / furnace C | F | downstream of a float switch if the float is in R |
| 3 | 6203 Y out | 6203 HVAC **Y** / furnace C | F | the panel's cooling output |
| 4 | Furnace Y | furnace strip **Y** / furnace C | F | differs from ch 3 if the float is between them |
| 5 | G | furnace strip **G** / furnace C | F | |
| 6 | W | furnace strip **W** / furnace C | F | |
| 7 | COOL tap | control **COOL** / **24 COM** | F | 12–33 VAC; see 3.3 |
| 8 | HEAT tap | control **HEAT** / 24 COM | F | not ignition proof |
| 9 | FAN tap | control **FAN** / 24 COM | F | |
| 10 | 6203 24 V (heartbeat) | 6203 POWER **R** / POWER **C** | Z | zone transformer + F2 alive |
| 11 | Zone 1 damper closed | DAMPER 1 **NO** / **COM** | Z | NO energized = power-close |
| 12 | Zone 2 damper closed | DAMPER 2 **NO** / **COM** | Z | |
| (out) | Y at unit, contactor coil | outdoor node, §4.4 | outdoor | straddles a float at the condenser feed |

Where the condensate switch is decides which pair straddles it. See §8: one existing pair always does,
so its exact location only changes the template, not the hardware.

⚠ **Confirm the 6203's COM is its POWER C** with an ohmmeter, power off. If it isn't, give the damper
channels their own reference lead and fuse.

### 3.3 Input circuit and fault safety

**Pickup assembly, at each terminal and inside heat-shrink:**

```
  HVAC TERMINAL (e.g. furnace Y) ──[ R1  3.3 kΩ 1 W ]──► signal lead ──────────────┐
                                                                                    │
  REFERENCE (furnace C)          ──[ F1  250 mA fast ]─► reference lead (bus) ─┐    │
                                                                               │    │
  ─────────────────────────────────── in the box ───────────────────────────── │ ── │ ──
                                                                               │    │
                                      H11AA1 (DIP-6)                           │    │
                                pin 1 ─ LED pair ─ pin 2  ◄────────────────────┘    │   (pin 2 → reference bus)
                                  ▲                                                 │
                                  └─────────────────────────────────────────────────┘   (pin 1 ← signal lead)
                                pin 5 (collector) ──┬── MCP23017 input ──[10 kΩ]── 3.3 V
                                                    └──[ C1 1 µF ceramic ]── GND   (optional)
                                pin 4 (emitter)  ──── GND
                                pin 6 (base) open, pin 3 NC
```

- **R1 at the terminal, not on the board.** Every conductor that leaves an HVAC terminal carries at most
  about 10 mA. The only low-impedance leads are the two references, each fused (F1 furnace C, F2 6203
  COM) at its pickup.
- **Fault review:**

  | Fault | What happens |
  |---|---|
  | Two signal leads shorted together (e.g. the Y pickups on either side of a float switch) | The path runs through two resistors, ≥ 6.6 kΩ, ≈ 5 mA. A contactor coil needs roughly 100 mA or more to pull in, so it **can't bypass the float or energize a load** |
  | Signal lead shorted to its reference | ≈ 10 mA, harmless |
  | Furnace C shorted to 6203 COM | ties the transformer commons through F1/F2. Keep the bundles apart. F1/F2 open on any real current |
  | F1 or F2 blows | all channels in that group go dark together, and the heartbeat (ch 1/10) goes dark with them. The monitor must treat "heartbeat off" as **sensing lost / no 24 V** (and a real loss of 24 V is itself a failure worth an alert), never as "no calls" |

- **Never put any sense load *across* the float or safety contacts, or across S4/S173.** Sense each side
  to its transformer common only.
- **R1 sizing.** H11AA1 CTR is **guaranteed ≥ 20 % only at 10 mA**, so drive the LED near that.
  - At 24 VAC (34 V peak) through 3.3 kΩ: I_peak ≈ 10 mA, I_rms ≈ 7 mA. At 30 VAC unloaded:
    I_peak ≈ 12.5 mA, and dissipation is 0.27 W. A **1 W** resistor runs at ≤ 30 %, which suits attic heat.
  - The 10 kΩ pull-up needs only 0.33 mA to pull low, so a CTR of about 3 % at the peak is enough: large
    margin for LED ageing.
  - Load: about 7 mA × 12 ≈ 85 mA ≈ 2 VA in total, split across the 40 VA furnace transformer and the
    6203's supply. Negligible.
- **Speed-tap channels (7–9).** The spec allows 12–33 VAC. At 12 VAC, 3.3 kΩ gives I_peak ≈ 4.8 mA
  (CTR margin still > 10×, but not guaranteed). **Measure the COOL/HEAT/FAN voltage to 24 COM with the tap
  live** (§11 Q4). If it's below about 18 VAC, use 1.8 kΩ 1 W on those three, or use relays (Option B).
- **Debounce order.** The opto output drops out near every zero crossing (120 Hz). Bridge the dropouts
  first (`delayed_off`), then debounce the assertion (`delayed_on`). With `delayed_on` first and no C1,
  every zero crossing resets the timer and the input never asserts. With C1 fitted (10 kΩ × 1 µF = 10 ms)
  the output is already smooth, and the same filter order still applies.
- **Off-state leakage.** A triac or snubber output can leak a few VAC through the load when it's "off".
  **Measure with a multimeter, no call** (§11 Q4): AC volts 6203 Y → furnace C, furnace Y → C, and each
  damper NO → COM. If any reads above about 3 VAC, add a 4.7 kΩ 1 W bleeder across that opto input on the board
  side, then re-check that the input reads off.

**Option B, DIN interface relays** (24 V AC/DC "UC" coil, e.g. Phoenix Contact PLC-RSC-24UC/21 or
Finder 38.51 24 V AC/DC; **verify the exact order code**; about $10–20 each, not verified):

- UL-listed and rated for the full coil range.
- Load is about 0.5 VA each (12 relays ≈ 6 VA). Check that against the 6203's 18–30 VA damper output
  budget.
- The same pickup rule applies: fuse the coil lead at the terminal (a 100 mA fuse or PTC per channel).
  A relay coil is a low-impedance load, so a two-lead short *can* carry enough current to matter.
  **Option A's resistor pickups are the safer design around the float switch.**

**Ready-made opto boards:** most listings are 220 VAC or DC-input (PC817). If you use one, the pickup
resistors above still go at the terminals, and the board's own resistor must be bypassed or accounted for.

### 3.4 Wiring and mounting

- **Cables** (run each pickup's signal lead with its own group's reference lead):
  - 18/8 thermostat cable for group F: R, RC, 6203 Y, furnace Y, G, W, C-ref, one spare.
  - A separate 18/5 cable for the three tap leads plus 24 COM. Use a short jumper to C if 24 COM and
    strip C are the same point; check this with an ohmmeter.
  - A separate 18/5 cable for group Z: R, Z1 NO, Z2 NO, COM-ref, one spare.
- **Terminal connections.**
  - Use piggyback spades or a second conductor under the same screw at the furnace.
  - The 6203 push terminals take one 18–20 AWG solid wire each. Add a short jumper from each 6203
    terminal to a 4-position barrier strip, and land both the original wire and the pickup there.
- **Pickups.** R1 and the fuses go in heat-shrink at the barrier or strip end, labelled with the channel
  number.
- **Box.** Two separate barrier strips (F and Z) at the cable entry. Pluggable terminal blocks on the
  board so it can be pulled without re-terminating.
- **Keep clear of line voltage.** Don't bundle any of this with 120 V, and route it away from the flue,
  as the manual says for the DAT sensor wiring.

### 3.5 ESPHome sketch (indoor node, part 1)

```yaml
# hvac-indoor.yaml: Olimex ESP32-POE-ISO + MCP23017 (0x20). Opto pulls LOW when energized.
esphome: { name: hvac-indoor, friendly_name: HVAC Indoor }
esp32: { board: esp32-poe-iso, framework: { type: esp-idf } }
ethernet: { type: LAN8720, mdc_pin: GPIO23, mdio_pin: GPIO18, clk_mode: GPIO17_OUT, phy_addr: 0, power_pin: GPIO12 }
api: { encryption: { key: !secret hvac_indoor_api_key } }
ota: [{ platform: esphome, password: !secret hvac_indoor_ota }]
logger: { level: INFO }
i2c: { sda: GPIO13, scl: GPIO16, frequency: 50kHz }
mcp23017: [{ id: mcp_in, address: 0x20 }]

# Bridge zero-crossing dropouts FIRST, then debounce the assertion.
.opto: &opto
  platform: gpio
  filters:
    - delayed_off: 60ms
    - delayed_on: 150ms

binary_sensor:
  - { <<: *opto, name: "Furnace 24V",          id: furnace_24v, pin: { mcp23xxx: mcp_in, number: 0,  mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "Zone Panel RC",        id: rc_6203,     pin: { mcp23xxx: mcp_in, number: 1,  mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "Zone Panel Y",         id: y_6203,      pin: { mcp23xxx: mcp_in, number: 2,  mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "Y",                    id: y,           pin: { mcp23xxx: mcp_in, number: 3,  mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "G",                    id: g,           pin: { mcp23xxx: mcp_in, number: 4,  mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "W",                    id: w,           pin: { mcp23xxx: mcp_in, number: 5,  mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "Blower Cool Tap",                        pin: { mcp23xxx: mcp_in, number: 6,  mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "Blower Heat Tap",                        pin: { mcp23xxx: mcp_in, number: 7,  mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "Blower Fan Tap",                         pin: { mcp23xxx: mcp_in, number: 8,  mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "Zone Panel 24V",       id: z_24v,       pin: { mcp23xxx: mcp_in, number: 9,  mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "Zone 1 Damper Closed",                   pin: { mcp23xxx: mcp_in, number: 10, mode: { input: true }, inverted: true } }
  - { <<: *opto, name: "Zone 2 Damper Closed",                   pin: { mcp23xxx: mcp_in, number: 11, mode: { input: true }, inverted: true } }
  - platform: status
    name: "Status"
```

External 10 kΩ pull-ups are used because the MCP23017's internal ~100 kΩ is too weak for an attic
cable environment. ESPHome polls MCP23017 inputs every loop, which is fast enough. If your ESPHome
version rejects the `.opto` YAML anchor, repeat the two filters on each entry.

### 3.6 Suggested HA entities and derived templates

The registry uses device+entity IDs, so a device named "HVAC Indoor" gives:
`binary_sensor.hvac_indoor_furnace_24v`, `_zone_panel_rc`, `_zone_panel_y`, `_y`, `_g`, `_w`,
`_blower_cool_tap`, `_blower_heat_tap`, `_blower_fan_tap`, `_zone_panel_24v`, `_zone_1_damper_closed`,
`_zone_2_damper_closed`.

```yaml
# DAT low-limit cutoff. On a real cutoff the 6203 drops Y (the compressor stops) and forces G,
# while a zone keeps calling. Evaluated 75 s after Y drops. That delay lets a lagging ecobee
# hvac_action catch up after a normal call end. Y having been on is implicit (the trigger is Y
# on->off), so the 4-min min-off at call start (Y never came on) can't match.
- trigger:
    - trigger: state
      entity_id: binary_sensor.hvac_indoor_y
      from: 'on'
      to: 'off'
      for: { seconds: 75 }
      id: y_dropped
    - trigger: state
      entity_id: binary_sensor.hvac_indoor_y
      to: 'on'
      id: clear
    - trigger: state
      entity_id: sensor.ac_compressor_state
      to: '0'
      id: clear
  binary_sensor:
    - unique_id: hvac_dat_cutoff
      name: HVAC DAT Cutoff
      state: >-
        {{ trigger.id == 'y_dropped'
           and states('sensor.ac_compressor_state') | float(0) >= 1
           and is_state('binary_sensor.hvac_indoor_y', 'off')
           and is_state('binary_sensor.hvac_indoor_g', 'on')
           and is_state('binary_sensor.hvac_indoor_w', 'off')
           and is_state('binary_sensor.hvac_heat_call', 'off')
           and (states('sensor.hvac_indoor_supply_air_temperature') | float(40) < 48) }}
        {# the supply check is neutral (40) until M5 exists; with M5 a real cutoff is < ~45 °F #}

- binary_sensor:
    - unique_id: hvac_sensing_ok
      name: HVAC Sensing OK
      # Off = a sense fuse, the ESP, or a transformer is down: never read "no calls" from it.
      state: >-
        {{ is_state('binary_sensor.hvac_indoor_furnace_24v', 'on')
           and is_state('binary_sensor.hvac_indoor_zone_panel_24v', 'on') }}
```

⚠ The DAT template is a design sketch. Validate it against the 6203's **COOLING LED flashing** (the
manual's limit-interrupt indicator) the first few times it fires.

### 3.7 Install steps

1. Photograph the furnace strip, the control's tap terminals, and the 6203.
2. **Power off both 120 V sources** (furnace service switch and the 6203 transformer). The 6203 manual
   also warns that a live short can damage components.
3. Build and label the pickups (R1 or the fuse in heat-shrink). Land them.
4. Before connecting the box, measure AC volts at each pickup's box end against its reference, with
   calls on and off, and record them. This is where you do the leakage and tap-voltage measurements (§11 Q4).
5. Connect, flash, adopt.

### 3.8 Commissioning

| Test | Expect |
|---|---|
| Idle | Both 24 V heartbeats on; Y/G/W off. Damper NO states: whatever the 6203 does at idle (record it; with NO dampers, "closed" needs power) |
| Fan ON at an ecobee | G on; FAN tap on; the non-calling zone's NO comes on (its damper is powered closed) |
| Cool call upstairs | Z1 NO on (downstairs powered closed), Z2 NO off; 6203 Y on (after any min-off), furnace Y on; COOL tap on; compressor step within ~2 s of Y. Cross-check the 6203 zone LEDs (green = open, red = closed) against the NO channels |
| Call ends | Y off; dampers hold 3.5 min then purge; COOL tap off about 45 s later (furnace delay) |
| TDO button | speeds up the timers for testing (6 s = 1 min) |
| Pull F1 (power off, then on) | all group-F channels off, `hvac_sensing_ok` off. Same for F2 and group Z |
| Heat call (season) | W on → HEAT tap on after the ignition sequence, with a heat rise in M5 (the rise is the proof) |

Actual damper *position* isn't sensed. A magnet plus reed switch (or a Zigbee contact sensor) at each
damper's closed stop (about $15/zone) would prove "closed really closes". That's worth doing with the
damper repair.

**Effort:** 3–4 h build + 1–2 h in the attic + 30 min commissioning.

---

## 4. Module 2: current sensing

### 4.1 What the monitor gains

| Condition | Signature | Tier |
|---|---|---|
| **No condenser fan current** (open motor winding, burnt lead, motor thermal trip) | compressor current present, **fan current < ~0.35 A** | 🚨 any hour |
| Fan **stalled** (seized bearing, failed run capacitor) | fan current **present but abnormal**, typically above the learned band (a stalled PSC motor draws more than running) or erratic. ⚠ **Current present ≠ rotation**, see 4.5 | held; corroborate with M5 condenser air ΔT |
| Compressor on internal overload | contactor coil on, fan current present, **compressor ≈ 0**, recurring | held (🚨 if indoor > 80 °F) |
| S4 (HP, manual reset) or S173 (if fitted) open | **Y at unit on, contactor coil off**, no current | held; message names the red S4 reset button ("find the cause first") |
| Locked rotor, sustained | compressor ≥ 40 A for **≥ 3 s continuous** (it runs until the overload trips) | held |
| Capacitor/coil drift | fan A down, compressor A up vs. the outdoor-temperature model | phase-3 drift |
| Blower watts, direct | furnace-circuit current × 120 V (× PF) while cooling | replaces the ramp-down estimate |

⚠ **Inrush/hard-start is not reliably detectable here.** `ct_clamp` samples 200 ms out of every 1 s,
and an inrush lasts about 0.1–0.3 s, so most starts fall between samples. Only sustained events (a
locked rotor lasting several seconds) are dependable.

### 4.2 Options compared

| Option | Measures | Verdict |
|---|---|---|
| **a. ESP32 + 0.333 V CTs with protected ADC inputs** (recommended) | compressor, fan (outdoor); furnace (indoor) | Cheap, at the equipment. Good enough for on/off and drift. Current only (no PF). Needs a one-time calibration against a clamp meter |
| b. Energy-monitor IC board (CircuitSetup ATM90E32-based, ESPHome `atm90e32`) | true RMS A, W, PF per channel | Better accuracy and power factor, and it handles CT inputs properly. Needs a 9 VAC reference transformer (the condenser receptacle can supply it). More cost and board space (~$90–150, not verified). Choose it if you want real watts/PF trends |
| c. Shelly 3EM gen1 **phase C** | one circuit, coarse | Free-ish, already in HA. ⚠ See below |
| d. Shelly Pro EM-50 in the panel | 2 circuits, 50 A CTs, 1 voltage input | $119.95 (ameriDroid, **V**). Amps are fine, but 240 V loads read **watts ×½**. Can't see the fan. Only worth it if you want panel-side redundancy |

**Shelly 3EM gen1 phase C, specifics:**

- **The CT.** Ryan may not have the original clamp. I could **not** confirm that Shelly's 50 A clamp
  works on the gen1 3EM, or that gen1 firmware lets you mix CT types per channel. The safe choice is the
  **same 120 A clamp type the 3EM shipped with** (buy the replacement Shelly lists for the gen1 3EM and
  confirm the part number with Shelly/the retailer before ordering; ❓ §11 Q6).
- **Resolution.** Even with the right clamp, a 120 A (or 50 A) CT at 1.5–4 A of furnace draw is coarse.
  It's fine for the on/off *pattern* (blower on, inducer or igniter sequence), not for precise blower
  watts.
- **Voltage reference.** The phase-C voltage input may sit on the wrong leg, so trust **amps**, not watts.

**Decision:** the indoor node gets a **dedicated 10 A CT on the furnace hot** as the primary blower
measurement. The 3EM phase C is an optional free cross-check.

### 4.3 CT choice, placement and input protection

| CT | Where | Part | Signal |
|---|---|---|---|
| Compressor | **Compressor common (C) lead** at the contactor inside the condenser control box. Identify it from the unit's wiring diagram. Enclose only that wire, not a shared terminal jumper | 30 A / 0.333 V, 600 V-rated leads (Magnelab SCT-0400-030 class) | 12 A run → 0.13 V rms; 83 A LRA → ~0.92 V rms / 1.3 V peak (less if the core saturates) |
| Condenser fan | **Fan motor common/line lead** (to the contactor), **not** the lead to the capacitor's FAN terminal (that one carries only the auxiliary-winding current) | 5 A / 0.333 V, 600 V leads (**Magnelab SCT-0400-005**, about $25–40, not verified) | 0.9 A → 60 mV rms |
| Furnace (indoor) | the furnace **hot** as a single conductor: inside the furnace service-switch box or the furnace's line-voltage junction box (power off at the switch/breaker first) | 10 A / 0.333 V, 600 V leads (Magnelab SCT-0400-010 class) | 1.5 A blower → 50 mV; ~8 A max in heat → 0.27 V rms |

- **Why this layout.** Measuring the compressor on its own lead avoids "total minus fan". Subtracting
  RMS currents isn't exact because the compressor and fan currents are at different phase angles. If you
  clamp the unit total at the disconnect instead, call the difference an estimate.
- **Voltage-output (0.333 V) CTs.** These have an internal burden, so there's no open-secondary hazard.
  Their 600 V leads are what's needed inside a line-voltage enclosure (NEC 725 separation). **Don't** use
  SCT-013-030 (1 V at 30 A) on the compressor: at 83 A LRA it gives ≈ 2.8 V rms / **3.9 V peak**,
  against a 1.65 V-biased ESP32 input. A burden resistor doesn't clip anything.
- **Input protection on every CT channel:**

```
  CT (+) ──[ 1 kΩ ]──┬──────────────► ESP32 ADC pin
                     ├─|◄─ 3.3 V      BAT54S (dual Schottky) clamps the pin to 0…3.3 V
                     └─►|─ GND
  CT (−) ────────────► bias node:  3.3 V ─[Ra]─┬─[Rb]─ GND,  10 µF ceramic from node to GND
      compressor channel (12 dB atten.):  Ra = Rb = 10 kΩ   → 1.65 V bias, ±1.3 V swing at LRA fits 0–3.3 V
      fan / furnace channels (0 dB atten., ~0–1 V range):  Ra = 56 kΩ, Rb = 10 kΩ → 0.50 V bias
```

- **Small signals.** The low-range channels use **0 dB attenuation** so the 50–60 mV signals use the
  ADC's finest range. With a 0.5 V bias, peaks up to about ±0.4 V stay in range, which covers fan start
  and furnace heat current.

### 4.4 Outdoor Y / contactor-coil optos

| Ch | Across | Meaning |
|---|---|---|
| Y at unit | unit's **Y1 / C** low-voltage connection | the call arrived outdoors |
| Contactor coil | the **two contactor coil terminals only** | the call passed S4 (and S173 if fitted) |

- **Discriminator.** Y at unit on + coil off = a safety is open (S4 stays open until someone presses its
  reset). Y on + coil on + no compressor current = contactor, compressor or capacitor.
- **The clean discriminator is the contactor-coil opto,** because it sits in parallel with the coil
  only.
- **Protecting the S4/S173 chain.** The Y-at-unit opto is a few-mA path from Y to C, parallel to the
  whole S4 → S173 → coil chain.
  - It must stay a few mA: 3.3 kΩ resistor at the pickup, **never upsized** to a relay or LED indicator.
  - It must never be wired to the coil side, where it would sit across the safeties.
- Same pickup rule as §3.3 (R1 at the terminal, fused C reference).

### 4.5 Fan current vs. fan rotation

Current proves the motor circuit is energized and drawing. It **doesn't prove the blade turns**. A
seized bearing or a dead run capacitor gives a stalled PSC motor that still draws current, often
*more* than normal.

- **Use now:**
  - A current *band*: the learned running value ± ~25 % is normal. Well above it, or noisy, means
    stalled-suspect.
  - M5 corroboration: with the compressor running, **condenser leaving air minus entering air** should
    sit at a steady positive value (learn it; often 15–25 °F). A collapsing or erratic ΔT with fan
    current present means stalled-suspect.
- **Optional proof of rotation:**
  - An optical blade-pass tach: a reflective IR sensor under the fan guard counting blade passes into an
    ESPHome `pulse_counter`.
  - A small accelerometer (e.g. LIS3DH) on the fan-motor bracket, reading vibration RMS. ESPHome has no
    spectrum analysis, so treat it as a threshold only.
  - Both are unbuilt ideas: dirt and weather make the optical one fiddly.

### 4.6 ESPHome sketch (outdoor node, part 1; indoor furnace CT is analogous)

```yaml
esphome: { name: hvac-outdoor, friendly_name: HVAC Outdoor }
esp32: { board: esp32-poe-iso, framework: { type: esp-idf } }
# ethernet / api / ota as indoor

sensor:
  - { platform: adc, id: adc_comp, pin: GPIO36, attenuation: 12db }   # older ESPHome: 11db
  - { platform: adc, id: adc_fan,  pin: GPIO39, attenuation: 0db }    # check the board schematic for GPIO39 use

  - platform: ct_clamp
    sensor: adc_comp
    id: comp_a_raw
    internal: true
    sample_duration: 200ms
    update_interval: 1s
    filters:
      - calibrate_linear: [ 0.0 -> 0.0, 0.130 -> 12.0 ]   # placeholders; fill from a clamp meter
      - lambda: return x < 0.5 ? 0.0 : x;
    on_value:
      - binary_sensor.template.publish:
          id: comp_running
          state: !lambda 'return x > 4.0;'
      - binary_sensor.template.publish:
          id: comp_locked
          state: !lambda 'return x > 40.0;'
  - platform: ct_clamp
    sensor: adc_fan
    id: fan_a_raw
    internal: true
    sample_duration: 200ms
    update_interval: 1s
    filters:
      - calibrate_linear: [ 0.0 -> 0.0, 0.060 -> 0.85 ]   # placeholders
      - lambda: return x < 0.08 ? 0.0 : x;
    on_value:
      - binary_sensor.template.publish:
          id: fan_present
          state: !lambda 'return x > 0.35;'

  # Throttled copies for HA / recorder
  - { platform: copy, source_id: comp_a_raw, name: "Compressor Current", unit_of_measurement: A, accuracy_decimals: 1,
      filters: [ or: [ delta: 0.3, heartbeat: 30s ] ] }
  - { platform: copy, source_id: fan_a_raw,  name: "Condenser Fan Current", unit_of_measurement: A, accuracy_decimals: 2,
      filters: [ or: [ delta: 0.05, heartbeat: 30s ] ] }

binary_sensor:
  # Driven directly from the 1-s CT updates (no polling delay)
  - { platform: template, id: comp_running, name: "Compressor Running",             filters: [ delayed_on: 3s, delayed_off: 5s ] }
  - { platform: template, id: fan_present,  name: "Condenser Fan Current Present",  filters: [ delayed_on: 3s, delayed_off: 5s ] }
  - { platform: template, id: comp_locked,  name: "Compressor Locked Rotor",        filters: [ delayed_on: 3s ] }
  - { platform: gpio, name: "Y At Unit",      pin: { number: GPIO32, inverted: true }, filters: [ delayed_off: 60ms, delayed_on: 150ms ] }
  - { platform: gpio, name: "Contactor Coil", pin: { number: GPIO33, inverted: true }, filters: [ delayed_off: 60ms, delayed_on: 150ms ] }
```

⚠ These are placeholder calibration points. The ESP32 ADC is non-linear near the ends of each range,
and the calibration handles that. Option names (`12db`/`11db`, `copy`, `or`) depend on the ESPHome
version.

### 4.7 HA entities

- Outdoor:
  - `sensor.hvac_outdoor_compressor_current`
  - `sensor.hvac_outdoor_condenser_fan_current`
  - `binary_sensor.hvac_outdoor_compressor_running`
  - `binary_sensor.hvac_outdoor_condenser_fan_current_present`
  - `binary_sensor.hvac_outdoor_compressor_locked_rotor`
  - `binary_sensor.hvac_outdoor_y_at_unit`
  - `binary_sensor.hvac_outdoor_contactor_coil`
- Indoor: `sensor.hvac_indoor_furnace_current`, with a template `sensor.hvac_furnace_power_est`
  (A × 120 × assumed PF). Label it an estimate unless you use option b.
- Optional: `sensor.energy_monitor_phase_c_current` (3EM, once the entities are re-enabled).

### 4.8 Safety and install

- **Kill power first.** Pull the disconnect and verify dead with a meter at the contactor line side.
  The disconnect's line side stays live.
- **Discharge the dual run capacitor** through a resistor (about 20 kΩ 5 W) before your hands go near it.
- **Clamp only.** Don't cut or re-terminate any conductor.
- **Route the CT leads** out through an existing knockout with a bushing, clear of the fan blade and the
  compressor terminal cover. Close the cover fully.
- **Furnace CT:** power off at the service switch *and* confirm dead. The switch may not break a
  miswired neutral.
- **Enclosures.** Outdoor: NEMA 4X, glands on the bottom, drip loops, shaded or north-facing, on standoffs
  with desiccant. Not on the condenser cabinet.

### 4.9 Commissioning (no fan-disconnect tests)

1. **Calibrate against a clamp meter during normal operation.** Clamp the meter on the same conductor
   and record compressor running amps (about 9–13 A expected), fan running amps (0.6–1.0 A) and furnace
   blower amps. Enter the ESP raw values into `calibrate_linear`.
2. **Never run the compressor with the fan disconnected to "test" the alarm.** S4 trips at about 590 psig
   and is manual-reset, and in Austin heat head pressure can climb there quickly.
3. **Test the alarm logic with simulated inputs instead:**
   - Temporarily publish fake states: a `binary_sensor.template.publish` from an ESPHome test button, or
     HA `homeassistant.update_entity` with test template entities.
   - Or run the monitor's rule against recorded events, the same way the replay validated the cooling-cycle
     detector.
4. **Cross-check** compressor amps against the Shelly leg step (W ≈ 240 × A × PF, PF ≈ 0.85–0.95), and
   the furnace amps against the monitor's `sensor.hvac_blower_watts` (~176 W ≈ 1.5 A).

**Effort:** 1 day (outdoor box, three CTs, calibration).

---

## 5. Module 5: air temperatures

### 5.1 Points

| Point | Sensor | Where | Why |
|---|---|---|---|
| **Supply air** | DS18B20 in a stainless sheath (**temperature only**) | supply trunk after the coil, **before the zone dampers**, out of line of sight of the coil (the DAT zone in the 6203 manual), ≥ 12–18 in. past the plenum for mixing | Near-saturated supply air and droplets wreck cheap RH sensors (HVAC-tech feedback). Dry bulb is all the target-ΔT method needs |
| **Return air** | SHT45 (T + RH) | return plenum upstream of the blower, downstream of the grille filters | entering DB + WB → target ΔT |
| Condenser entering air | DS18B20 | 2–4 in. off the coil face, away from the sun, in a radiation shield (louvered or a white PVC tee) | M2 fan corroboration; the IOM tables key on entering-coil air |
| Condenser leaving air | DS18B20 | under the top grille, out of the blade path | condenser air ΔT |

### 5.2 What coil ΔT tells you (and doesn't)

Coil ΔT = return DB − supply DB. **On its own it's a weak diagnostic.** It moves with latent load
(return RH), airflow, charge and runtime.

- **Low indoor airflow raises ΔT.** Less air per BTU means colder supply air.
- **Low charge usually lowers capacity, and with it ΔT.**
- **Other causes overlap.** A dirty coil or a restriction can go either way. That's why ΔT alone can't
  tell you the cause.

Use it only against the **Lennox target-ΔT chart** (14ACX IOM Fig. 19, ±3 °F; rows = return DB, columns
= return WB):

| DB \ WB | 57 | 58 | 59 | 60 | 61 | 62 | 63 | 64 | 65 | 66 | 67 | 68 | 69 | 70 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 80 | 24 | 24 | 24 | 23 | 23 | 22 | 22 | 22 | 20 | 19 | 18 | 17 | 16 | 15 |
| 78 | 23 | 23 | 23 | 22 | 22 | 21 | 21 | 20 | 19 | 18 | 17 | 16 | 15 | 14 |
| 76 | 22 | 22 | 22 | 21 | 21 | 20 | 19 | 19 | 18 | 17 | 16 | 15 | 14 | 13 |
| 74 | 21 | 21 | 21 | 20 | 19 | 19 | 18 | 17 | 16 | 16 | 15 | 14 | 13 | 12 |
| 72 | 20 | 20 | 19 | 18 | 17 | 17 | 16 | 15 | 15 | 14 | 13 | 12 | 11 | 10 |
| 70 | 19 | 19 | 18 | 18 | 17 | 17 | 16 | 15 | 15 | 14 | 13 | 12 | 11 | 10 |

- Measured − target > +3 °F → airflow low. Below −3 °F → airflow high (Lennox's rule).
- Evaluate only after **≥ 10 min of continuous compressor run.**

**Heating: the ignition proof and an independent CFM check.** Output is 53,000 BTU/h, so
**CFM ≈ 53000 / (1.08 × rise)** read at ≥ 10 min into the cycle. A 50 °F rise ≈ 980 CFM; 71 °F ≈ 690 CFM
(the "brown tap is Low" scenario). A rising supply temperature after W is also the real proof of
ignition.

### 5.3 ESPHome (indoor part 2; outdoor adds two probes on its own 1-Wire bus)

```yaml
one_wire:
  - platform: gpio
    pin: GPIO4            # 4.7k pull-up to 3.3 V
sensor:
  - platform: dallas_temp
    address: 0x0000000000000000   # fill from the boot log
    name: "Supply Air Temperature"
    update_interval: 10s
    filters: [ median: { window_size: 5, send_every: 3 } ]
  - platform: sht4x               # same I2C bus as the MCP23017 (0x20) and SDP810 (0x25)
    address: 0x44
    temperature: { name: "Return Air Temperature" }
    humidity:    { name: "Return Air Humidity" }
    precision: High
    heater_max_duty: 0.0
    update_interval: 15s
```

Keep the SHT45 lead ≤ 1 m (I²C at 50 kHz), or use a probe-style SHT45 on its own cable. Seal the duct
penetrations with grommets and foil tape. Give the supply probe cable a drip loop.

### 5.4 HA entities and templates

- Probes:
  - `sensor.hvac_indoor_supply_air_temperature`
  - `sensor.hvac_indoor_return_air_temperature`
  - `sensor.hvac_indoor_return_air_humidity`
  - `sensor.hvac_outdoor_condenser_entering_air_temperature`
  - `sensor.hvac_outdoor_condenser_leaving_air_temperature`
- Templates: `sensor.hvac_return_wet_bulb`, `sensor.hvac_coil_delta_t`, `sensor.hvac_coil_target_delta_t`
  (code below).

```yaml
- sensor:
    - unique_id: hvac_return_wet_bulb
      name: HVAC Return Wet Bulb
      unit_of_measurement: °F
      # Stull (2011) wet bulb at sea-level pressure, about ±1 °F in this range
      state: >-
        {% set tf = states('sensor.hvac_indoor_return_air_temperature') | float(none) %}
        {% set rh = states('sensor.hvac_indoor_return_air_humidity') | float(none) %}
        {% if tf is none or rh is none %}{{ none }}{% else %}
          {% set t = (tf - 32) * 5 / 9 %}
          {% set tw = t * atan(0.151977 * (rh + 8.313659) ** 0.5) + atan(t + rh) - atan(rh - 1.676331)
                      + 0.00391838 * rh ** 1.5 * atan(0.023101 * rh) - 4.686035 %}
          {{ (tw * 9 / 5 + 32) | round(1) }}
        {% endif %}
    - unique_id: hvac_coil_delta_t
      name: HVAC Coil Delta T
      unit_of_measurement: °F
      availability: >-
        {{ has_value('sensor.hvac_indoor_return_air_temperature')
           and has_value('sensor.hvac_indoor_supply_air_temperature') }}
      state: >-
        {{ (states('sensor.hvac_indoor_return_air_temperature') | float
            - states('sensor.hvac_indoor_supply_air_temperature') | float) | round(1) }}
    - unique_id: hvac_coil_target_delta_t
      name: HVAC Coil Target Delta T
      unit_of_measurement: °F
      state: >-
        {% set T = {80: [24,24,24,23,23,22,22,22,20,19,18,17,16,15],
                    78: [23,23,23,22,22,21,21,20,19,18,17,16,15,14],
                    76: [22,22,22,21,21,20,19,19,18,17,16,15,14,13],
                    74: [21,21,21,20,19,19,18,17,16,16,15,14,13,12],
                    72: [20,20,19,18,17,17,16,15,15,14,13,12,11,10],
                    70: [19,19,18,18,17,17,16,15,15,14,13,12,11,10]} %}
        {% set db = states('sensor.hvac_indoor_return_air_temperature') | float(75) %}
        {% set wb = states('sensor.hvac_return_wet_bulb') | float(62) %}
        {% set row = [70, [80, ((db / 2) | round(0) * 2) | int] | min] | max %}
        {% set col = [0, [13, (wb | round(0) | int) - 57] | min] | max %}
        {{ T[row][col] }}
```

### 5.5 Commissioning

- **Waterproof DS18B20 probes only:** ice bath (32.0 °F) plus a reference thermometer, then room air.
  Apply `offset` filters if they're off by more than ±0.5 °F.
- **Don't ice-bath the SHT45 breakout.** Compare it in **controlled air** instead: in a closed box or bag
  beside a trusted reference (Aranet4 or ecobee) for 30 min, away from any draft. Expect ±0.4 °F and
  ±2–3 % RH.
- **Outdoors:** with the unit off and in shade, entering ≈ leaving ≈ the weather station.

**Effort:** 2 h indoor (attic), 1 h outdoor.

---

## 6. Module 3: refrigerant diagnostics, DEFERRED

No tech visit is planned, so this module is **deferred**. It's kept here, with corrections, so the
outdoor box can be sized for it now and the tech gets a ready plan when a visit happens.

### 6.1 Division of labour

| Who | Does what |
|---|---|
| **Licensed tech (EPA Section 608)** | Everything that can release refrigerant: tees on the service ports, fitting transducers, fresh cores and caps, leak check (electronic + bubbles). Also verifies charge with their own gauges and **records the unit's own charging targets** (label/manufacturer data) on the same visit |
| **You** | ADS1115 and wiring, strap-on line probes (no refrigerant opened), ESPHome/HA, comparing against the tech's gauges |

Don't open a service port yourself. R-410A liquid runs at 300–480 psig here, and in the US that work
requires Section 608 certification.

### 6.2 Where

- Suction: the vapor service valve port at the condenser. Liquid: the liquid service valve port.
- The tees keep both ports usable for gauges.
- ❓ Whether S4 is on a Schrader-type fitting is irrelevant if the service ports are used.

### 6.3 Parts (confirm the connection type of every part before ordering)

| Part | Spec | Example | ≈ Cost |
|---|---|---|---|
| Transducers ×2 | ratiometric 0.5–4.5 V at 5 V, IP65, R-410A/POE. **Both rated ≥ 800 psig** (hot climate: a sun-baked unit's standstill pressure approaches saturation at ~130 °F, ≈ 480 psig on the suction side too) | **Danfoss AKS 32R 060G6810** (−14.5…855 psig) for both. Per the reviewers it's a **female 1/4" SAE connection with core depressor**. ❓ Verify on the Danfoss datasheet. (060G0090, −14.5…493 psig, is male flare with no depressor: better suction resolution but little margin) | about $100–200 each (EU €96–272 seen for the AKS 32R line; US price not verified) |
| Budget alternative | generic stainless 0–800 psi, 5 V, 0.5–4.5 V, 1/4 SAE female with depressor | Amazon/AliExpress | $20–40 each (not verified; accuracy and seals unknown) |
| Tees | 1/4" FE SAE swivel tee access valve **with depressor** (the swivel goes on the service port; the tee ports carry cores and caps) | **JB Industries A31851** (3-pk) | about $25–40 (not verified) |
| Mating | Female-with-depressor transducer onto a tee port: direct, **provided the tee port has a Schrader core** for the depressor to open. With a male transducer you'd need an FE×FE coupler with depressor. The tech confirms the core arrangement for every joint | JB A31734 / Supco SF2000-type ($12–18 seen) | $0–35 |
| Cable | DIN 175301-803-A plug with 3-core shielded UV cable | | $15–25 |
| Line probes | DS18B20 stainless ×2, strapped parallel to the pipe with thermal paste and a worm clamp, under 1/2" closed-cell insulation + UV tape. **Trend-grade, not charging-grade** (±0.9 °F probe accuracy, plus strap-on contact and lag) | | $12–15 |
| ADC | ADS1115 (0x48), powered at 3.3 V, with 0.1 % 10k/15k dividers | Adafruit #1085 or generic | $15 |

⚠ **Permanent tees add flare joints and cores under constant pressure.** Ask for new cores, flares
torqued to spec, caps on the tees' gauge ports, a leak check, and a re-check at the next visit. If the
system is ever opened for other work, **brazed-in access fittings** dedicated to the transducers are
cleaner.

### 6.4 Wiring

```
 5 V (regulated) ──┬──► transducer #1 (+) ─┐
                   ├──► transducer #2 (+)   │ (0 V) → GND
                   └─[10k]─┬─[15k]─ GND ; mid → ADS1115 A2   (supply sense ×0.6)
 transducer #1 sig ─[10k]─┬─[15k]─ GND ; mid → A0 (suction)
 transducer #2 sig ─[10k]─┬─[15k]─ GND ; mid → A1 (liquid)
 ratio = V_sig / V_supply (dividers and supply drift cancel)
```

### 6.5 ESPHome (outdoor part 3, both transducers −14.5…855.5 psig)

```yaml
ads1115: [{ address: 0x48 }]
sensor:
  - { platform: ads1115, multiplexer: 'A0_GND', gain: 4.096, id: v_suc, update_interval: 2s }
  - { platform: ads1115, multiplexer: 'A1_GND', gain: 4.096, id: v_liq, update_interval: 2s }
  - { platform: ads1115, multiplexer: 'A2_GND', gain: 4.096, id: v_5v,  update_interval: 2s }
  - platform: template
    name: "Suction Pressure"
    id: p_suc
    unit_of_measurement: psi
    update_interval: 5s
    lambda: |-
      float r = id(v_suc).state / id(v_5v).state;
      if (isnan(r) || r < 0.03 || r > 0.97) return NAN;       // open/short -> unavailable
      return -14.5 + (r - 0.10) / 0.80 * (855.5 + 14.5);
    filters: [ median: { window_size: 5, send_every: 1 } ]
  - platform: template
    name: "Liquid Pressure"
    id: p_liq
    unit_of_measurement: psi
    update_interval: 5s
    lambda: |-
      float r = id(v_liq).state / id(v_5v).state;
      if (isnan(r) || r < 0.03 || r > 0.97) return NAN;
      return -14.5 + (r - 0.10) / 0.80 * (855.5 + 14.5);
    filters: [ median: { window_size: 5, send_every: 1 } ]
  - { platform: dallas_temp, address: 0x0000000000000000, name: "Suction Line Temperature", id: t_suc, update_interval: 5s }
  - { platform: dallas_temp, address: 0x0000000000000000, name: "Liquid Line Temperature",  id: t_liq, update_interval: 5s }
  - platform: template
    name: "Suction Saturation Temperature"
    id: sat_suc
    unit_of_measurement: °F
    update_interval: 5s
    lambda: |-
      // DEW-point fit, valid ONLY for the suction band: 0-70 °F sat (48-201 psig), ±0.07 °F
      float p = id(p_suc).state;
      if (isnan(p) || p < 48 || p > 201) return NAN;
      float L = logf(p + 14.696);
      return -80.17673f - 9.39401f * L + 6.94572f * L * L;
  - platform: template
    name: "Liquid Saturation Temperature"
    id: sat_liq
    unit_of_measurement: °F
    update_interval: 5s
    lambda: |-
      // BUBBLE-point fit, valid 60-150 °F sat (171-614 psig), ±0.03 °F
      float p = id(p_liq).state;
      if (isnan(p) || p < 171 || p > 614) return NAN;
      float L = logf(p + 14.696);
      return -32.73811f - 27.5815f * L + 8.68219f * L * L;
  - { platform: template, name: "Superheat",  unit_of_measurement: °F, update_interval: 5s,
      lambda: 'return id(t_suc).state * 1.8f + 32.0f - id(sat_suc).state;' }
  - { platform: template, name: "Subcooling", unit_of_measurement: °F, update_interval: 5s,
      lambda: 'return id(sat_liq).state - (id(t_liq).state * 1.8f + 32.0f);' }
```

⚠ With the 855 psig range on the suction side, the transducer error (±0.3 % typical / ±0.8 % max FS ≈
±2.6 / ±7 psi) is about ±1–3 °F of saturation temperature near 140 psig. Together with the strap-on
probes, superheat is **trend-grade**.

### 6.6 R-410A pressure–temperature reference (CoolProp, psig)

| Sat °F | Dew (suction) | Bubble (liquid) | | Sat °F | Dew | Bubble |
|---|---|---|---|---|---|---|
| 30 | 97.0 | 97.4 | | 90 | 274.5 | 275.3 |
| 40 | 118.4 | 118.8 | | 100 | 317.6 | 318.5 |
| 45 | 130.1 | 130.6 | | 110 | 365.4 | 366.5 |
| 50 | 142.6 | 143.1 | | 120 | 418.3 | 419.5 |
| 60 | 170.1 | 170.7 | | 130 | 476.8 | 478.0 |
| 70 | 201.1 | 201.7 | | 140 | 541.5 | 542.6 |
| 80 | 235.7 | 236.5 | | 150 | 613.0 | 613.9 |

This matches IOM Table 3 (40 °F → 118, 100 °F → 317).

**Formula:** T_sat(°F) = a + b·L + c·L², where L = ln(psig + 14.696).

| Fit | Valid band | a | b | c |
|---|---|---|---|---|
| Dew (suction) | 0–70 °F only | −80.17673 | −9.39401 | 6.94572 |
| Bubble (liquid) | 60–150 °F only | −32.73811 | −27.5815 | 8.68219 |

### 6.7 Using the numbers (TXV system)

**Evaluate only at steady state:** compressor on ≥ 10–15 min continuously, with suction pressure
changing < 2 psi over 3 min. Today's upstairs calls (median ≈ 6 min) mostly won't qualify, so fix the
dampers and cycling first.

**Targets** come from the unit's label and the tech's baseline, not from this doc. Direction of change
(textbook):

| Condition | Suction / SH | Head / SC | Amps |
|---|---|---|---|
| Undercharge / leak | low / high SH | low / low SC | low |
| Overcharge | normal-high / low-normal SH | high / high SC | high |
| Restriction (drier/TXV) | low / high SH | normal-high / high SC | low |
| Low indoor airflow | low / low-normal SH | low-normal | low; coil ΔT above target, TESP high, DAT cutoffs |
| Condenser airflow (fan, dirty coil) | high | high head | high; condenser air ΔT abnormal |
| Weak compressor | high | low | low |

### 6.8 HA entities

- `sensor.hvac_outdoor_suction_pressure`
- `sensor.hvac_outdoor_liquid_pressure`
- `sensor.hvac_outdoor_suction_line_temperature`
- `sensor.hvac_outdoor_liquid_line_temperature`
- `sensor.hvac_outdoor_suction_saturation_temperature`
- `sensor.hvac_outdoor_liquid_saturation_temperature`
- `sensor.hvac_outdoor_superheat`
- `sensor.hvac_outdoor_subcooling`
- `binary_sensor.hvac_refrigerant_steady` (template gate)

### 6.9 For the tech, when a visit happens

1. Confirm the TXV (bulb on the suction line) and its suitability for this condenser/coil match.
2. Charge check using **this unit's label/manufacturer method**. Record liquid/suction psig, line
   temperatures, outdoor and return DB/WB, and the targets used.
3. OK to leave tees + transducers permanently? Confirm the connection types and core arrangement for
   the parts chosen.
4. Is this a 14ACXS with S173? Any low-pressure switch?
5. Capacitor µF, contactor condition, fan amps.
6. **What's the approved airflow (CFM) target** for this condenser + CHX35 combination and the right
   cooling tap? TESP at the correct taps (M4).

---

## 7. Module 4: airflow (total external static pressure → CFM)

### 7.1 Principle

The EL180's constant-torque ECM delivers a fixed torque per tap, so airflow depends on the static
pressure the furnace works against. The Lennox table is **furnace-only** external static (less filter).
Blower watts measured on the furnace circuit (M2) are the cross-check.

**EL180UH070E36B performance (less filter), CFM / W:**

| ESP in. w.g. | High | Med-High | Medium | Med-Low | Low |
|---|---|---|---|---|---|
| 0.00 | 1415 / 265 | 1330 / 170 | 1215 / 135 | 1175 / 125 | 1075 / 85 |
| 0.10 | 1415 / 280 | 1295 / 170 | 1145 / 145 | 1130 / 130 | 955 / 95 |
| 0.20 | 1355 / 290 | 1225 / 185 | 1110 / 150 | 1080 / 140 | 885 / 100 |
| 0.30 | 1330 / 300 | 1190 / 200 | 1060 / 160 | 1035 / 155 | 825 / 110 |
| 0.40 | 1290 / 310 | 1155 / 205 | 1015 / 175 | 970 / 160 | 770 / 120 |
| 0.50 | 1245 / 325 | 1115 / 215 | 980 / 180 | 930 / 170 | 695 / 125 |
| 0.60 | 1225 / 335 | 1045 / 230 | 920 / 190 | 865 / 180 | 625 / 135 |
| 0.70 | 1190 / 350 | 1000 / 235 | 855 / 205 | 790 / 190 | 540 / 140 |
| 0.80 | 1160 / 365 | 925 / 245 | 790 / 205 | 735 / 200 | 445 / 145 |

The measured 176 W on the cooling tap fits **Medium at about 0.45 in.** (≈ 1000 CFM) **or Med-Low at
about 0.6 in.** (≈ 865 CFM). Watts can't tell those apart; static pressure can.

### 7.2 Probe placement (furnace-only static)

- **Supply tap: between the furnace outlet and the cased coil.** The table's external static is what
  the *furnace* sees at its outlet, and everything downstream (coil, plenum, ducts) is included
  automatically. Measuring **above the coil would leave out the coil's drop and overstate CFM.**
  - In this attic install the unit is probably horizontal, so the tap goes in the transition or coil
    cabinet's entry section, upstream of the coil face.
  - ⚠ Inspect before drilling: look inside with a flashlight or borescope, stay above the drain pan,
    and never drill where coil tubes or the pan could be hit. If there's no safe spot, use the furnace's
    supply-side flange area.
- **Return tap:** return plenum/transition between the last filter and the furnace inlet. Grille
  filters are external to the furnace, so their drop is correctly included.
- **Tips:** proper static pressure tips (Dwyer A-301 style, about $15–25, not verified) or 1/4" copper
  tube cut flush with the inside of the duct, burr-free, grommet + mastic. They double as the tech's
  test ports.
- **Tubing:** 3/16"–1/4" ID. Supply → "+", return → "−". No low spots, away from the flue.
- **Optional:** a second SDP810 across the coil (furnace-outlet tap vs. a tap above the coil) gives the
  **coil pressure drop**, useful for wet/dirty/icing trends.

### 7.3 Sensor

**Sensirion SDP810-500Pa** (±500 Pa = ±2.0 in. w.g., I²C **address 0x25**; $29.39 at Digi-Key, **V**).

- ESPHome's `sdp3x` platform supports the SDP800 series. Its default address is 0x21, so **set 0x25**
  (esphome/issues#5223).
- **ESPHome publishes this sensor in hPa.** in. w.g. = **hPa / 2.49089** (1 in. w.g. = 249.089 Pa =
  2.49089 hPa).

```yaml
sensor:
  - platform: sdp3x
    address: 0x25
    id: tesp_hpa
    name: "External Static Pressure Raw"
    measurement_mode: differential_pressure
    update_interval: 5s
    internal: true
  - platform: template
    name: "External Static Pressure"
    id: tesp
    unit_of_measurement: "inH₂O"
    accuracy_decimals: 3
    update_interval: 15s
    lambda: return id(tesp_hpa).state / 2.49089;      // hPa -> in. w.g.
    filters: [ median: { window_size: 7, send_every: 3 } ]
```

### 7.4 HA: CFM for the tap actually driven

Helpers: `input_select.hvac_cool_tap_speed`, `input_select.hvac_heat_tap_speed` and
`input_select.hvac_fan_tap_speed`, each with the options High / Med-High / Medium / Med-Low / Low. Set
them from the door diagram (❓ §11 Q2). Which one applies is decided by the **live tap terminal**, not
by G. G alone may mean the FAN tap.

```yaml
- sensor:
    - unique_id: hvac_airflow_cfm
      name: HVAC Airflow
      unit_of_measurement: CFM
      availability: >-
        {% set p = states('sensor.hvac_indoor_external_static_pressure') | float(-1) %}
        {{ (is_state('binary_sensor.hvac_indoor_blower_cool_tap', 'on')
            or is_state('binary_sensor.hvac_indoor_blower_heat_tap', 'on')
            or is_state('binary_sensor.hvac_indoor_blower_fan_tap', 'on'))
           and 0 <= p <= 0.8 }}
      state: >-
        {% set tab = {'High':     [1415,1415,1355,1330,1290,1245,1225,1190,1160],
                      'Med-High': [1330,1295,1225,1190,1155,1115,1045,1000,925],
                      'Medium':   [1215,1145,1110,1060,1015,980,920,855,790],
                      'Med-Low':  [1175,1130,1080,1035,970,930,865,790,735],
                      'Low':      [1075,955,885,825,770,695,625,540,445]} %}
        {% set sel = 'input_select.hvac_cool_tap_speed'
             if is_state('binary_sensor.hvac_indoor_blower_cool_tap', 'on')
             else ('input_select.hvac_heat_tap_speed'
                   if is_state('binary_sensor.hvac_indoor_blower_heat_tap', 'on')
                   else 'input_select.hvac_fan_tap_speed') %}
        {% set row = tab[states(sel)] %}
        {% set p = states('sensor.hvac_indoor_external_static_pressure') | float %}
        {% set i = [7, (p / 0.1) | int] | min %}
        {% set f = p / 0.1 - i %}
        {{ (row[i] + (row[i + 1] - row[i]) * f) | round(0) }}
- binary_sensor:
    - unique_id: hvac_static_out_of_table
      name: HVAC Static Out Of Table
      # Blower running but TESP outside the table (> 0.8 in. = severe restriction, e.g. dampers or
      # filter; < 0 = tubes swapped or blocked). A fault to report, never clamped silently.
      delay_on: { minutes: 2 }
      state: >-
        {% set p = states('sensor.hvac_indoor_external_static_pressure') | float(0) %}
        {{ (is_state('binary_sensor.hvac_indoor_blower_cool_tap', 'on')
            or is_state('binary_sensor.hvac_indoor_blower_heat_tap', 'on')
            or is_state('binary_sensor.hvac_indoor_blower_fan_tap', 'on'))
           and (p > 0.8 or p < 0) }}
```

**Airflow target:** don't guess a number here. The right CFM comes from the approved condenser/coil
combination and Lennox data. That's a question for the tech (§6.9 item 6).

### 7.5 Commissioning

- **Zero:** blower off → 0.000 ± 0.005 in.
- **Manometer check:** fan-only, compare against a manometer on the same tips (±0.02 in.). A tech's
  manometer, or an inexpensive digital manometer of your own.
- **Watts cross-check:** furnace-circuit watts (M2) against the table watts at the measured TESP for the
  driven tap (±10–15 W).
- **Record TESP per damper state:** both zones, upstairs-only, downstairs-only. The upstairs-only number
  (the big zone closed) is the damper-repair baseline. Repeat after the repair and after filter changes.

**Effort:** 2 h in the attic.

---

## 8. Module 6: condensate

### 8.1 Hardware

- **Keep the existing condensate safety switch as the protective device.** ❓ Its location (primary-pan
  aux port, secondary pan, or inline) and the conductor it breaks (Y or R) are unconfirmed (§11 Q3).
- An attic air handler over living space should also have a **secondary pan** under it (code-typical,
  IRC M1411.3). Check for one while you're up there.
- Add an **independent Zigbee water sensor** (Aqara-class, about $15–20) in the secondary pan, or at its
  lowest corner. It has its own battery and radio, so it still alarms after the float has cut the power.
- A Rectorseal SS2 (about $25–40, not verified) is only needed if the existing switch is missing or
  failed.

### 8.2 Sensing the switch without weakening it

**Each side of the switch is sensed against its own transformer common. Never put anything across the
switch contacts.** With the pickups built as in §3.3 (resistor at the terminal), even two pickups
shorted together only pass about 5 mA: nowhere near enough to hold in a contactor, so the switch still
does its job.

| If the switch is in | Upstream channel | Downstream channel | Trip = |
|---|---|---|---|
| R, between the furnace R and the 6203 RC | ch 1 furnace R | ch 2 6203 RC | ch 1 on, ch 2 off |
| Y, between the 6203 Y and the furnace Y | ch 3 6203 Y | ch 4 furnace Y | ch 3 on, ch 4 off > 5 s |
| Y, on the condenser feed after the furnace strip | ch 4 furnace Y | outdoor Y at unit | ch 4 on, Y-at-unit off > 5 s (and contactor off) |

Whichever case applies, one existing pair straddles the switch. Once the location is known, only the
template changes:

```yaml
- binary_sensor:
    - unique_id: hvac_condensate_trip
      name: HVAC Condensate Trip
      device_class: moisture
      delay_on: { seconds: 5 }
      # Example for "switch in Y between the 6203 and the furnace strip". Swap the pair per the table.
      state: >-
        {{ is_state('binary_sensor.hvac_sensing_ok', 'on')
           and is_state('binary_sensor.hvac_indoor_zone_panel_y', 'on')
           and is_state('binary_sensor.hvac_indoor_y', 'off') }}
```

### 8.3 HA

`binary_sensor.hvac_condensate_trip` and `binary_sensor.<zigbee>_water_leak`: both 🚨 (Ryan: "condensate
float").

### 8.4 Commissioning

Lift the float by hand during a cooling call (or fill the switch's test cup):

- The condenser must stop, which proves the safety still works.
- `hvac_condensate_trip` turns on within about 5 s.
- The leak puck alarms when wet.

**Effort:** 30–60 min.

---

## 9. Signal → monitor rule map

Existing event kinds: `start`, `start_measured`, `stop`, `blower`, `mid_call_stop`, `changeover`,
`no_start`, `no_restart`, `uncertain_stop`, `blower_missing`, `heat_response`, `heat_no_response`.
New kinds are marked **new**.

| New signal | Rule it improves or enables | Tier |
|---|---|---|
| `hvac_sensing_ok` (heartbeats) | Gate every 24 V-based rule. **new** `sensing_lost` when it drops (a sense fuse, the ESP, or a real loss of 24 V; the monitor can't tell which, so say so) | held (🚨 if indoor > 80 °F) |
| `hvac_indoor_y` | Replaces `sensor.ac_compressor_state` as the call input to Cooling Cycles. No-start window: 5.5 min → ~90 s after Y | — |
| Y at stop time | `mid_call_stop` splits into **new** `protective_stop` (Y still on) vs **new** `dat_cutoff` (§3.6 template) vs `changeover` | `protective_stop` held (🚨 ≥ 2/h); `dat_cutoff` logged, 🚨 when repeated (e.g. ≥ 3 in 2 h; tune it, since upstairs-only calls with the big zone closed are the likely trigger) |
| Y on + no compressor ≥ 90 s | `no_start` becomes certain | held |
| Y at unit / contactor coil | **new** `safety_open` (Y at unit, no coil: S4/S173) vs `no_start` with the coil on (contactor, compressor, capacitor) | held; S4 manual-reset message |
| Compressor running + fan current absent | **new** `condenser_fan_missing` (compressor ≥ 20 s, fan < 0.35 A, held 30 s) | 🚨 any hour |
| Fan current outside its learned band / condenser air ΔT collapse | **new** `condenser_fan_suspect` (stalled/capacitor) | held |
| Compressor current | start/stop from amps (no EV mask); **new** `compressor_overload` (coil on, fan on, compressor ≈ 0, recurring); **new** `locked_rotor` (≥ 40 A for ≥ 3 s). Not inrush/hard-start (sampling) | held |
| Furnace CT + tap channels | `blower` / `blower_missing` measured while running, keyed to the live tap | 🚨 as today |
| W + heat rise (M5) + furnace CT | `heat_response` / `heat_no_response`: **the heat rise is the ignition proof** (the HEAT tap alone isn't). W on and no supply rise ≥ 15 °F within 5 min → `heat_no_response` without waiting for 10 learning samples | held |
| Damper NO channels | Context (which zone had the air); the damper-leak script; TESP per damper state | — |
| Supply T | Confirms `dat_cutoff`; coil-icing trend | — |
| Coil ΔT vs target (≥ 10 min run) | **new** `airflow_suspect` (> +3 °F on 3 qualifying cycles) | digest |
| TESP / CFM / `hvac_static_out_of_table` | Filter-loading and damper trends vs `input_datetime.hvac_filters_changed`; out-of-table = **new** `static_fault` | digest / held |
| Heat rise out of 40–70 °F | **new** `heat_rise_out_of_range` | held |
| Condensate trip / leak puck | **new** `condensate_trip` | 🚨 any hour |
| (M3, deferred) SH/SC/pressures at steady state | Drift vs the tech's baseline → **new** `charge_suspect` | held / digest |

Wiring these in is a later software task. This doc pins down the inputs and their names.

---

## 10. Bill of materials

Prices are approximate USD. **V** = verified on a retailer/distributor page; everything else is an
estimate.

| Module | Item | Qty | Each | Line | Where |
|---|---|---|---|---|---|
| **M1** | Olimex ESP32-POE-ISO (-IND if available) | 1 | $31–40 (std **V** $29.93–31.09) | $35 | Digi-Key / Mouser / Olimex |
| | MCP23017 module | 1 | $5 | $5 | Amazon / Adafruit |
| | H11AA1 AC-input opto | 12 | $0.80 | $10 | Digi-Key / Mouser |
| | 3.3 kΩ 1 W (+ 1.8 kΩ 1 W spares), 10 kΩ pull-ups, 1 µF ceramic, 4.7 kΩ 1 W bleeders | kit | — | $10 | " |
| | Perfboard/PCB + pluggable terminal blocks | 1 | — | $15 | " |
| | Inline fuse holders + 250 mA fast fuses (F1, F2 + spares) | 2 | $5 | $10 | hardware / Digi-Key |
| | Heat-shrink, ferrules, piggyback spades | — | — | $8 | |
| | 18/8 + 2× 18/5 thermostat cable | 3 | $10 | $30 | hardware store |
| | Barrier strips (F, Z, 6203 splice) | 3 | $4 | $12 | |
| | Gasketed polycarbonate box ~200×150×90 + glands | 1 | $25 | $25 | Amazon / AutomationDirect |
| | PoE injector (802.3af), if no PoE switch port | 1 | $15 | $15 | |
| | **M1 subtotal** | | | **≈ $175** | Option B relays: + ~$120–240 |
| **M6** | Zigbee water leak sensor | 1 | $18 | $18 | Amazon |
| | Rectorseal SS2 (only if the existing switch is missing/failed) | 0–1 | $30 | $0–30 | Ferguson / SupplyHouse |
| | **M6 subtotal** | | | **$18–48** | |
| **M2** | Olimex ESP32-POE-ISO (outdoor) | 1 | $31–40 | $35 | |
| | Compressor CT 30 A / 0.333 V, 600 V leads (Magnelab SCT-0400-030 class) | 1 | $30–40 | $35 | Kele / Newark / Amazon |
| | Fan CT 5 A / 0.333 V (Magnelab SCT-0400-005) | 1 | $25–40 | $30 | " |
| | Furnace CT 10 A / 0.333 V (Magnelab SCT-0400-010 class; indoor node) | 1 | $25–40 | $30 | " |
| | Protection + bias (BAT54S, 1 kΩ, dividers, 10 µF) ×3 channels | kit | — | $6 | |
| | Outdoor optos + pickup resistors/fuse | 2 | — | $6 | |
| | NEMA 4X box ~200×150×100 + PG glands + desiccant | 1 | $30 | $30 | |
| | Outdoor/UV Cat6 (short run) + PoE injector | 1 | $35 | $35 | |
| | Optional: Shelly gen1-3EM clamp for phase C (❓ part no.) | 0–1 | ? | — | Shelly |
| | Optional: Shelly Pro EM-50 | 0–1 | $119.95 **V** | — | ameriDroid |
| | **M2 subtotal** | | | **≈ $207** | |
| **M5** | DS18B20 stainless probes (5-pack: supply + 2 outdoor air + 2 for M3) | 1 | $13 | $13 | Amazon |
| | SHT45 breakout or probe | 1 | $13–25 | $18 | Adafruit / Amazon |
| | Radiation shield parts, grommets, foil tape | — | — | $12 | |
| | **M5 subtotal** | | | **≈ $43** | |
| **M4** | Sensirion SDP810-500Pa (+1 optional for coil ΔP) | 1 | $29.39 **V** | $29 | Digi-Key |
| | Static pressure tips (or DIY copper) | 2 | $15–25 | $40 | supply house / Amazon |
| | Tubing 3/16" ID, 10 ft | 1 | $8 | $8 | |
| | **M4 subtotal** | | | **≈ $77** | |
| **M3 (deferred)** | Transducers ≥ 800 psig ×2 (Danfoss 060G6810; generic $20–40) | 2 | $100–200 | $40–400 | distributor / Danfoss; generic Amazon |
| | Swivel tee access valves w/ depressor (JB A31851 3-pk) | 1 | $30 | $30 | SupplyHouse |
| | Couplers if needed | 0–2 | $12–18 | $0–35 | |
| | DIN plug cables + outdoor cable | 2 | $15 | $30 | |
| | ADS1115 + 0.1 % dividers | 1 | $15 | $15 | |
| | Pipe insulation, clamps, paste, UV tape | — | — | $15 | |
| | **M3 subtotal** | | | **≈ $130–525** + tech visit | |

**Grand total (parts):** M1 + M6 + M2 + M5 + M4 ≈ **$520–550** without refrigerant; with M3 (deferred)
≈ **$650–1075**. Add $120 for the Pro EM-50 or relay Option B if you choose them.

---

## 11. Open questions and assumptions (updated 2026-09-28)

**Answered (folded in above):**
- **Dampers:** Honeywell normally-open / power-close (spring-open), wired NO + COM (an earlier photo read as NC was wrong).
- **PoE:** a 24-port PoE switch sits in the network corner directly below the attic; both nodes stay PoE (WiFi considered and rejected).
- **Location:** the air handler is in the attic.
- **Condensate switch:** one exists.
- **Outdoor power and network:** there's a receptacle at the condenser and a short Cat6/PoE path.
- **Shelly 3EM:** it's a gen1 3EM with phase C unused.
- **Tech visit:** none planned, so M3 is deferred.

**Still open, Ryan can check:**
1. ~~Damper type~~ **Answered:** normally-open / power-close, on NO + COM (see above).
2. **Blower tap map** (photo of the door diagram pending): which motor pin (P49 1–5) do red (FAN), blue
   (COOL) and brown (HEAT) land on, and what speed does each pin correspond to? This sets the three
   `input_select.hvac_*_tap_speed` helpers.
3. **Condensate switch location and circuit:** in Y or R, at which point (6203 → furnace, or furnace →
   condenser feed), and is it on the primary aux port, a secondary pan, or inline? Is there a secondary
   pan?
4. **Multimeter measurements** (no tech needed; AC volts):
   - With no call: 6203 Y → furnace C, furnace Y → C, and each damper NO → COM. Above about 3 VAC means
     a triac is leaking; add a bleeder.
   - With the tap live: COOL/HEAT/FAN → 24 COM. Below about 18 VAC, use 1.8 kΩ on those channels.
   - Ohmmeter, power off: is the 6203 damper COM the same point as its POWER C? Is 24 COM the same point
     as strip C?
5. ~~PoE source~~ **Answered:** 24-port PoE switch directly below the attic.
6. **Shelly 3EM gen1 phase-C clamp:** which part number is correct for the gen1 3EM? I couldn't confirm
   that Shelly's 50 A clamp works on the gen1, or that gen1 firmware allows a different CT type on one
   channel. Default to the same 120 A type as channels A/B. It's optional in any case (coarse).
7. **Compressor common lead:** identify it on the condenser's wiring diagram before clamping.
8. **Olimex ESP32-POE-ISO-IND:** confirm availability and the rated temperature range. If it isn't
   available, the standard board in a return-side mounted box is a calculated risk in a 150 °F attic.

**Deferred to the tech (M3, whenever a visit happens):**
- TXV confirmation.
- Charge baseline and the unit's own charging targets.
- 14ACXS vs 14ACX, S173 present, any low-pressure switch.
- The approved airflow target and correct cooling tap.
- Acceptance of permanent tees + transducers, plus the transducer model and connection/core arrangement
  (060G6810 female-with-depressor per the review; to verify).

**Assumed:**
- Both boxes can be reached with Cat6.
- The indoor box can sit within about 1 m of the return plenum.
- The 6203 is within a few feet of the furnace strip.

## 12. Sources

* Aprilaire 6203/6202 installation manual (terminals, NC/NO damper definitions, sequence of operation, DAT).
* Lennox EL180UHE engineering handbook (specs, blower table) and service literature 1302F (control
  terminals, transformer/breaker, taps 12–33 VAC, fan delays).
* [Lennox 14ACX installation instructions 506645-01](https://www.lennox.com/dA/8b22f61eb8/Lennox_14ACX_IOM.pdf)
  (S4, S173 "some units", charging tables, target-ΔT chart).
* [LennoxPros CHX35-30B-6F listing (TXV)](https://m.lennoxpros.com/chx35-30b-6f-coil2-5tcased-r410a/p/29A39).
* [ESPHome sdp3x](https://esphome.io/components/sensor/sdp3x/), [esphome/issues#5223 (SDP810 address)](https://github.com/esphome/issues/issues/5223),
  [Digi-Key SDP810-500PA](https://www.digikey.com/en/products/detail/sensirion-ag/SDP810-500PA/6605489).
* [Danfoss AKS 32R 060G6810](https://designcenter.danfoss.com/products/sensing-solutions/pressure-transmitters-and-accessories/wholesaler/pressure-transmitters/aks-32r---aks-2050/p/060G6810),
  [060G0090](https://store.danfoss.com/us/en_US/Climate-Solutions-for-cooling/Sensors-and-transmitters/Pressure-transmitters/Pressure-transmitter%2C-AKS-32R%2C-1-00-bar---34-00-bar%2C-14-50-psi---493-00-psi/p/060G0090).
* [JB A31851 tee (SupplyHouse)](https://www.supplyhouse.com/Carrier-A31851-1-4-FE-SAE-Swivel-Tee-Access-Valve-w-Depressor-Nut-on-Run-A31851-Pack-of-3).
* [Shelly Pro EM-50 (ameriDroid)](https://ameridroid.com/products/shelly-pro-em-50), [Olimex ESP32-POE-ISO (Digi-Key)](https://www.digikey.com/en/products/detail/olimex-ltd/ESP32-POE-ISO/10258716).
* [Magnelab SCT-0400-005](https://www.amazon.com/Magnelab-SCT-0400-005-Current-Transformer-Secondary/dp/B009NU9YQO), [Rectorseal SS2](https://rectorseal.com/safe-t-switch-ss2-new/),
  [HA community: AC input on an optocoupler](https://community.home-assistant.io/t/ac-input-on-optocoupler-how-to-detect-smooth-out-the-input/556174).
* R-410A saturation: CoolProp; fits checked to ±0.07 °F within their stated bands.
