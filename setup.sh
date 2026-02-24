#!/bin/bash
# ============================================
# Aegis - One-Click Setup & Launch (Mac/Linux)
# ============================================

echo ""
echo "========================================"
echo "  Aegis - Multi-Agent Kanban Setup"
echo "========================================"
echo ""

# Check Python
echo "[1/5] Checking for Python..."
if ! command -v python3 &> /dev/null; then
    echo "  ERROR: Python not found!"
    echo "  Please install Python 3.10+ from https://python.org"
    read -p "Press Enter to exit..."
    exit 1
fi
echo "  ✓ Python found: $(python3 --version)"

# Check Node.js (optional)
echo "[2/5] Checking for Node.js..."
if command -v node &> /dev/null; then
    echo "  ✓ Node.js found: $(node --version)"
else
    echo "  - Node.js not found (optional - for advanced features)"
fi

# Create virtual environment
echo "[3/5] Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  ✓ Virtual environment created"
else
    echo "  ✓ Virtual environment already exists"
fi

# Activate and install
echo "[4/5] Installing dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt
if [ $? -ne 0 ]; then
    echo "  ERROR: Failed to install dependencies"
    read -p "Press Enter to exit..."
    exit 1
fi
echo "  ✓ Dependencies installed"

# Create .env if not exists
echo "[5/5] Configuration..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  ✓ Configuration created"
else
    echo "  ✓ Configuration already exists"
fi

echo ""
echo "========================================"
echo "  Setup Complete!"
echo "========================================"
echo ""
echo "Starting Aegis..."
echo ""
echo "The dashboard will open at: http://localhost:8080"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Generate agent templates
echo "Initializing agent templates..."
python3 setup_templates.py
echo "  ✓ Templates generated"
echo ""

# Start the server
python3 main.py
