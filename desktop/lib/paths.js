'use strict'

const path = require('node:path')

/** desktop/lib -> 仓库根。全部路径基于仓库位置，不写死盘符。 */
const REPO_ROOT = path.resolve(__dirname, '..', '..')
const BACKEND_DIR = path.join(REPO_ROOT, 'backend')
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend')
const FRONTEND_DIST = path.join(FRONTEND_DIR, 'dist')
const DESKTOP_DIR = path.join(REPO_ROOT, 'desktop')
const SHELL_HTML = path.join(DESKTOP_DIR, 'shell', 'index.html')
const ICON_PATH = path.join(DESKTOP_DIR, 'assets', 'icon.png')
const ENV_FILE = path.join(REPO_ROOT, '.env')
const GEN_KEYS_SCRIPT = path.join(REPO_ROOT, 'scripts', 'gen_keys.py')

function venvPython(repoRoot = REPO_ROOT) {
  return process.platform === 'win32'
    ? path.join(repoRoot, 'backend', '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, 'backend', '.venv', 'bin', 'python')
}

function defaultDataDir(repoRoot = REPO_ROOT) {
  return path.join(repoRoot, 'data')
}

function resolveDataDir(value, repoRoot = REPO_ROOT) {
  if (!value) return defaultDataDir(repoRoot)
  return path.isAbsolute(value) ? path.normalize(value) : path.resolve(repoRoot, value)
}

module.exports = {
  REPO_ROOT,
  BACKEND_DIR,
  FRONTEND_DIR,
  FRONTEND_DIST,
  DESKTOP_DIR,
  SHELL_HTML,
  ICON_PATH,
  ENV_FILE,
  GEN_KEYS_SCRIPT,
  venvPython,
  defaultDataDir,
  resolveDataDir,
}
