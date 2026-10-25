# AI 群友开发启动脚本（Windows PowerShell）
# 用法：.\scripts\dev.ps1
# 后端 http://127.0.0.1:8000（自动重载），前端 http://127.0.0.1:5173

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

function Quote-PS([string]$value) {
    return "'" + $value.Replace("'", "''") + "'"
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "未找到后端虚拟环境：$python`n请先在 backend 目录创建 .venv 并安装依赖。"
}

if (-not (Test-Path -LiteralPath (Join-Path $frontend "node_modules"))) {
    Write-Error "未找到 frontend/node_modules。请先运行：cd frontend; npm install"
}

$envFile = Join-Path $root ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Warning "未找到 .env。请先运行：backend\.venv\Scripts\python.exe scripts\gen_keys.py --write"
}

$backendCmd = @(
    "Set-Location -LiteralPath $(Quote-PS $backend)",
    "`$env:PYTHONUTF8 = '1'",
    "& $(Quote-PS $python) -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
) -join "; "

$frontendCmd = @(
    "Set-Location -LiteralPath $(Quote-PS $frontend)",
    "`$env:PYTHONUTF8 = '1'",
    "npm run dev"
) -join "; "

Write-Host "启动后端（新窗口）..." -ForegroundColor Cyan
Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $backendCmd) | Out-Null
Start-Sleep -Seconds 1

Write-Host "启动前端（新窗口）..." -ForegroundColor Cyan
Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $frontendCmd) | Out-Null

Write-Host ""
Write-Host "控制台：  http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "API 文档：http://127.0.0.1:8000/api/docs" -ForegroundColor Green
Write-Host ""
Write-Host "关闭对应的 PowerShell 窗口即可停止服务。首次使用请在控制台加载 Mock 演示环境。"
