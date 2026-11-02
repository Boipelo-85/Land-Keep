$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.landkeep-runtime\Scripts\python.exe'
if (!(Test-Path $python)) { $python = Join-Path $PSScriptRoot 'backend\.venv\Scripts\python.exe' }
if (!(Test-Path $python)) { throw 'Run START-LANDKEEP.cmd first to install the project environment.' }
Set-Location (Join-Path $PSScriptRoot 'backend')
& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed. See the error above.' }
& $python initialize_demo.py
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
