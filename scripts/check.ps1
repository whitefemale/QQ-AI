# AI 群友质量检查（Windows PowerShell）
# 用法：
#   .\scripts\check.ps1                 # 后端 + 前端 + 桌面壳单元测试（含前端构建）
#   .\scripts\check.ps1 -BackendOnly
#   .\scripts\check.ps1 -FrontendOnly   # 仅前端；不包含桌面壳测试
# 任一步失败立即以非零状态退出。GUI 截图冒烟需单独执行 electron . --smoke。

param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ErrorActionPreference = "Stop"
# 兼容 PowerShell 5.1：确保中文步骤名与子进程输出在 Windows Terminal / Git Bash 中按 UTF-8 显示。
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
}
catch {
    # 某些宿主机不支持修改控制台编码；不影响检查本身。
}
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$desktop = Join-Path $root "desktop"
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

# 桌面壳测试只在全量检查中运行；-FrontendOnly 保持仅前端范围。
if (-not $BackendOnly -and -not $FrontendOnly) {
    if (-not (Test-Path -LiteralPath (Join-Path $desktop "node_modules"))) {
        Write-Error "未找到 desktop/node_modules。请先运行：cd desktop; npm install"
    }
    Push-Location $desktop
    try {
        Invoke-Step "桌面壳单元测试 (node:test)" { & npm test }
    }
    finally {
        Pop-Location
    }
    Write-Host "提示：GUI 截图冒烟未在 check.ps1 中运行；可在 desktop/ 执行 npm run smoke。" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "全部检查通过。" -ForegroundColor Green
