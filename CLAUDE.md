# Claude Code Work Log

## 2026-01-07: AirGradient Open Air (PCB V4.2) ESPHome Setup

### Task
Configure AirGradient Open Air (PCB V4.2 - ESP8266 D1 Mini) with ESPHome for Home Assistant integration.

### Device Specifications
- **PCB Version**: V4.2 (older, pre-ESP32 upgrade)
- **Chip**: ESP8266 D1 Mini
- **Firmware Limitation**: Max 3.0.8 (official AirGradient firmware)
- **Sensors**:
  - 1x PMS5003 (particulate matter)
  - 1x SHT3x (temperature & humidity)
  - 1x SGP41 (VOC & NOx)

### Configuration Created
- **File**: `/Volumes/config/esphome/airgradient-open-air.yaml`
- **Based on**: MallocArray's airgradient_esphome project
- **Adapted for**: ESP8266 D1 Mini with specific sensor configuration

### Pin Mapping (D1 Mini)
- **I2C**: SDA=GPIO4 (D2), SCL=GPIO5 (D1) - for SHT & SGP41
- **UART**: RX=GPIO13 (D7), TX=GPIO15 (D8) - for PMS5003
- **Watchdog**: GPIO16 (D0)
- **Status LED**: GPIO2 (D4)

### Setup Steps

**1. Update Secrets**
Edit `/Volumes/config/esphome/secrets.yaml` and set:
- `airgradient_api_key` - Generate in ESPHome during first compile
- `airgradient_ota_password` - Set a password for OTA updates
- `airgradient_ap_password` - Set a password for fallback AP

**2. Compile & Flash**
```bash
# From ESPHome dashboard or CLI
esphome compile airgradient-open-air.yaml
esphome upload airgradient-open-air.yaml
```

Or use ESPHome Dashboard:
1. Open ESPHome in Home Assistant
2. Click "Install" on "airgradient-outdoor"
3. First flash MUST be via USB ("Plug into this computer")
4. Future updates can be done wirelessly (OTA)

**3. First Flash (USB)**
- Connect D1 Mini via USB
- May need to hold FLASH/BOOT button during connection
- ESPHome will detect the serial port
- Flash will take 3-5 minutes for ESP8266

**4. Post-Flash**
- Device will connect to WiFi
- Auto-discover in Home Assistant (Settings → Integrations)
- All sensors will appear as entities

### Troubleshooting
- **Won't flash?** Hold FLASH button on D1 Mini while plugging in USB
- **Sensors not working?** Check I2C scan in logs (should see 0x44 for SHT, 0x59 for SGP41)
- **PMS sensor offline?** Verify UART pins and baud rate (9600)
- **SHT sensor type wrong?** Adjust platform (sht3xd, sht4x, etc.) based on actual sensor

### Resources
- [MallocArray's AirGradient ESPHome](https://github.com/MallocArray/airgradient_esphome)
- [AirGradient Forum Discussion](https://forum.airgradient.com/t/malloc-array-airgradient-esp-home-repository/1398)

---

## 2026-01-07: ESP32-S3 Bluetooth Proxy Setup

### Task
Configure ESP32-S3 board as a Bluetooth Proxy for Home Assistant.

### Configuration
- **File**: `/Volumes/config/esphome/bluetooth-repeater.yaml`
- **Board**: ESP32-S3-DevKitC-1
- **Framework**: ESP-IDF (required for ESP32-S3)
- **Components Added**:
  - `esp32_ble_tracker` - Scans for Bluetooth devices
  - `bluetooth_proxy` - Proxies Bluetooth to Home Assistant

### How to Flash

**Option 1: ESPHome Dashboard (Easiest)**
1. Open ESPHome in Home Assistant (Settings → Add-ons → ESPHome)
2. Click on "bluetooth-repeater"
3. Click "Install" → "Plug into this computer"
4. Connect ESP32-S3 via USB
5. Select the serial port and click "Install"

**Option 2: ESPHome CLI**
```bash
# From /Volumes/config/esphome/
esphome run bluetooth-repeater.yaml
```

**Option 3: Web Flasher (First time only)**
1. Go to https://web.esphome.io
2. Connect ESP32-S3 via USB
3. Click "Install" and select the compiled firmware
4. After first flash, you can do OTA updates from ESPHome dashboard

### After Flashing
1. Device will connect to WiFi ("Home" network)
2. Should auto-discover in Home Assistant
3. Go to Settings → Devices & Services → ESPHome
4. Click "Configure" on the discovered device
5. Done! Bluetooth devices near the proxy will now be accessible

### Troubleshooting
- **Not showing up?** Check the ESPHome logs for connection issues
- **Won't flash?** Try holding BOOT button while connecting USB
- **WiFi issues?** Device will create fallback AP "Bluetooth-Repeater" (password: set in the device YAML, not committed)

---

## 2026-01-07: SSL Certificate Setup & Ecowitt Fix

### Issue
Ecowitt weather station webhooks stopped working after enabling SSL.

### Root Cause
- Ecowitt stations only support HTTP webhooks (no HTTPS support)
- When SSL is enabled on Home Assistant, it switches to HTTPS-only
- Ecowitt station cannot connect → no weather data updates

### Solution Applied
**Disabled SSL in Home Assistant** to restore Ecowitt functionality:
- Commented out `ssl_certificate` and `ssl_key` in configuration.yaml
- Home Assistant now serves HTTP on port 8123
- Ecowitt webhooks working again

### SSL Certificate (Created but Not Active)
- **Location**: `/Volumes/ssl/`
- **Files created**:
  - `privkey.pem` - 4096-bit RSA private key
  - `fullchain.pem` - Self-signed certificate (365 days validity)
- **Algorithm**: RSA 4096-bit
- **Validity**: 365 days
- **Subject**: CN=homeassistant.local

### Future: NGINX Reverse Proxy Solution
If you need HTTPS for browser access while keeping HTTP webhooks working:

**Install NGINX Home Assistant Add-on:**
1. Settings → Add-ons → Add-on Store → NGINX Home Proxy Manager
2. Configure NGINX to:
   - Listen on HTTPS (port 443) with SSL certificates
   - Forward to Home Assistant HTTP (port 8123) internally
3. Ecowitt webhooks go to HTTP (homeassistant.local:8123)
4. Browser access goes to HTTPS (homeassistant.local:443)

**Benefits:**
- HTTPS for browsers (required for microphone, clipboard, etc.)
- HTTP still available for IoT devices/webhooks
- SSL handled by NGINX, HA stays simple

### Current State
- SSL: **Disabled** (certificates exist but not configured)
- Access: HTTP only at `http://homeassistant.local:8123`
- Ecowitt: **Working** via HTTP webhooks

---

## 2026-01-06: Battery Warning Automation

### Issue
Low battery warning automation is spammy and needs improvement.

### Current Setup
- **Location**: `/Volumes/config/automations.yaml:851`
- **Blueprint**: `sbyx/low-battery-level-detection-notification-for-all-battery-sensors.yaml`
- **Current behavior**: Runs daily at 10:00 AM, creates one persistent notification listing ALL low batteries

### Why It's Spammy
1. One giant notification with all low batteries listed
2. Repeats daily until fixed (no throttling)
3. Persistent notifications clutter UI
4. No priority levels or grouping
5. No way to snooze specific batteries
6. Doesn't exclude charging devices

### Solution Created
Created `battery-warning.yaml` with improvements:
- **Priority levels**: Critical (<10%), Warning (<20%)
- **Smart filtering**: Excludes charging devices
- **Better formatting**: Grouped by priority, sorted by level
- **Persistent notifications**: Simple, built-in notification system
- **Configurable thresholds**: Customize levels per your needs
- **Cleaner messages**: Clear action items vs just dumping a list
- **Conditional notifications**: Only notifies when batteries are actually low

### Configuration
- Uses `notify.persistent_notification` (appears in HA UI)
- Critical: 🔴 Immediate attention needed
- Warning: 🟡 Should be replaced soon
- Default check time: 9:00 AM daily
- Default thresholds: Critical <10%, Warning <20%

### Next Steps
1. Copy `battery-warning.yaml` to `/Volumes/config/blueprints/automation/`
2. Reload automations in Home Assistant
3. Create new automation using the improved blueprint
4. Adjust thresholds if needed
5. Test and verify notifications work
6. Disable old spammy automation at line 851 in automations.yaml
