# Home Assistant Blueprints

Custom blueprints with automatic sync workflow for rapid development.

Device-specific quirks (weird entities, HomeKit fixes, etc.) are tracked in [HARDWARE-NOTES.md](HARDWARE-NOTES.md).

## Quick Start

```bash
# 1. Install dependencies
./install-deps.sh

# 2. Configure environment
cp .env.example .env
nano .env  # Add HA path, URL, and token

# 3. Mount HA SMB share
# macOS: Finder → Go → Connect to Server → smb://homeassistant.local

# 4. Start auto-sync
./watch.sh
```

## Blueprints

### Motion & Lighting
- **motion-light-controller.yaml** - Motion lights v2: manual respect via tracking helper, time-of-day-sensor timeouts (day/night off-delays), optional scene turn-on, reconcile watchdog. Requires HA 2024.10+ and a per-room input_boolean
- **motion-light-simple.yaml** - Simple motion-activated lights with scenes, overrides, and manual control cancellation
- **motion-and-door-light-control.yaml** - Advanced motion + door sensors with late-night modes
- **motion-auto-off-lights-with-override.yaml** - Basic motion with manual override

### Climate Control
- **bathroom-controller.yaml** - Combined bathroom automation: humidity fan (threshold/reference/derivative modes, purge, min/max runtimes), motion lights with shower hold (optional scene turn-on, day/night off-delays from a time-of-day sensor or a clock window), optional shower start/cancel button events (e.g. fan-paddle double-taps), optional heater with restart-surviving safety cutoff. Requires HA 2024.10+ and per-bathroom tracking helpers (see the blueprint description)
- **steamer-controller.yaml** - Garment steamer (or any heating appliance) on a metered smart plug, the appliance's own switch stays the control: exhaust fan on when it draws power (off after a humidity settle - absolute threshold and/or offset from a reference sensor, like bathroom-controller - or a fixed purge, min/max runtimes, manual respect), plug cut after N minutes without motion or past a max runtime, per-event announcements (persistent, mobile notify, TTS), and automatic re-enable - on the next room entry the plug is probed back on; if the appliance still draws power (switch left on) it is cut again and you are told, otherwise it stays on. Manual plug-on / the plug's own button also re-enables. Requires HA 2025.4+ and three input_booleans (running, plug-cut, fan tracking)
- **temperature-fan-control.yaml** - Temperature-based fan control with multiple speed levels
- **air-quality-fan.yaml** - Air quality fans (CO2, PM2.5, TVOC sensors)

### Remotes & Controls
- **zooz-zen37-remote-control.yaml** - Zooz ZEN37 800LR 4-button remote (all press types)
- **aeotec-minimote-controller.yaml** - Aeotec / AEON Labs Minimote (DSA03XXX-ZW, white or black) on Z-Wave JS: Press + Hold per button (Release too on Central Scene firmware), decodes both the Scene Activation (sceneId 1-8) and Central Scene formats, parallel mode. One instance per remote; give twins (e.g. a pair of bedside remotes) identical actions. Works as a media remote too (e.g. Hue Sync toggle/mode, media lighting scenes)
- **aqara-cube-controller.yaml** - Aqara Cube (T1 Pro / older cube on ZHA): one action list per gesture (shake, tap, slide, flip 90/180, rotate left/right, throw) plus "faces as modes": collapsed per-face sections (tap/slide/rotate/flip per face) with an optional Input Number face helper so rotate knows the face, and built-in rotate-to-dim / rotate-to-cycle-scenes that can be limited to one face. Cube must be in Action mode. Requires HA 2024.10+
- **wall-dimmer-natural-light-controller.yaml** - In-wall Z-Wave dimmer as a room controller: paddle drives its own load (recessed cans) at a time-of-day brightness while the room's Hue Natural Light scene handles the smart bulbs. Up 2x = Full Bright, Down 2x = Lamps Only. Optional single-tap prestage (writes the band level into the switch so it turns on at the right level itself), an optional relay/third-button section for switches like the ZEN30, and optional zone-scene sync so the cans join a house-wide Natural Light recall. Requires HA 2026.1+ (for the `scene.activated` trigger) and Scene Control enabled on the switch. Optional GE / Jasco paddle mode for dimmers without Central Scene (14294 / ZW3005): double taps come from the Scene Activation event, single taps from a hand-made load change (no user/parent context), with a settle delay so a double tap's own load report is not mistaken for a single tap. Optional Linked Overheads: other loads that follow every gesture so two dimmers in one room act as one circuit (each instance lists the other's load; zone sync stays per-load)

## Controller Guide

`controller-guide/` builds a "what does this button do?" website and
printable sheets for every remote and switch, straight from the live
blueprint instances. See [controller-guide/README.md](controller-guide/README.md).

## Development Workflow

**Auto-sync mode (recommended):**
```bash
./watch.sh
```
Watches files → Validates YAML → Syncs to HA → Reloads automations

**Manual sync:**
```bash
./sync.sh
```

## Features

- ✅ YAML validation before sync
- ✅ Auto-sync on save
- ✅ API-based reload (no HA restarts)
- ✅ Instant error feedback
- ✅ Git version control
- ✅ Fast iteration (seconds from edit to test)

## Automation Organization

All automations use consistent naming: `[Category]: [Area] - [Action]`

**Categories:**
- `Motion:` - Motion-activated lighting
- `Remote:` - Button/remote controls
- `Climate:` - Fans, temperature, humidity
- `Door:` - Door-activated lights
- `Lighting:` - Manual lighting controls
- `System:` - Backups, counters, notifications
- `Security:` - Alarms, sensors
- `Mode:` - Home/away modes

## Useful Scripts

- **house_mode_toggle** - Toggle party/normal mode with voice announcement
- **outdoor_all_on/off** - Control all outdoor lights
- **christmas_lights_on/off** - Seasonal lighting

## Requirements

- Home Assistant with SMB share enabled
- Python 3 + pip
- macOS with Homebrew (for fswatch)
- Network access to HA

See [SETUP.md](SETUP.md) for detailed instructions.
