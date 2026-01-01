# Home Assistant Blueprints

Automated Home Assistant blueprints with integrated development workflow.

## Quick Start

```bash
# 1. Install dependencies
./install-deps.sh

# 2. Configure your environment
cp .env.example .env
nano .env  # Add your HA path, URL, and token

# 3. Mount your HA SMB share
# macOS: Finder → Go → Connect to Server → smb://homeassistant.local

# 4. Start auto-sync mode
./watch.sh

# Now edit any .yml file and it auto-syncs to HA!
```

## Blueprints

- `air-quality-fan.yml` - Control fans based on CO2, PM2.5, and TVOC sensors
- `bathroom-fan-with-humidity.yml` - Humidity-based bathroom fan control
- `motion-auto-off-lights-with-override.yml` - Motion-activated lights with manual override
- `motion-and-door-light-control.yaml` - Advanced motion and door sensor light control

## Development Workflow

### Auto-Sync Mode (Recommended)

```bash
./watch.sh
```

- Watches for file changes
- Validates YAML automatically
- Syncs to Home Assistant
- Reloads automations
- Shows errors immediately

### Manual Sync

```bash
./sync.sh
```

Validates and syncs on demand.

## Features

✅ **YAML validation** before sync prevents broken blueprints
✅ **Automatic sync** to Home Assistant on file save
✅ **API-based reload** - no HA restarts needed
✅ **Instant error feedback** in your terminal
✅ **Version control** with git
✅ **Fast iteration** - seconds from edit to test

## How It Works

1. Edit blueprint files locally with your favorite editor
2. File watcher detects changes
3. YAML validation runs automatically
4. Files sync to HA via SMB mount
5. Automations reload via HA API
6. Errors appear immediately in terminal

No more:
- ❌ Manual file uploads
- ❌ HA restarts
- ❌ Debugging syntax errors in HA UI
- ❌ Slow iteration cycles

## Documentation

See [SETUP.md](SETUP.md) for detailed setup instructions and troubleshooting.

## Requirements

- Home Assistant OS with SMB share enabled
- Python 3 with pip
- macOS with Homebrew (for fswatch)
- Network access to Home Assistant
