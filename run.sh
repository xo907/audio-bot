#!/usr/bin/env bash
set -e

# Change to script directory
cd "$(dirname "$0")"

echo "========================================================"
echo "              Discord Audio Bot Launcher"
echo "========================================================"
echo ""

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 could not be found. Please install Python 3.10+."
    exit 1
fi

# 2. Check virtual environment
if [ ! -d ".venv" ]; then
    echo "[*] Creating virtual environment (.venv)..."
    python3 -m venv .venv
fi

# 3. Activate virtual environment
source .venv/bin/activate

# 4. Check .env template
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "[*] Creating .env from .env.example..."
    cp .env.example .env
fi

# 5. Install dependencies
echo "[*] Checking dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 6. Launch bot
echo "[*] Starting Audio Bot..."
echo "========================================================"
python3 main.py
