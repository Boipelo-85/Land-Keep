@echo off
cd /d "%~dp0"
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.12 run_landkeep.py
    goto finished
)
python -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if not errorlevel 1 (
    python run_landkeep.py
    goto finished
)
echo Install Python 3.12 with the Python launcher and Node.js 24 LTS, then try again.
:finished
pause
