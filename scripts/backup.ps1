# AI 群友数据库备份（Windows PowerShell）
# 优先调用正在运行的后端备份接口（有清单、校验与审计记录）。
# 后端未启动时自动退化为 SQLite 在线备份，但仍建议通过控制台完成正式备份。
#
# 用法：
#   .\scripts\backup.ps1
#   .\scripts\backup.ps1 -Note "升级前"
#   .\scripts\backup.ps1 -BaseUrl "http://127.0.0.1:8000"
#   .\scripts\backup.ps1 -Offline
#   .\scripts\backup.ps1 -Offline -DatabasePath "D:\somewhere\ai_group_friend.db"
#
# 注意：备份只包含数据库。Token/API Key 在库中为密文；加密密钥本身不进入备份。

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Note = "命令行手动备份",
    [switch]$Offline,
    [string]$DatabasePath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
$dataDir = Join-Path $root "data"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Invoke-OfflineBackup {
    if (-not $DatabasePath) {
        $DatabasePath = Join-Path $dataDir "ai_group_friend.db"
    }
    if (-not (Test-Path -LiteralPath $DatabasePath)) {
        throw "数据库不存在：$DatabasePath"
    }
    if (-not (Test-Path -LiteralPath $python)) {
        throw "未找到后端 Python：$python"
    }
    $targetDir = Join-Path $dataDir "backups"
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    $target = Join-Path $targetDir "manual-$stamp.db"
    $offlineScript = Join-Path $PSScriptRoot "offline_backup.py"

    & $python $offlineScript $DatabasePath $target
    if ($LASTEXITCODE -ne 0) {
        throw "离线备份失败（退出码 $LASTEXITCODE）。"
    }
    Write-Warning "这是离线文件备份，不会出现在控制台备份列表与审计日志中。恢复前请先停止后端并全局暂停。"
}

function Invoke-ApiBackup {
    $body = @{ note = $Note } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    $response = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/backups" `
        -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec 30
    if ($response.error) {
        throw "备份失败：$($response.error.code) $($response.error.message)"
    }
    $data = $response.data
    Write-Host "备份完成。" -ForegroundColor Green
    Write-Host "  ID：      $($data.id)"
    Write-Host "  文件：    $($data.filename)"
    Write-Host "  大小：    $($data.size_bytes) 字节"
    Write-Host "  SHA-256： $($data.sha256)"
    Write-Host "  仅数据库：是；含明文密钥：$($data.includes_secrets)"
    Write-Host "可在控制台「系统设置 → 备份」中校验或恢复。"
}

if ($Offline) {
    Invoke-OfflineBackup
}
else {
    try {
        Invoke-ApiBackup
    }
    catch {
        Write-Warning "无法通过后端接口备份：$($_.Exception.Message)"
        Write-Warning "改用 SQLite 离线备份。"
        Invoke-OfflineBackup
    }
}
