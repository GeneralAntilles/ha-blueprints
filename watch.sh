#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}👀 Watching for changes to blueprint files...${NC}"
echo -e "${BLUE}Press Ctrl+C to stop${NC}"
echo ""

# Check if fswatch is installed
if ! command -v fswatch &> /dev/null; then
    echo "Installing fswatch..."
    brew install fswatch
fi

# Watch for changes to .yaml files and trigger sync
fswatch -o -e ".*" -i "\\.yaml$" . | while read change; do
    echo -e "${GREEN}📝 Change detected, syncing...${NC}"
    ./sync.sh
    echo ""
    echo -e "${BLUE}👀 Watching for more changes...${NC}"
done
