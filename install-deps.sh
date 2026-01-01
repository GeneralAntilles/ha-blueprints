#!/bin/bash

echo "📦 Installing dependencies for HA blueprint development..."

# Check if pip3 is available
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 not found. Please install Python 3 first:"
    echo "   brew install python3"
    exit 1
fi

# Install yamllint
echo "Installing yamllint..."
pip3 install yamllint

# Check if fswatch is available (for macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! command -v fswatch &> /dev/null; then
        echo "Installing fswatch..."
        if command -v brew &> /dev/null; then
            brew install fswatch
        else
            echo "⚠️  Homebrew not found. Install fswatch manually or install Homebrew first."
        fi
    fi
fi

echo "✅ Dependencies installed!"
echo ""
echo "Next steps:"
echo "1. Copy .env.example to .env:  cp .env.example .env"
echo "2. Edit .env with your settings: nano .env"
echo "3. Run: ./watch.sh"
