$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    } else {
        throw "Python 3.11 is required. Install it from https://www.python.org/downloads/"
    }
}

$projectPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $projectPython -m pip install --upgrade pip
& $projectPython -m pip install -r requirements-graph.txt
& $projectPython -m uvicorn decidr.api.app:app --reload --port 8000
