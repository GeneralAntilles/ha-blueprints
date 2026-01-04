# Home Assistant Blueprints

Custom blueprints with automatic sync workflow for rapid development.

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
- **motion-light-simple.yaml** - Simple motion-activated lights with scenes, overrides, and manual control cancellation
- **motion-and-door-light-control.yaml** - Advanced motion + door sensors with late-night modes
- **motion-auto-off-lights-with-override.yaml** - Basic motion with manual override

### Climate Control
- **temperature-fan-control.yaml** - Temperature-based fan control with multiple speed levels
- **air-quality-fan.yaml** - Air quality fans (CO2, PM2.5, TVOC sensors)
- **bathroom-fan-with-humidity.yaml** - Humidity-based bathroom fan with timer

### Remotes & Controls
- **zooz-zen37-remote-control.yaml** - Zooz ZEN37 800LR 4-button remote (all press types)

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
