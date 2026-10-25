# AI 群友桌面版启动器：安装 Electron（仅首次）并打开桌面窗口。
# 兼容 PowerShell 5.1；所有路径都以本脚本所在仓库为基准，不写死盘符。

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DesktopDir = Join-Path $RepoRoot 'desktop'
$DesktopPackage = Join-Path $DesktopDir 'package.json'
$ElectronCmd = Join-Path $DesktopDir 'node_modules\.bin\electron.cmd'
$ElectronExe = Join-Path $DesktopDir 'node_modules\electron\dist\electron.exe'
$ElectronInstall = Join-Path $DesktopDir 'node_modules\electron\install.js'

function Fail([string]$Message) {
  Write-Host ''
  Write-Host $Message -ForegroundColor Red
  exit 1
}

if (-not (Test-Path -LiteralPath $DesktopPackage)) {
  Fail "找不到 desktop\package.json。请确认仓库完整。"
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Fail '未找到 Node.js。请安装 Node.js 20 或更高版本后重新启动。'
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Fail '未找到 npm。请安装包含 npm 的 Node.js 20 或更高版本。'
}

if (-not (Test-Path -LiteralPath $ElectronCmd)) {
  Write-Host '首次运行：正在安装桌面壳依赖（Electron），首次下载可能需要几分钟…' -ForegroundColor Cyan
  Push-Location $DesktopDir
  try {
    & npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) {
      Fail "安装桌面壳依赖失败（npm 退出码 $LASTEXITCODE）。请检查网络或 npm 配置后重试。"
    }
  }
  finally {
    Pop-Location
  }
}

if (-not (Test-Path -LiteralPath $ElectronCmd)) {
  Fail 'Electron 安装不完整：未找到 node_modules\.bin\electron.cmd。请删除 desktop\node_modules 后重试。'
}

if (-not (Test-Path -LiteralPath $ElectronExe)) {
  Write-Host '正在下载 Electron 运行时（约 150 MB）…' -ForegroundColor Cyan
  Push-Location $DesktopDir
  try {
    & node $ElectronInstall
    if ($LASTEXITCODE -ne 0) {
      Fail '下载 Electron 运行时失败。请检查网络后重试；国内网络可先设置 $env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/" 再运行。'
    }
  }
  finally {
    Pop-Location
  }
}

if (-not (Test-Path -LiteralPath $ElectronExe)) {
  Fail 'Electron 运行时缺失：node_modules\electron\dist\electron.exe 不存在。请删除 desktop\node_modules 后重试。'
}

Write-Host '正在打开 AI 群友桌面版…' -ForegroundColor Green
Push-Location $DesktopDir
try {
  & $ElectronCmd '.' @args
  $ElectronExitCode = $LASTEXITCODE
}
finally {
  Pop-Location
}

exit $ElectronExitCode
