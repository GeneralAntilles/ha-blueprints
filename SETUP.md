# Home Assistant Blueprint Development Workflow

## One-Time Setup

### 1. Install Dependencies

```bash
# Install Python tools for YAML validation
pip3 install yamllint

# fswatch will be auto-installed when you run watch.sh
# (or install manually: brew install fswatch)
```

### 2. Configure Environment

```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your settings
nano .env
```

**Required settings in `.env`:**

- `HA_CONFIG_PATH`: Path to your mounted SMB share
  - Example: `/Volumes/homeassistant/config` (macOS)
  - Mount your HA share first: Go to Finder → Go → Connect to Server → `smb://homeassistant.local`

- `HA_URL`: Your Home Assistant URL
  - Example: `http://homeassistant.local:8123`

- `HA_TOKEN`: Long-lived access token
  - Create at: Settings → Profile → Long-Lived Access Tokens → Create Token
  - Copy the token to `.env`

### 3. Mount Your Home Assistant Share

**On macOS:**
1. Open Finder
2. Go → Connect to Server (⌘K)
3. Enter: `smb://homeassistant.local`
4. Mount the drive
5. Update `HA_CONFIG_PATH` in `.env` to match the mount point

## Daily Workflow

### Option 1: Auto-Sync Mode (Recommended)

```bash
# Start the file watcher
./watch.sh
```

This will:
- Watch for any changes to `.yaml` or `.yml` files
- Automatically validate YAML syntax
- Sync to Home Assistant
- Reload automations
- Show any errors immediately

**Now just edit your blueprints and save!** Changes sync automatically.

### Option 2: Manual Sync

```bash
# Validate and sync whenever you want
./sync.sh
```

## What Happens During Sync

1. ✅ **Validates** all YAML files with yamllint
2. ✅ **Copies** blueprints to HA's `config/blueprints/automation/` directory
3. ✅ **Reloads** automations via Home Assistant API
4. ✅ **Reports** any errors immediately in your terminal

## Troubleshooting

### "HA config path not found"
- Make sure your SMB share is mounted
- Check that `HA_CONFIG_PATH` in `.env` is correct
- Try: `ls "$HA_CONFIG_PATH"` to verify

### "Failed to reload automations"
- Check that `HA_TOKEN` is valid
- Verify `HA_URL` is accessible: `curl $HA_URL`
- Make sure token has proper permissions

### "Validation failed"
- Fix the YAML errors shown in the output
- Common issues: indentation, invalid syntax
- The sync won't proceed until validation passes

### "Permission denied"
- Run: `chmod +x sync.sh watch.sh`

## Benefits of This Workflow

✅ **No more blind uploads** - Validation catches errors before they reach HA
✅ **Instant feedback** - See errors immediately in your terminal
✅ **Fast iteration** - Save file → auto-sync → test in seconds
✅ **Version control** - All changes tracked in git
✅ **No HA restarts** - Just automation reloads via API

## Using with Claude Code

When developing blueprints with Claude Code:

```bash
# In one terminal, start the watcher
./watch.sh

# In another terminal/window, use Claude Code normally
claude
```

Claude Code will edit the blueprints, and they'll auto-sync to HA when saved!
