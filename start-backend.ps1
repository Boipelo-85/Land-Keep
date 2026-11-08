$ErrorActionPreference = 'Stop'
$backend = Join-Path $PSScriptRoot 'backend'
$candidates = @(
    (Join-Path $PSScriptRoot 'backend\.venv\Scripts\python.exe'),
    (Join-Path $PSScriptRoot '.landkeep-runtime\Scripts\python.exe'),
    (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
)
$originalPythonPath = $env:PYTHONPATH
$python = $null
foreach ($candidate in $candidates) {
    if (!(Test-Path -LiteralPath $candidate)) { continue }
    $env:PYTHONPATH = $originalPythonPath
    if ($candidate -eq $candidates[2]) {
        $packages = Join-Path $PSScriptRoot '.landkeep-runtime\Lib\site-packages'
        $env:PYTHONPATH = "$packages;$originalPythonPath"
    }
    try {
        & $candidate -c "import fastapi, sqlalchemy, uvicorn, alembic" 2>$null
        if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
    } catch { continue }
}
if (!$python) {
    $env:PYTHONPATH = $originalPythonPath
    throw 'No working Python environment with backend dependencies found. Install Python 3.12, create backend\.venv, and install backend\requirements.txt.'
}
Set-Location $backend
& $python ensure_secret.py
if ($LASTEXITCODE -ne 0) { throw 'Login signing key configuration failed.' }
& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed. See the error above.' }
& $python initialize_demo.py
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
