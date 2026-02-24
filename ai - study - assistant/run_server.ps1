# AI Study Assistant - Uvicorn with hot reload (project code only)
# Run from project root. Uses venv at .\venv.

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$VenvUvicorn = Join-Path $ProjectRoot "venv\Scripts\uvicorn.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment not found at: $ProjectRoot\venv"
    exit 1
}

# Exclude venv so WatchFiles doesn't trigger reloads on venv changes
$VenvPath = (Resolve-Path (Join-Path $ProjectRoot "venv")).Path

Set-Location $ProjectRoot
& $VenvUvicorn "backend.main:app" `
    --host "0.0.0.0" `
    --port 8000 `
    --reload `
    --reload-exclude $VenvPath
