# szpeter2026 知识库 - 管理脚本
param(
    [ValidateSet("start", "web", "import", "query", "report", "test", "setup", "stats",
                 "docker-up", "docker-down", "docker-status", "docker-reset")]
    [string]$Action = "web"
)

# Auto-detect project root (script dir, optional SZPETER_HOME override)
$ScriptDir = Split-Path -Parent $PSScriptRoot
$projectPaths = @($ScriptDir, $env:SZPETER_HOME) | Where-Object { $_ } | Select-Object -Unique

$ProjectRoot = $null
foreach ($p in $projectPaths) {
    if ($p -and (Test-Path $p) -and (Test-Path "$p\requirements.txt")) {
        $ProjectRoot = $p
        break
    }
}

if (-not $ProjectRoot) {
    Write-Host "[ERROR] Project not found at $ScriptDir" -ForegroundColor Red
    if (-not $env:SZPETER_HOME) {
        Write-Host "       Set `$env:SZPETER_HOME to your clone path if the repo lives elsewhere." -ForegroundColor Yellow
    }
    exit 1
}

$env:PYTHONPATH = "$ProjectRoot;$ProjectRoot\static"

# ===== Venv Activation =====
function Activate-Venv {
    $venvPath = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
    if (Test-Path $venvPath) {
        . $venvPath
        Write-Host "[OK] venv activated" -ForegroundColor Green
    } else {
        Write-Host "[WARN] .venv not found, using system python" -ForegroundColor Yellow
    }
}

function Start-WebDashboard {
    Write-Host "`n 启动 szpeter2026 Web 管理面板..." -ForegroundColor Cyan
    Set-Location $ProjectRoot
    Activate-Venv
    python static\src\web_dashboard.py
}

function Start-Import {
    param([string]$Path = "$ProjectRoot\knowledge_base\documents")
    Write-Host "`n 导入文档: $Path" -ForegroundColor Cyan
    Set-Location $ProjectRoot
    Activate-Venv
    python scripts\import_docs.py --path "$Path"
}

function Start-Query {
    param([string]$Query)
    if (-not $Query) {
        $Query = Read-Host "请输入查询内容"
    }
    Set-Location $ProjectRoot
    Activate-Venv
    python scripts\query.py "$Query"
}

function Invoke-Report {
    param([string]$Type = "daily")
    Write-Host "`n 生成 $Type 报告..." -ForegroundColor Cyan
    Set-Location $ProjectRoot
    Activate-Venv
    python scripts\gen_report.py $Type
}

function Invoke-Tests {
    Write-Host "`n 运行端到端测试..." -ForegroundColor Cyan
    Set-Location $ProjectRoot
    Activate-Venv
    python tests\test_e2e.py
}

function Invoke-Setup {
    Write-Host "`n 环境初始化..." -ForegroundColor Cyan
    Set-Location $ProjectRoot
    Activate-Venv

    python --version 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] 未找到 Python，请先安装 Python 3.10+" -ForegroundColor Red
        return
    }
    Write-Host "[OK] Python 已就绪" -ForegroundColor Green

    Write-Host "安装依赖..." -ForegroundColor Yellow
    pip install -r requirements.txt -q

    if (-not (Test-Path ".env")) {
        if (Test-Path ".env.example") {
            Copy-Item .env.example .env
            Write-Host "[WARN] 已创建 .env 文件，请编辑填入 API Key" -ForegroundColor Yellow
        } else {
            Write-Host "[WARN] 未找到 .env.example，请手动创建 .env 文件" -ForegroundColor Yellow
        }
    }

    if (-not (Test-Path ".env.production")) {
        if (Test-Path ".env.production.example") {
            Copy-Item .env.production.example .env.production
            Write-Host "[WARN] 已创建 .env.production 模板，请编辑填入真实配置（勿提交 Git）" -ForegroundColor Yellow
        } else {
            Write-Host "[WARN] 未找到 .env.production.example，请手动创建 .env.production" -ForegroundColor Yellow
        }
    }

    Write-Host "`n[OK] 初始化完成！" -ForegroundColor Green
}

function Show-Stats {
    Write-Host "`n 知识库统计:" -ForegroundColor Cyan
    Set-Location $ProjectRoot
    Activate-Venv
    python -c @"
from src.db_manager import DBManager
from src.vector_store import VectorStore
import json
db = DBManager()
vs = VectorStore()
stats = db.get_stats()
vec = vs.get_collection_stats()
print(f'  documents: {stats[\"documents_total\"]}')
print(f'  completed: {stats[\"documents_completed\"]}')
print(f'  chunks:    {stats[\"chunks_total\"]}')
print(f'  chars:     {stats[\"total_characters\"]:,}')
print(f'  queries:   {stats[\"queries_total\"]}')
print(f'  vectors:   {vec.get(\"total_vectors\", \"N/A\")}')
"@
}

# ===== Docker =====

function Invoke-DockerUp {
    Write-Host "Starting Docker containers..." -ForegroundColor Cyan
    Set-Location $ProjectRoot
    # nginx 已移入 production profile，默认不启动
    docker compose up -d
    Write-Host "`nWaiting for services..." -ForegroundColor Yellow
    Start-Sleep -Seconds 3
    Show-DockerStatus
}

function Invoke-DockerDown {
    Write-Host "Stopping Docker containers..." -ForegroundColor Cyan
    Set-Location $ProjectRoot
    docker compose down
    Write-Host "[OK] Containers stopped (data preserved in db/)" -ForegroundColor Green
}

function Invoke-DockerReset {
    Write-Host "[WARN] This will delete all Docker containers and data!" -ForegroundColor Red
    $confirm = Read-Host "Type YES to confirm"
    if ($confirm -ne "YES") {
        Write-Host "Cancelled" -ForegroundColor Yellow
        return
    }
    Set-Location $ProjectRoot
    docker compose down -v
    Write-Host "[OK] Containers and data removed" -ForegroundColor Green
}

function Show-DockerStatus {
    Set-Location $ProjectRoot
    Write-Host "`n Docker container status:" -ForegroundColor Cyan
    docker compose ps

    Write-Host "`n Health check:" -ForegroundColor Cyan
    try {
        # Chroma port is not mapped to host; check via docker exec
        $null = docker exec szpeter2026-chroma curl -s http://localhost:8000/api/v2/heartbeat 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] Chroma: alive" -ForegroundColor Green
        } else {
            Write-Host "  [FAIL] Chroma: unreachable" -ForegroundColor Red
        }
    } catch {
        Write-Host "  [FAIL] Chroma: unreachable" -ForegroundColor Red
    }

    try {
        $null = docker exec szpeter2026-pgvector pg_isready -U szpeter -d szpeter2026 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] pgvector: ready" -ForegroundColor Green
        } else {
            Write-Host "  [WARN] pgvector: starting..." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  [WARN] pgvector: unknown" -ForegroundColor Yellow
    }
}

switch ($Action) {
    "start" { Start-WebDashboard }
    "web" { Start-WebDashboard }
    "import" { Start-Import }
    "query" { Start-Query }
    "report" { Invoke-Report }
    "test" { Invoke-Tests }
    "setup" { Invoke-Setup }
    "stats" { Show-Stats }
    "docker-up" { Invoke-DockerUp }
    "docker-down" { Invoke-DockerDown }
    "docker-status" { Show-DockerStatus }
    "docker-reset" { Invoke-DockerReset }
}
