@echo off
REM ============================================
REM Aegis - One-Click Setup & Launch
REM ============================================

echo.
echo ========================================
echo   Aegis - Multi-Agent Kanban Setup
echo ========================================
echo.

REM Check Python
echo [1/5] Checking for Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Python not found!
    echo   Please install Python 3.10+ from https://python.org
    echo   Make sure to check "Add Python to PATH" during install
    pause
    exit /b 1
)
echo   ✓ Python found

REM Check Node.js (optional)
echo [2/5] Checking for Node.js...
node --version >nul 2>&1
if %errorlevel% equ 0 (
    echo   ✓ Node.js found
) else (
    echo   - Node.js not found (optional - for advanced features)
)

REM Create virtual environment
echo [3/5] Setting up Python environment...
if not exist "venv" (
    python -m venv venv
    echo   ✓ Virtual environment created
) else (
    echo   ✓ Virtual environment already exists
)

REM Activate virtual environment and install
echo [4/5] Installing dependencies...
call venv\Scripts\activate.bat
pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo   ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo   ✓ Dependencies installed

REM Create .env if not exists
echo [5/5] Configuration...
if not exist ".env" (
    copy .env.example .env >nul
    echo   ✓ Configuration created
) else (
    echo   ✓ Configuration already exists
)

echo.
echo ========================================
echo   Setup Complete!
echo ========================================
echo.
echo Starting Aegis...
echo.
echo The dashboard will open at: http://localhost:8080
echo.
echo Press Ctrl+C to stop the server
echo.

REM Start the server
python main.py
