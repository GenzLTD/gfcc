# gfcc 归集脚本：从 D/E 盘源目录复制源码到 monorepo（排除数据/缓存/虚拟环境）
$ErrorActionPreference = 'Stop'

function Copy-Clean {
    param([string]$Src, [string]$Dst, [string]$Label)
    if (-not (Test-Path $Src)) { Write-Host "SKIP $Label : $Src not found"; return }
    New-Item -ItemType Directory -Force -Path $Dst | Out-Null
    robocopy $Src $Dst /E `
        /XD __pycache__ .git build dist node_modules .venv venv .pytest_cache .chroma-cache logs data db reports chronicle `
        /XF *.pyc *.log `
        /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    $code = $LASTEXITCODE
    if ($code -ge 8) { throw "robocopy FAILED($code): $Label" }
    Write-Host "OK $Label (robocopy=$code)"
}

Copy-Clean 'D:\surface-zervi\GitHub\szjason72\ethos'  'D:\gfcc\services\ethos'       'ethos'
Copy-Clean 'D:\surface-zervi\GitHub\szjason72\tenet'  'D:\gfcc\services\tenet'       'tenet'
Copy-Clean 'D:\surface-zervi\GitHub\szjason72\Tatha'  'D:\gfcc\services\tatha'       'tatha'
Copy-Clean 'E:\DemoPeter'                             'D:\gfcc\services\demopeter'  'demopeter'

# agentmemory：仅复制网关/桥/引擎配置（联调产物与数据不归集）
New-Item -ItemType Directory -Force -Path 'D:\gfcc\services\agentmemory' | Out-Null
foreach ($f in @('gateway.py', 'am-bridge.mjs', 'iii-config.docker.yaml')) {
    $src = Join-Path 'E:\CorpusPipeline\agentmemory' $f
    if (Test-Path $src) { Copy-Item $src (Join-Path 'D:\gfcc\services\agentmemory' $f) -Force; Write-Host "OK am/$f" }
    else { Write-Host "SKIP am/$f (missing)" }
}

Write-Host 'COPY_DONE'
