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

function resolveDataDir(value, repoRoot = REPO_ROOT, fallback = defaultDataDir(repoRoot)) {
  if (!value) return fallback
  return path.isAbsolute(value) ? path.normalize(value) : path.resolve(repoRoot, value)
}

/**
 * 解析源码运行与安装包两种布局。
 *
 * 安装包（electron-builder extraResources）：
 *   resources/backend/aiqf-backend.exe
 *   resources/backend/tools/aiqf-napcat-installer.exe
 *   resources/frontend/dist
 * 用户数据、密钥和受管连接器都放在 Electron userData 下，安装目录保持只读。
 */
function resolveRuntime({
  isPackaged = false,
  resourcesPath = '',
  userDataPath = '',
  repoRoot = REPO_ROOT,
  appRoot = repoRoot,
  platform = process.platform,
} = {}) {
  if (!isPackaged) {
    return {
      packaged: false,
      backendMode: 'source',
      repoRoot,
      backendDir: path.join(repoRoot, 'backend'),
      backendExecutable: '',
      frontendDist: path.join(repoRoot, 'frontend', 'dist'),
      envFile: path.join(repoRoot, '.env'),
      installerExecutable: '',
      defaultDataDir: path.join(repoRoot, 'data'),
      defaultConnectorsDir: '',
      shellHtml: path.join(repoRoot, 'desktop', 'shell', 'index.html'),
      iconPath: path.join(repoRoot, 'desktop', 'assets', 'icon.png'),
      smokeOutputDir: path.join(repoRoot, 'desktop', '.smoke'),
      desktopDir: path.join(repoRoot, 'desktop'),
    }
  }
  const resources = path.resolve(resourcesPath)
  const userData = path.resolve(userDataPath)
  const app = path.resolve(appRoot)
  const exeName = platform === 'win32' ? 'aiqf-backend.exe' : 'aiqf-backend'
  const installerName = platform === 'win32' ? 'aiqf-napcat-installer.exe' : 'aiqf-napcat-installer'
  return {
    packaged: true,
    backendMode: 'bundled',
    repoRoot,
    backendDir: path.join(resources, 'backend'),
    backendExecutable: path.join(resources, 'backend', exeName),
    frontendDist: path.join(resources, 'frontend', 'dist'),
    envFile: path.join(userData, '.env'),
    installerExecutable: path.join(resources, 'backend', 'tools', installerName),
    defaultDataDir: path.join(userData, 'data'),
    // 后端 CONNECTORS_DIR 指向具体连接器（当前仅 NapCat）目录。
    defaultConnectorsDir: path.join(userData, 'connectors', 'napcat'),
    // shell 与图标被打进 app.asar；Electron 的 loadFile/nativeImage 支持 asar 路径。
    shellHtml: path.join(app, 'shell', 'index.html'),
    iconPath: path.join(app, 'assets', 'icon.png'),
    smokeOutputDir: path.join(userData, 'smoke'),
    desktopDir: app,
  }
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
  resolveRuntime,
}
