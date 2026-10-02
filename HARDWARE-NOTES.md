# Hardware Notes

Device-specific quirks and their fixes, not obvious from the HA UI. One entry per device/switch type. Add to this as new quirks turn up — keep entries short.

## Inovelli VZM35-SN (fan switch, ZHA)

- **Duplicate light entity.** Firmware shares the VZM31-SN dimmer's clusters, so each switch exposes both `fan.<name>_fan` (real control, Fan Control cluster) and `light.<name>_light` (same load via On/Off + Level Control, kept for ecosystems/bindings that don't speak Fan Control). `light.turn_on` on it spins the fan.
  - **Fix:** disable the `light.<name>_light` entity (Settings → Devices → device → entity → disable, or entity registry `disabled_by: user`). Use `fan.<name>_fan` everywhere. Done for: Living Room, Guest Bedroom, Master, Office (as of 2026-09).
- **HomeKit shows 4 tiles per fan.** ZHA publishes generic presets `on/auto/smart` without the PRESET_MODE feature flag, and HomeKit's Fan accessory builds a Switch service per preset with no feature check — 1 fan + 3 preset switches in the Home app.
  - **Fix:** `homeassistant: customize: <fan_entity>: preset_modes: []` in `configuration.yaml`, then restart (or `reload_core_config` + `homeassistant.update_entity` on the fan to pick it up without a restart, then reload the HomeKit bridge entry). Only masks the attribute — `fan.set_preset_mode` still works if breeze mode is ever wanted.
  - Needed again for every new VZM35-SN added to the bridge.

## Zooz ZEN76 (in-wall fan/switch, Z-Wave)

- A dead-looking node (statistics show `commands_rx` climbing — the controller hears its reports — while `commands_tx` stays frozen, every send timing out; it flaps alive-on-own-report → dead-on-first-command) **looks like a defective unit but usually isn't.**
- Confirmed 2026-08-31 with two units from the same batch plus a controller swap: the real cause was a 500-series (Gen5) stick unable to reach that room. An 800-series controller (ZWA-2) plus an air-gap power cycle brought the same node fully alive in ~30s.
- Don't condemn the switch from statistics alone — try a controller/radio change or an air-gap power cycle first.

## Zooz ZEN30 / ZEN77 in-wall dimmers (Z-Wave)

- Gamma Factor and single-tap prestage params are at **different numbers per model** — ZEN30: p38 (gamma), p23 (prestage level); ZEN77: p36 (gamma), p18 (prestage level). Set both devices' gamma to the same value (22 = gamma 2.2, vs. the linear default of 10) so identical brightness commands look identical across rooms.
- ZEN30 only: decoupling the relay (p20 = 0, meant to stop it switching an empty circuit when nothing's wired to it) caused paired lights on the same button press to flicker back on ~5s later. Mechanism unconfirmed (suspected Basic Set to the button's association group). **Leave p20 = 1** even with nothing wired to the relay.

## GE / Jasco dimmers & switches (Z-Wave)

- **Parameter 3 meaning is not consistent across the line** — don't hardcode it. It's "Operation Mode" (on-when-off vs. off) on 14294/ZW3005, 14280/ZW3107, 12719/ZW4101; inverted on the 14287 fan control; a different function on Jasco motion switches (24770/26932); and absent entirely on 55 of 141 catalogued models.
- Look up the exact model in the zwave-js device database before writing this parameter.

## HomeSeer HS-FC200+ / WD200+ / WS200+ (Z-Wave)

- Status-mode LED behavior is **param 13** (0 = normal, 1 = status) on all three models.
- **Param 5 on the FC200+ is Fan Type, not status mode** — a prior recipe got this wrong; verify against the zwave-js device database, not by analogy to the other two models.

## Aeotec ZSE40 (4-in-1 motion/humidity/lux sensor, Z-Wave)

- Wake it with the **paperclip pinhole** (not the tamper switch) before doing anything that needs it awake, like "Rebuild routes" — it sleeps on a 12h interval by default and will silently miss the request otherwise. 1 press = wake (LED flash), 2 presses = include/exclude, 10 presses = factory reset.

## Ecobee thermostats (ECB601 Premium / ECB501)

- HomeKit Controller (local, push) should stay the primary integration, but it exposes **no air-quality service at all**. The cloud `ecobee` integration (username/password, no dev API key needed since HA 2026.3) is the only route to the Premium's CO2/VOC/AQI sensors, presets, and equipment state — run both side by side rather than picking one.
- Disable the cloud integration's duplicate temp/humidity/occupancy/weather entities instead of migrating automations off HomeKit.
- Ecobee's "CO2" is eCO2 estimated from a VOC sensor with a 4-day self-calibration window — good for trends, not comparable to an NDIR sensor (e.g. AirGradient).

## Aqara U200 smart lock (Matter)

- Bonds to Apple Home / Home Key natively; it reaches HA via **Matter multi-admin sharing** from the Home app ("Turn On Pairing Mode"), not a direct HA pairing.
- `changed_by` reports the *credential type*, not the person: PIN, fingerprint, inside thumb-turn, and the keypad lock button all report **Keypad**; Home Key (phone/watch) reports **RFID**; the Apple Home app or HA reports **Remote**. No per-user identity is exposed.
- For physical operations the attribute lands 0.2–0.45s *after* the state change — give an automation a short delay before reading it.

## Aqara Cube T1 Pro ("Dice Remote", ZHA)

- Has two hardware modes; only **Action mode** sends tap/slide/flip/rotate through HA's ZHA quirk (Scene mode only sends shake + rotate). Switch modes by opening the lid and clicking LINK 5×.
- If gestures "don't show up" in HA, check the mode before suspecting the integration.
