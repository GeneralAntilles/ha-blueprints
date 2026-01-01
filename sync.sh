#!/bin/bash
set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "Error: .env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "🔍 Validating YAML files..."

# Validate all YAML files (must use .yaml extension for HA)
VALIDATION_FAILED=0
shopt -s nullglob
for file in *.yaml; do
    echo "  Checking $file..."
    if ! yamllint "$file"; then
        echo -e "${RED}✗ Validation failed for $file${NC}"
        VALIDATION_FAILED=1
    else
        echo -e "${GREEN}✓ $file is valid${NC}"
    fi
done
shopt -u nullglob

if [ $VALIDATION_FAILED -eq 1 ]; then
    echo -e "${RED}❌ Validation failed. Fix errors before syncing.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ All files validated successfully${NC}"

# Check if HA config path is mounted
if [ ! -d "$HA_CONFIG_PATH" ]; then
    echo -e "${RED}Error: HA config path not found: $HA_CONFIG_PATH${NC}"
    echo "Make sure your Home Assistant SMB share is mounted."
    exit 1
fi

# Create blueprints directory if it doesn't exist
BLUEPRINT_DIR="$HA_CONFIG_PATH/blueprints/automation"
mkdir -p "$BLUEPRINT_DIR"

# Sync blueprint files
echo "📁 Syncing blueprints to Home Assistant..."
shopt -s nullglob
for file in *.yaml; do
    cp "$file" "$BLUEPRINT_DIR/"
    echo -e "${GREEN}✓ Synced $file${NC}"
done
shopt -u nullglob

# Reload blueprints via API
echo "🔄 Reloading Home Assistant blueprints..."
RESPONSE=$(curl -s -X POST \
    -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" \
    "$HA_URL/api/services/homeassistant/reload_config_entry" \
    -d '{"entry_id": "blueprints"}' 2>/dev/null)

# Also reload automations
echo "🔄 Reloading automations..."
RESPONSE=$(curl -s -X POST \
    -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" \
    "$HA_URL/api/services/automation/reload")

if echo "$RESPONSE" | grep -q "error"; then
    echo -e "${YELLOW}⚠️  API reload returned an error (might be normal)${NC}"
else
    echo -e "${GREEN}✓ Reloaded successfully${NC}"
fi

echo -e "${GREEN}🎉 Sync complete!${NC}"
