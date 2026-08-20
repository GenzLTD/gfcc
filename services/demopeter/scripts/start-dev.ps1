# szpeter2026 Dev Startup Script (drive fallback)
# Usage: .\scripts\start-dev.ps1
# Auto-detect D/E drives, fallback to C if not found

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  szpeter2026 Smart Startup v2" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ===== Drive Scan =====
Write-Host "[Scan] Checking drives..." -ForegroundColor Yellow

$driveD = Test-Path "D:\"
$driveE = Test-Path "E:\"

if ($driveD) { Write-Host "       D: connected" -ForegroundColor Green }
else         { Write-Host "       D: not found" -ForegroundColor DarkGray }

if ($driveE) { Write-Host "       E: connected" -ForegroundColor Green }
else         { Write-Host "       E: not found" -ForegroundColor DarkGray }

Write-Host ""

# ===== Docker Path (D first, C fallback) =====
$dockerPaths = @(
    "D:\ProgramFiles\Docker\Docker\Docker Desktop.exe",
    "C:\Program Files\Docker\Docker\Docker Desktop.exe"
)
$dockerExe = $null
foreach ($p in $dockerPaths) {
    if (Test-Path $p) { $dockerExe = $p; break }
}

# ===== Project Path (script-dir first, E fallback, C last) =====
$scriptDir = Split-Path -Parent $PSScriptRoot
$projectPaths = @($scriptDir, "E:\szpeter2026", "C:\szpeter2026") | Select-Object -Unique

$projectRoot = $null
foreach ($p in $projectPaths) {
    if ($p -and (Test-Path $p) -and (Test-Path "$p\requirements.txt")) {
        $projectRoot = $p
        break
    }
}

if (-not $projectRoot) {
    Write-Host "[ERROR] Project not found!" -ForegroundColor Red
    Write-Host "        Expected at: E:\szpeter2026 or C:\szpeter2026" -ForegroundColor DarkGray
    Write-Host "        git clone https://github.com/szpeter2026/DemoPeter.git C:\szpeter2026" -ForegroundColor DarkGray
    Read-Host "Press Enter to exit"
    exit 1
}

Set-Location $projectRoot
$env:PYTHONPATH = "$projectRoot;$projectRoot\static"

Write-Host "[Mode]" -ForegroundColor Yellow
Write-Host "       project: $projectRoot" -ForegroundColor Green
if ($dockerExe) { Write-Host "       docker:  $dockerExe" -ForegroundColor Green }
else            { Write-Host "       docker:  not found (skip containers)" -ForegroundColor DarkGray }
Write-Host ""

# ===== [1/4] Env Vars =====
Write-Host "[1/4] Env vars..." -ForegroundColor Yellow
if ($driveD) {
    $env:PIP_CACHE_DIR = "D:\pip-cache"
    Write-Host "       pip cache -> D:\pip-cache" -ForegroundColor Green
} else {
    Write-Host "       pip cache -> default (C:)" -ForegroundColor DarkGray
}

# ===== [2/4] Docker =====
Write-Host "[2/4] Docker..." -ForegroundColor Yellow
$dockerAvailable = $false

if ($dockerExe) {
    # Check if already running
    try {
        $null = docker info 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "       already running" -ForegroundColor Green
            $dockerAvailable = $true
        }
    } catch {}

    # Start if not running
    if (-not $dockerAvailable) {
        Write-Host "       starting Docker Desktop..." -ForegroundColor Yellow
        Start-Process $dockerExe -WindowStyle Hidden

        Write-Host "       waiting (max 60s)..." -ForegroundColor Yellow
        $timeout = 60
        while ($timeout -gt 0) {
            try {
                $null = docker info 2>$null
                if ($LASTEXITCODE -eq 0) { break }
            } catch {}
            Start-Sleep -Seconds 2
            $timeout -= 2
        }
        if ($timeout -le 0) {
            Write-Host "       timeout, skip containers" -ForegroundColor Red
        } else {
            Write-Host "       ready" -ForegroundColor Green
            $dockerAvailable = $true
        }
    }

    # Start containers
    if ($dockerAvailable) {
        Write-Host "       starting containers..." -ForegroundColor Yellow
        docker compose up -d 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "       containers started" -ForegroundColor Green
        } else {
            Write-Host "       container start failed (RAG -> SQLite fallback)" -ForegroundColor DarkYellow
        }
    }
} else {
    Write-Host "       Docker not installed (RAG -> SQLite fallback)" -ForegroundColor DarkGray
}

# ===== [3/4] Python Env =====
Write-Host "[3/4] Python env..." -ForegroundColor Yellow

$venvPath = Join-Path $projectRoot ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "       creating venv..."
    python -m venv .venv 2>&1 | Out-Null
}

$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    . $activateScript
    Write-Host "       venv activated" -ForegroundColor Green
} else {
    Write-Host "       using system python" -ForegroundColor DarkYellow
}

pip install -r requirements.txt -q 2>&1 | Out-Null
Write-Host "       deps ready" -ForegroundColor Green

# ===== [4/4] Start Panel =====
Write-Host "[4/4] Starting panel..." -ForegroundColor Yellow
Write-Host ""
Write-Host "       http://127.0.0.1:5220" -ForegroundColor Cyan
Write-Host "       Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

python static/src/web_dashboard.py
