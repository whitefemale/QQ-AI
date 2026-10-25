#!/usr/bin/env bash
# AI 群友开发启动脚本（Linux / macOS / Git Bash）
# 用法：./scripts/dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

if [[ -x "$BACKEND/.venv/Scripts/python.exe" ]]; then
  PYTHON="${PYTHON:-$BACKEND/.venv/Scripts/python.exe}"
elif [[ -x "$BACKEND/.venv/bin/python" ]]; then
  PYTHON="${PYTHON:-$BACKEND/.venv/bin/python}"
else
  echo "未找到后端虚拟环境。请先在 backend 目录创建 .venv 并安装依赖。" >&2
  exit 1
fi

if [[ ! -d "$FRONTEND/node_modules" ]]; then
  echo "未找到 frontend/node_modules。请先运行：cd frontend && npm install" >&2
  exit 1
fi

if [[ ! -f "$ROOT/.env" ]]; then
  echo "警告：未找到 .env。请先运行：$PYTHON scripts/gen_keys.py --write" >&2
fi

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "启动后端：http://127.0.0.1:8000"
(
  cd "$BACKEND"
  export PYTHONUTF8=1
  exec "$PYTHON" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) &
BACKEND_PID=$!

sleep 1
echo "启动前端：http://127.0.0.1:5173（Ctrl+C 停止）"
cd "$FRONTEND"
npm run dev
