$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot 'client-vite-scaffold')
npm run dev -- --host 127.0.0.1
