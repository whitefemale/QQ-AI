# AI 群友质量检查（Windows PowerShell）
# 用法：
#   .\scripts\check.ps1                 # 后端 + 前端全量检查（含构建）
#   .\scripts\check.ps1 -BackendOnly
#   .\scripts\check.ps1 -FrontendOnly
# 任一步失败立即以非零状态退出。

param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"

if ($BackendOnly -and $FrontendOnly) {
    Write-Error "-BackendOnly 与 -FrontendOnly 不能同时使用。"
}

function Invoke-Step {
    param(
        [string]$Label,
        [scriptblock]$Command
    )
    Write-Host ""
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label 失败（退出码 $LASTEXITCODE）。"
    }
}

if (-not $FrontendOnly) {
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Error "未找到后端虚拟环境：$python"
    }
    Push-Location $backend
    try {
        Invoke-Step "后端格式检查 (ruff format --check)" { & $python -m ruff format --check app tests }
        Invoke-Step "后端静态检查 (ruff check)" { & $python -m ruff check app tests }
        Invoke-Step "后端类型检查 (mypy)" { & $python -m mypy app }
        Invoke-Step "后端测试 (pytest)" { & $python -m pytest -q }
    }
    finally {
        Pop-Location
    }
}

if (-not $BackendOnly) {
    if (-not (Test-Path -LiteralPath (Join-Path $frontend "node_modules"))) {
        Write-Error "未找到 frontend/node_modules。请先运行：cd frontend; npm install"
    }
    Push-Location $frontend
    try {
        Invoke-Step "前端类型检查 (vue-tsc)" { & npm run type-check }
        Invoke-Step "前端单元测试 (vitest)" { & npm run test }
        Invoke-Step "前端生产构建 (vite build)" { & npm run build }
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "全部检查通过。" -ForegroundColor Green
