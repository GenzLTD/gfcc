# Tenet 安装脚本（Windows / PowerShell）
# 用法: .\scripts\install.ps1   （在项目根目录执行）
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

Write-Host "==> 安装 tenet（editable + dev 依赖）..."
python -m pip install -e ".[dev]"

Write-Host "==> 运行测试..."
python -m pytest tests/ -v

Write-Host "==> 完成。在任意 Python 项目中："
Write-Host "    from tenet.security import init_security"
Write-Host "    from tenet.resolver import init_resolver"
