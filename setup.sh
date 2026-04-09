#!/bin/bash
set -e

echo "=== Canva to WhatsApp Status Automation - Setup ==="

# Install Python dependencies
echo "[1/3] Installing Python dependencies..."
pip install -r requirements.txt

# Install Playwright browsers (Chromium only)
echo "[2/3] Installing Playwright Chromium browser..."
playwright install chromium
playwright install-deps chromium

# Create .env from example if it doesn't exist
echo "[3/3] Setting up configuration..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env file from .env.example"
    echo "Please edit .env and set your CANVA_URL before running."
else
    echo ".env already exists, skipping."
fi

# Create required directories
mkdir -p downloads
mkdir -p browser_data

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env and set your CANVA_URL"
echo "  2. Run first-time WhatsApp login:  python main.py --setup"
echo "  3. Scan QR code in WhatsApp Web when browser opens"
echo "  4. After login, close browser and run:  python main.py"
