#!/usr/bin/env python3
"""
Rename Home Assistant automations for consistency
Pattern: [Category]: [Area] - [Action/Description]
"""

import yaml
import sys
from pathlib import Path

# Mapping of old names to new names
RENAMES = {
    # Doors
    "Stair closet door activates light": "Door: Stair Closet - Auto Light",
    "Workshop door light": "Door: Workshop - Auto Light",
    "Carport door open trigger": "Door: Carport - Motion Light",

    # Motion - Lighting
    "Living room idle motion off": "Motion: Living Room - Auto Off",
    "Kitchen idle motion off": "Motion: Kitchen - Auto Off (15min)",
    "Gym motion detected": "Motion: Gym - Light On",
    "Gym motion clear": "Motion: Gym - Auto Off",
    "Downstairs bathroom motion light": "Motion: Downstairs Bath - Light On",
    "Downstairs bathroom clear light": "Motion: Downstairs Bath - Auto Off",
    "Bedroom motion nightlight": "Motion: Bedroom - Nightlight On",
    "Bedroom motion nightlight off": "Motion: Bedroom - Nightlight Off",
    "Front porch motion detected": "Motion: Front Porch - Door Trigger",
    "Front porch motion clear": "Motion: Front Porch - Auto Off",
    "Front portion motion detected": "Motion: Front Porch - Sensor Trigger",
    "Carport motion detected": "Motion: Carport - Light On",
    "Carport motion clear": "Motion: Carport - Auto Off",
    "Back porch motion clear": "Motion: Back Porch - Auto Off",
    "Kitchen nightlight motion detected": "Motion: Kitchen - Nightlight On",
    "Kitchen motion clear": "Motion: Kitchen - Auto Off",
    "Carport motion lights": "Motion: Carport - Brightness Control",
    "Driveway motion sensor (temporary)": "Motion: Driveway - Brightness Control (Temp)",
    "Front driveway (temporary)": "Motion: Front Driveway - Brightness Control (Temp)",

    # Remotes - Ryan Bedroom (Aeon Labs)
    "Ryan bedroom remote button 1": "Remote: Ryan Bedroom - Button 1 Toggle",
    "Ryan button remote button 2 (long-press)": "Remote: Ryan Bedroom - Button 2 Hold (Sleep)",
    "Ryan bedroom remote button 2": "Remote: Ryan Bedroom - Button 2 Press (Wake)",
    "Ryan bedroom remote button 3 (long-press)": "Remote: Ryan Bedroom - Button 3 Hold (Time-of-Day)",
    "Ryan bedroom remote button 3": "Remote: Ryan Bedroom - Button 3 Press (Lights Off)",
    "Ryan bedroom button 4": "Remote: Ryan Bedroom - Button 4 (All Lights On)",

    # Remotes - Hall (ZEN37)
    "Hall remote button 1": "Remote: Hall - Button 1 Toggle",
    "Hall remote button 1 (2x)": "Remote: Hall - Button 1 Double (Full Bright)",
    "Hall remote button 2 (2x)": "Remote: Hall - Button 2 Double (Lights Off)",
    "Hall remote button 4": "Remote: Hall - Button 4 Double (Wheels Climate)",
    "Hall remote button 1 (held)": "Remote: Hall - Button 1 Hold (Scene)",
    "Hall remote button 1 (Christmas)": "[SEASONAL] Remote: Hall - Button 1 (Xmas Lights)",

    # Remotes - Kitchen (ZEN37)
    "Kitchen remote controls": "Remote: Kitchen - All Buttons",

    # Remotes - Upstairs (ZEN37)
    "Upstairs remote 4 - outdoor on": "Remote: Upstairs - Button 4 (Outdoor On) [DUPLICATE]",
    "Upstairs remote": "Remote: Upstairs - Button 4 (Outdoor Control)",

    # Remotes - Gym
    "Gym remote button 1": "Remote: Gym - Button 1 Toggle",

    # Remotes - Switches
    "Ryan bedroom switch button 1": "Switch: Ryan Bedroom - Button 1 (Light Off)",
    "Ryan bedroom switch button 2": "Switch: Ryan Bedroom - Button 2 (Bright Lights)",

    # Climate - Fans
    "Ryan bedroom fan speed by temperature": "Climate: Ryan Bedroom - Fan Temperature Control",
    "Ryan bedroom fan motion clear": "Climate: Ryan Bedroom - Fan Off (No Motion)",
    "Ryan bedroom fan override disabled": "Climate: Ryan Bedroom - Fan Override Off",
    "Ryan bedroom fan override enabled": "Climate: Ryan Bedroom - Fan Override On",
    "Ryan bedroom fan enable override": "Climate: Ryan Bedroom - Fan Override Enable (Button)",
    "Ryan bedroom fan disable override": "Climate: Ryan Bedroom - Fan Override Disable (Button)",
    "Ryan bedroom fan temperature change": "Climate: Ryan Bedroom - Fan Temp Adjust",

    # Climate - Bathroom Fans
    "Hall bathroom high humidity": "Climate: Hall Bath - Fan On (High Humidity)",
    "Hall bathroom low humidity": "Climate: Hall Bath - Fan Off (Low Humidity)",
    "Downstairs bathroom fan timer": "Climate: Downstairs Bath - Fan Timer",
    "Downstairs bathroom high humidity": "Climate: Downstairs Bath - Fan On (High Humidity)",

    # Lighting - Outdoor
    "Outdoor all off": "Lighting: Outdoor - All Off (Multi-Trigger)",
    "Outdoor all on": "Lighting: Outdoor - All On (Multi-Trigger)",

    # Lighting - Kitchen
    "Kitchen lights button activated": "Lighting: Kitchen - Motion Deactivate (Button Press)",

    # Seasonal
    "Christmas lights on at sunset": "[SEASONAL] Christmas - Lights On (Sunset)",
    "Christmas lights off at sunrise": "[SEASONAL] Christmas - Lights Off (Sunrise)",

    # System
    "Automatic backups": "System: Backup - Daily 3AM",
    "Reset auto off events counter at midnight": "System: Counter - Reset Auto-Off (Midnight)",

    # Security
    "Trigger alarm on door open while armed away": "Security: Alarm - Trigger (Door + Armed Away)",
    "Send notification when alarm triggered": "Security: Alarm - Notify (Triggered)",

    # Modes
    "Home away (return)": "Mode: Home - Return (Lights + Normal Mode)",
    "Home away (away)": "Mode: Home - Away (Lights Off + Away Mode)",

    # Low Battery
    "Low battery level detection & notification for all battery sensors": "System: Battery - Low Level Notifications",
}

def rename_automations(file_path):
    """Rename automations in the YAML file"""

    # Load YAML
    with open(file_path, 'r') as f:
        automations = yaml.safe_load(f)

    if not automations:
        print("No automations found")
        return

    # Track changes
    renamed_count = 0
    not_found = []

    # Rename automations
    for automation in automations:
        old_alias = automation.get('alias', '')
        if old_alias in RENAMES:
            automation['alias'] = RENAMES[old_alias]
            print(f"✓ Renamed: {old_alias[:50]:<50} → {RENAMES[old_alias]}")
            renamed_count += 1

    # Find automations not in rename map
    for automation in automations:
        alias = automation.get('alias', '')
        if alias and alias not in RENAMES.values() and alias not in RENAMES:
            not_found.append(alias)

    # Write back
    with open(file_path, 'w') as f:
        yaml.dump(automations, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✅ Renamed {renamed_count} automations")

    if not_found:
        print(f"\n⚠️  {len(not_found)} automations not in rename map:")
        for alias in not_found:
            print(f"   - {alias}")

if __name__ == "__main__":
    automations_file = "/Volumes/config/automations.yaml"

    print("Home Assistant Automation Renamer")
    print("=" * 70)
    print(f"File: {automations_file}\n")

    # Create backup
    import shutil
    backup_file = str(Path(automations_file).with_suffix('.yaml.backup'))
    shutil.copy2(automations_file, backup_file)
    print(f"✓ Backup created: {backup_file}\n")

    # Rename
    rename_automations(automations_file)

    print("\n" + "=" * 70)
    print("Done! Reload automations in Home Assistant to see changes.")
    print(f"If anything goes wrong, restore from: {backup_file}")
