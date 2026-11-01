'use strict'

const {
  app,
  BrowserWindow,
  Menu,
  Notification,
  Tray,
  dialog,
  ipcMain,
  nativeImage,
  session,
  shell,
} = require('electron')
const crypto = require('node:crypto')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { fileURLToPath, pathToFileURL } = require('node:url')

const paths = require('./lib/paths')
const { SettingsStore } = require('./lib/settings')
const { BackendManager } = require('./lib/backend')
const { createLogger } = require('./lib/logger')
const { createCommandRunner, ensureLocalEnvFile, inspectPackagedRuntime, runSetup } = require('./lib/setup')
const { findFreePort } = require('./lib/ports')

const SMOKE_MODE = process.argv.includes('--smoke')
const RELEASES_URL = 'https://github.com/whitefemale/QQ-AI/releases'
const FOLDER_KINDS = new Set(['data', 'logs', 'backups', 'connectors'])

// 冒烟模式使用独立的 userData，避免读写用户真实的桌面设置、缓存与日志。
if (SMOKE_MODE) {
  const smokeUserData = fs.mkdtempSync(path.join(os.tmpdir(), 'aiqf-desktop-smoke-userdata-'))
  app.setPath('userData', smokeUserData)
}

// 源码运行与安装包使用不同资源布局；所有路径都从这一处派生。
const RUNTIME = paths.resolveRuntime({
  isPackaged: app.isPackaged,
  resourcesPath: process.resourcesPath,
  userDataPath: app.getPath('userData'),
  repoRoot: paths.REPO_ROOT,
  appRoot: app.getAppPath(),
})

let mainWindow = null
let tray = null
let trayState = { available: false, reason: 'not_initialized' }
let backend = null
let settingsStore = null
let logger = null
let quitting = false
let quitPrepared = false
let setupRunning = false
let smokeRoot = null
let trayHintShown = false
let lastConsoleOrigin = ''
let lastBackendStatus = 'stopped'
let preferredBackendPort = 8000
const recentLogs = []

const setupState = {
  running: false,
  error: '',
  warning: '',
  steps: [],
}

const STARTUP_STEPS = RUNTIME.packaged
  ? [
      ['environment', '检查随附运行环境'],
      ['env', '生成本地安全密钥'],
      ['backend', '启动本地后端'],
    ]
  : [
      ['environment', '检查运行环境'],
      ['venv', '创建后端虚拟环境'],
      ['backend-deps', '检查后端依赖'],
      ['env', '生成本地安全密钥'],
      ['frontend-deps', '安装前端依赖'],
      ['frontend-build', '构建管理界面'],
      ['backend', '启动本地后端'],
    ]

function emptySetupSteps() {
  return STARTUP_STEPS.map(([id, label]) => ({ id, label, status: 'pending', detail: '' }))
}

setupState.steps = emptySetupSteps()

function resolveDataDir() {
  const base = RUNTIME.packaged ? path.dirname(RUNTIME.defaultDataDir) : paths.REPO_ROOT
  return paths.resolveDataDir(
    settingsStore ? settingsStore.load().dataDir : '',
    base,
    RUNTIME.defaultDataDir,
  )
}

/** 连接器目录：空值在源码模式交给后端仓库默认；安装包使用 userData 下的可写目录。 */
function resolveConnectorsDir() {
  const configured = settingsStore ? settingsStore.load().connectorsDir || '' : ''
  if (configured) return configured
  return RUNTIME.packaged ? RUNTIME.defaultConnectorsDir : ''
}

function backendLogPath() {
  return path.join(resolveDataDir(), 'logs', 'app.log')
}

function snapshot() {
  const settings = settingsStore ? settingsStore.load() : {}
  return {
    isDesktop: true,
    packaged: RUNTIME.packaged,
    desktopVersion: app.getVersion(),
    backend: backend
      ? backend.getInfo()
      : {
          status: 'stopped',
          port: null,
          pid: null,
          managed: true,
          version: '',
          error: '',
          health: {
            state: 'unknown',
            lastCheckAt: null,
            latencyMs: null,
            consecutiveFailures: 0,
            message: '',
          },
        },
    settings,
    dataDir: resolveDataDir(),
    logPath: backendLogPath(),
    desktopLogPath: logger ? logger.logPath : '',
    setup: {
      running: setupState.running,
      error: setupState.error,
      warning: setupState.warning,
      steps: setupState.steps.map((step) => ({ ...step })),
    },
    logs: recentLogs.slice(-120),
    tray: { ...trayState },
  }
}

function send(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload)
  }
}

function sendLog(source, line) {
  const entry = { source, line: String(line), at: new Date().toISOString() }
  recentLogs.push(entry)
  if (recentLogs.length > 240) recentLogs.shift()
  send('desktop:log', entry)
}

function sendState() {
  send('desktop:state', snapshot())
}

function setStep(id, label, status, detail = '') {
  const step = setupState.steps.find((item) => item.id === id)
  if (step) {
    step.status = status
    step.detail = detail
    if (label) step.label = label
  } else {
    setupState.steps.push({ id, label, status, detail })
  }
  send('desktop:setup', snapshot().setup)
}

function resetSetupState() {
  setupState.running = false
  setupState.error = ''
  setupState.warning = ''
  setupState.steps = emptySetupSteps()
}

// 只允许诊断复制所需的剪贴板写入权限；摄像头、麦克风、定位、通知、设备等一律拒绝。
const ALLOWED_PERMISSIONS = new Set(['clipboard-sanitized-write'])

function hardenSession(targetSession) {
  targetSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(ALLOWED_PERMISSIONS.has(permission))
  })
  targetSession.setPermissionCheckHandler((_webContents, permission) => ALLOWED_PERMISSIONS.has(permission))
  targetSession.setDevicePermissionHandler(() => false)
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1080,
    minHeight: 700,
    show: false,
    title: 'AI 群友',
    icon: fs.existsSync(RUNTIME.iconPath) ? RUNTIME.iconPath : undefined,
    backgroundColor: '#f4f7fd',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      spellcheck: false,
      offscreen: SMOKE_MODE,
    },
  })

  if (process.platform === 'win32') mainWindow.removeMenu()

  mainWindow.once('ready-to-show', () => {
    if (SMOKE_MODE) return
    const settings = settingsStore.load()
    if (settings.showWindowOnStart || !tray) mainWindow.show()
  })

  mainWindow.on('close', (event) => {
    if (quitting) return
    const settings = settingsStore.load()
    if (settings.closeToTray && trayState.available && tray) {
      event.preventDefault()
      mainWindow.hide()
      if (!trayHintShown && Notification.isSupported()) {
        trayHintShown = true
        new Notification({
          title: 'AI 群友仍在后台运行',
          body: '窗口已最小化到系统托盘。可在托盘菜单中恢复或彻底退出。',
          silent: true,
        }).show()
      }
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url === RELEASES_URL) {
      shell.openExternal(url)
        .catch((error) => logger?.warn(`打开外链失败：${error.message}`))
    }
    return { action: 'deny' }
  })

  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isAllowedNavigation(url)) event.preventDefault()
  })
  mainWindow.webContents.on('will-redirect', (event, url) => {
    if (!isAllowedNavigation(url)) event.preventDefault()
  })
  mainWindow.webContents.on('will-attach-webview', (event) => {
    event.preventDefault()
  })

  mainWindow.webContents.on('did-finish-load', () => {
    sendState()
    send('desktop:setup', snapshot().setup)
  })

  loadShell()
}

function isShellUrl(url) {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'file:') return false
    return path.resolve(fileURLToPath(parsed)).toLowerCase() === path.resolve(RUNTIME.shellHtml).toLowerCase()
  } catch {
    return false
  }
}

function isAllowedNavigation(url) {
  if (isShellUrl(url)) return true
  try {
    const parsed = new URL(url)
    const info = backend ? backend.getInfo() : null
    return (
      parsed.protocol === 'http:' &&
      parsed.hostname === '127.0.0.1' &&
      info?.port != null &&
      parsed.port === String(info.port)
    )
  } catch {
    return false
  }
}

function loadShell() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  lastConsoleOrigin = ''
  mainWindow.loadFile(RUNTIME.shellHtml).catch((error) => {
    if (logger) logger.error(`加载启动页失败：${error.message}`)
  })
}

function navigateToConsole(port, targetPath = '/', { force = false } = {}) {
  if (!mainWindow || mainWindow.isDestroyed() || !port) return
  const origin = `http://127.0.0.1:${port}`
  const normalized = targetPath.startsWith('/') ? targetPath : `/${targetPath}`
  if (!force && lastConsoleOrigin === origin) {
    try {
      const current = new URL(mainWindow.webContents.getURL())
      if (current.origin === origin && current.pathname === normalized) return
    } catch {
      /* 当前地址无法解析时继续加载 */
    }
  }
  lastConsoleOrigin = origin
  // 使用一次性查询参数强制重新获取 index.html，避免升级/重建后命中旧的入口缓存；
  // 静态资源仍使用带哈希的文件名，可正常缓存。
  mainWindow.loadURL(`${origin}${normalized}?desktop=${Date.now()}`).catch((error) => {
    if (logger) logger.error(`加载管理界面失败：${error.message}`)
    loadShell()
  })
}

/** 重启后重新加载控制台，避免停留在旧页面的缓存数据上。 */
function reloadConsole(port) {
  lastConsoleOrigin = ''
  navigateToConsole(port)
}

function backendManagerOptions(dataDir, envBase = process.env) {
  return {
    repoRoot: paths.REPO_ROOT,
    backendDir: RUNTIME.backendDir,
    pythonPath: RUNTIME.packaged ? '' : paths.venvPython(),
    backendMode: RUNTIME.backendMode,
    backendExecutable: RUNTIME.backendExecutable,
    frontendDist: RUNTIME.frontendDist,
    envFile: RUNTIME.envFile,
    installerExecutable: RUNTIME.installerExecutable,
    dataDir,
    connectorsDir: resolveConnectorsDir(),
    envBase,
    preferredPort: preferredBackendPort,
  }
}

function createBackend(dataDir, envBase = process.env) {
  const manager = new BackendManager({
    ...backendManagerOptions(dataDir, envBase),
    logger,
  })
  manager.on('state', (info) => {
    if (logger && info.status !== lastBackendStatus) {
      logger.info(`后端状态：${info.status}${info.port ? ` :${info.port}` : ''}`)
    }
    const wasRunning = lastBackendStatus === 'running' || lastBackendStatus === 'external'
    const isRunning = info.status === 'running' || info.status === 'external'
    lastBackendStatus = info.status
    // 健康探测也会发出 state 事件；只有真正进入运行态才导航，避免把用户从向导或设置页切走。
    if (isRunning && !wasRunning && !setupRunning && !setupState.warning) {
      navigateToConsole(info.port, '/')
    }
    if (info.status === 'error' && !setupRunning) loadShell()
    sendState()
    updateTrayMenu()
  })
  manager.on('log', (line) => sendLog('backend', line))
  lastBackendStatus = 'stopped'
  return manager
}

async function startBackendNow(dataDir, envBase = process.env) {
  if (backend) {
    const current = backend.getInfo()
    if (current.status === 'running' || current.status === 'external') return
    await backend.stop()
  }
  backend = createBackend(dataDir, envBase)
  updateTrayMenu()
  await backend.start()
}

async function startSystem({ demo = false, envBase = process.env } = {}) {
  if (setupRunning) return snapshot()
  resetSetupState()
  setupRunning = true
  setupState.running = true
  const wasFirstRun = !settingsStore.load().firstRunCompleted
  loadShell()
  sendState()
  send('desktop:setup', snapshot().setup)

  try {
    const dataDir = resolveDataDir()

    if (RUNTIME.packaged) {
      setStep('environment', '检查随附运行环境', 'running')
      const packCheck = inspectPackagedRuntime({
        backendExecutable: RUNTIME.backendExecutable,
        frontendDist: RUNTIME.frontendDist,
        installerExecutable: RUNTIME.installerExecutable,
      })
      if (!packCheck.ok) {
        setStep('environment', '检查随附运行环境', 'error', `缺少：${packCheck.missing.join('、')}`)
        throw new Error(`安装包不完整：缺少 ${packCheck.missing.join('、')}。请重新安装。`)
      }
      setStep(
        'environment',
        '检查随附运行环境',
        'ok',
        packCheck.installerExists ? '内置后端与界面，无需 Python/Node' : '内置后端与界面；连接器自动安装不可用',
      )

      setStep('env', '生成本地安全密钥', 'running')
      const envState = ensureLocalEnvFile({ envFile: RUNTIME.envFile })
      setStep('env', '生成本地安全密钥', 'ok', envState.created ? '已在用户目录生成' : '已存在')
    } else {
      const runner = createCommandRunner({ logger })
      setStep('environment', '检查运行环境', 'running')
      await runSetup({
        repoRoot: paths.REPO_ROOT,
        runner,
        onStep: (step) => setStep(step.id, step.label, step.status, step.detail),
        onLog: (line) => sendLog('setup', line),
      })
      setStep('environment', '检查运行环境', 'ok')
    }
    sendState()

    setStep('backend', '启动本地后端', 'running')
    await startBackendNow(dataDir, envBase)
    setStep('backend', '启动本地后端', 'ok')

    if (demo) {
      try {
        const info = backend.getInfo()
        const response = await fetch(`http://127.0.0.1:${info.port}/api/demo/bootstrap`, {
          method: 'POST',
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        if (logger) logger.info('Mock 演示环境已初始化。')
      } catch (error) {
        setupState.warning = `后端已启动，但 Mock 演示初始化失败：${error.message}。可稍后在仪表盘重试。`
        if (logger) logger.warn(setupState.warning)
      }
    }

    const updated = settingsStore.update({ firstRunCompleted: true })
    logger.info(`桌面版启动完成，设置：${JSON.stringify(updated)}`)
    setupState.running = false
    setupRunning = false
    sendState()
    send('desktop:setup', snapshot().setup)
    if (!setupState.warning) {
      const info = backend.getInfo()
      // 首次启动先进入接入向导；之后保留仪表盘作为入口。
      if (info.port) navigateToConsole(info.port, wasFirstRun ? '/onboarding' : '/', { force: true })
    }
  } catch (error) {
    setupState.error = error instanceof Error ? error.message : String(error)
    const backendStep = setupState.steps.find((step) => step.id === 'backend')
    if (backendStep && backendStep.status === 'running') {
      setStep('backend', '启动本地后端', 'error', setupState.error)
    }
    if (logger) logger.error(`启动失败：${setupState.error}`)
    setupState.running = false
    setupRunning = false
    loadShell()
    sendState()
    send('desktop:setup', snapshot().setup)
  }
  return snapshot()
}

function updateTrayMenu() {
  if (!tray) return
  const info = backend
    ? backend.getInfo()
    : { status: 'stopped', port: null, managed: true }
  const running = info.status === 'running' || info.status === 'external'
  const statusLabel = {
    stopped: '后端未运行',
    starting: '后端启动中…',
    stopping: '后端停止中…',
    running: `后端运行中 · 端口 ${info.port}`,
    external: `已连接外部后端 · 端口 ${info.port}`,
    error: '后端异常',
  }[info.status] ?? `后端状态：${info.status}`

  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '打开控制台', click: showConsole },
      { label: '打开接入向导', enabled: running, click: () => showConsolePath('/onboarding') },
      { label: statusLabel, enabled: false },
      { type: 'separator' },
      {
        label: running ? (info.status === 'external' ? '断开外部后端' : '停止后端') : '启动后端',
        click: async () => {
          if (running) await backend?.stop()
          else await startSystem({ demo: false })
        },
      },
      {
        label: '重启后端',
        enabled: running && info.managed,
        click: async () => {
          try {
            await backend?.restart()
            const info = backend?.getInfo()
            if (info?.port) reloadConsole(info.port)
          } catch (error) {
            if (logger) logger.error(`重启失败：${error.message}`)
            await startSystem({ demo: false })
          }
        },
      },
      { type: 'separator' },
      { label: '打开数据目录', click: () => openFolder('data') },
      { label: '打开日志', click: () => openFolder('logs') },
      { label: '打开备份目录', click: () => openFolder('backups') },
      { type: 'separator' },
      { label: '退出', click: () => app.quit() },
    ]),
  )
}

function createTray() {
  if (!fs.existsSync(RUNTIME.iconPath)) {
    trayState = { available: false, reason: 'icon_missing' }
    if (logger) logger.warn('托盘图标文件缺失，关闭窗口将退出应用。')
    return
  }
  const image = nativeImage.createFromPath(RUNTIME.iconPath)
  if (image.isEmpty()) {
    trayState = { available: false, reason: 'icon_invalid' }
    if (logger) logger.warn('托盘图标无法读取，关闭窗口将退出应用。')
    return
  }
  try {
    tray = new Tray(image.resize({ width: 32, height: 32 }))
    trayState = { available: true, reason: '' }
  } catch (error) {
    tray = null
    trayState = { available: false, reason: 'tray_error' }
    if (logger) logger.warn(`创建系统托盘失败：${error.message}`)
    return
  }
  tray.setToolTip('AI 群友')
  tray.on('double-click', showConsole)
  tray.on('click', showConsole)
  updateTrayMenu()
}

function showConsole() {
  if (!mainWindow) {
    createWindow()
  }
  if (!mainWindow) return
  const info = backend ? backend.getInfo() : null
  const loaded = mainWindow.webContents.getURL()
  if (info && (info.status === 'running' || info.status === 'external') && info.port) {
    if (!loaded.startsWith(`http://127.0.0.1:${info.port}/`)) navigateToConsole(info.port)
  } else if (!loaded.startsWith('file:')) {
    loadShell()
  }
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

/** 从托盘直接打开指定内部页面；只在后端运行且窗口存在时生效。 */
function showConsolePath(targetPath) {
  const info = backend ? backend.getInfo() : null
  if (!info || !info.port || (info.status !== 'running' && info.status !== 'external')) return
  if (!mainWindow) createWindow()
  if (!mainWindow) return
  navigateToConsole(info.port, targetPath, { force: true })
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

async function openFolder(kind) {
  if (!FOLDER_KINDS.has(kind)) throw new Error('不支持的目录类型。')
  const dataDir = resolveDataDir()
  const target = {
    data: dataDir,
    logs: path.join(dataDir, 'logs'),
    backups: path.join(dataDir, 'backups'),
    connectors: resolveConnectorsDir() || path.join(paths.REPO_ROOT, 'connectors', 'napcat'),
  }[kind]
  fs.mkdirSync(target, { recursive: true })
  const error = await shell.openPath(target)
  if (error) throw new Error(error)
}

function registerIpc() {
  ipcMain.handle('desktop:get-info', () => snapshot())
  ipcMain.handle('desktop:get-settings', () => settingsStore.load())
  ipcMain.handle('desktop:update-settings', (_event, patch) => {
    const before = settingsStore.load()
    const updated = settingsStore.update(patch)
    if (before.dataDir !== updated.dataDir && logger) {
      logger.info('数据目录设置已更新，将在重启后端后生效。')
    }
    if (before.connectorsDir !== updated.connectorsDir && logger) {
      logger.info('连接器目录设置已更新，将在重启后端后生效。')
    }
    updateTrayMenu()
    sendState()
    return {
      settings: updated,
      restartRequired: before.dataDir !== updated.dataDir || before.connectorsDir !== updated.connectorsDir,
    }
  })
  // 只打开系统目录选择对话框并保存选择；不读写文件、不执行命令。
  ipcMain.handle('desktop:choose-connectors-dir', async () => {
    const before = settingsStore.load()
    const options = {
      title: '选择受管连接器根目录',
      defaultPath: before.connectorsDir || resolveConnectorsDir() || paths.REPO_ROOT,
      properties: ['openDirectory', 'createDirectory'],
    }
    const result = mainWindow
      ? await dialog.showOpenDialog(mainWindow, options)
      : await dialog.showOpenDialog(options)
    if (result.canceled || !result.filePaths.length) {
      return { settings: before, restartRequired: false, canceled: true }
    }
    const updated = settingsStore.update({ connectorsDir: result.filePaths[0] })
    if (logger) logger.info('连接器目录设置已更新，将在重启后端后生效。')
    updateTrayMenu()
    sendState()
    return { settings: updated, restartRequired: true, canceled: false }
  })
  ipcMain.handle('desktop:start-backend', (_event, options) => {
    const demo = Boolean(options && options.demo)
    return startSystem({ demo })
  })
  ipcMain.handle('desktop:stop-backend', async () => {
    if (backend) await backend.stop()
    loadShell()
    sendState()
    return snapshot()
  })
  ipcMain.handle('desktop:restart-backend', async () => {
    const dataDir = resolveDataDir()
    const info = backend ? backend.getInfo() : null
    if (info && info.status === 'external') {
      throw new Error('当前连接的是外部后端，桌面版不能重启它。请先在启动它的终端中停止。')
    }
    if (backend) await backend.stop()
    backend = createBackend(dataDir)
    await backend.start()
    const restarted = backend.getInfo()
    if (restarted.port) reloadConsole(restarted.port)
    return snapshot()
  })
  ipcMain.handle('desktop:open-folder', (_event, kind) => openFolder(String(kind)))
  ipcMain.handle('desktop:open-releases', () => shell.openExternal(RELEASES_URL))
  ipcMain.handle('desktop:open-console', () => {
    const info = backend ? backend.getInfo() : null
    if (info && info.port) {
      setupState.warning = ''
      navigateToConsole(info.port)
    }
    return snapshot()
  })
  ipcMain.handle('desktop:quit', () => app.quit())
}

function setupAppEvents() {
  app.on('before-quit', (event) => {
    if (quitPrepared) return
    event.preventDefault()
    if (quitting) return
    quitting = true
    Promise.resolve(backend ? backend.stop() : null).finally(() => {
      quitPrepared = true
      if (tray) {
        tray.destroy()
        tray = null
      }
      app.quit()
    })
  })

  app.on('window-all-closed', () => {
    const settings = settingsStore ? settingsStore.load() : { closeToTray: false }
    if (process.platform !== 'darwin' && (!settings.closeToTray || !trayState.available)) app.quit()
  })
}

async function smokeRun() {
  const outputDir = RUNTIME.smokeOutputDir
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'aiqf-desktop-smoke-'))
  smokeRoot = tempRoot
  const dataDir = path.join(tempRoot, 'data')
  fs.mkdirSync(dataDir, { recursive: true })
  const credentialKey = crypto.randomBytes(32).toString('base64').replace(/\+/gu, '-').replace(/\//gu, '_')
  const envBase = {
    ...process.env,
    CREDENTIAL_ENCRYPTION_KEY: credentialKey,
    APP_SECRET_KEY: crypto.randomBytes(48).toString('base64url'),
  }

  try {
    if (RUNTIME.packaged) {
      const packCheck = inspectPackagedRuntime({
        backendExecutable: RUNTIME.backendExecutable,
        frontendDist: RUNTIME.frontendDist,
        installerExecutable: RUNTIME.installerExecutable,
      })
      if (!packCheck.ok) throw new Error(`安装包不完整：缺少 ${packCheck.missing.join('、')}。`)
    } else {
      if (!fs.existsSync(paths.venvPython())) throw new Error('缺少 backend/.venv，请先运行桌面版向导或手工安装后端。')
      if (!fs.existsSync(path.join(RUNTIME.frontendDist, 'index.html'))) {
        throw new Error('缺少 frontend/dist，请先执行 npm run build。')
      }
    }

    // 先截取启动向导页，再清理缓存并加载管理台，确保截图来自当前构建。
    await loadAndWait(pathToFileURL(RUNTIME.shellHtml).href)
    await wait(900)
    fs.mkdirSync(outputDir, { recursive: true })
    await capture(path.join(outputDir, 'shell.png'))
    await mainWindow.webContents.session.clearCache()

    // 使用非 8000 的临时端口，避免误连用户正在运行的真实后端或截取真实数据。
    preferredBackendPort = await findFreePort(18000)
    backend = new BackendManager({
      ...backendManagerOptions(dataDir, envBase),
      preferredPort: preferredBackendPort,
      logger,
    })
    backend.on('log', (line) => console.log(`[backend] ${line}`))
    await backend.start()
    const info = backend.getInfo()
    if (!info.port) throw new Error('后端未返回端口。')

    const origin = `http://127.0.0.1:${info.port}`
    await loadAndWait(`${origin}/?desktop=${Date.now()}`)
    await wait(1800)
    await capture(path.join(outputDir, 'dashboard.png'))

    await loadAndWait(`${origin}/settings?desktop=${Date.now()}`)
    await wait(1500)
    await capture(path.join(outputDir, 'settings.png'))

    // 再走一遍真实的启动路径（向导 + 后端启动 + 导航），验证首次启动逻辑本身。
    await backend.stop()
    settingsStore.update({ dataDir, firstRunCompleted: false })
    await startSystem({ demo: false, envBase })
    const startup = snapshot()
    if (startup.setup.error) throw new Error(`启动向导失败：${startup.setup.error}`)
    const started = backend ? backend.getInfo() : null
    if (!started || (started.status !== 'running' && started.status !== 'external')) {
      throw new Error(`启动向导未启动后端（状态：${started?.status ?? '未知'}）。`)
    }
    await wait(1200)
    await capture(path.join(outputDir, 'startup.png'))
    const startupUrl = new URL(mainWindow.webContents.getURL())
    if (startupUrl.pathname !== '/onboarding') {
      throw new Error(`首次启动未进入接入向导（当前路径：${startupUrl.pathname}）。`)
    }
    await capture(path.join(outputDir, 'onboarding.png'))

    const health = await backend.checkHealth()
    if (health.health.state !== 'healthy') {
      throw new Error(`后端健康检查未通过：${health.health.state} ${health.health.message}`)
    }
    if (!startup.tray || typeof startup.tray.available !== 'boolean' || typeof startup.tray.reason !== 'string') {
      throw new Error('桌面快照缺少托盘可用性字段。')
    }

    const startupPort = started.port
    await loadAndWait(`http://127.0.0.1:${startupPort}/diagnostics?desktop=${Date.now()}`)
    await wait(1500)
    await capture(path.join(outputDir, 'diagnostics.png'))

    console.log(
      `DESKTOP_STARTUP_OK ${JSON.stringify({
        status: started.status,
        port: startupPort,
        dataDir: startup.dataDir,
        path: startupUrl.pathname,
        health: health.health.state,
        tray: startup.tray,
      })}`,
    )

    console.log(
      `DESKTOP_SMOKE_OK ${JSON.stringify({
        port: info.port,
        startupPort,
        version: info.version,
        screenshots: [
          path.join(outputDir, 'shell.png'),
          path.join(outputDir, 'dashboard.png'),
          path.join(outputDir, 'settings.png'),
          path.join(outputDir, 'startup.png'),
          path.join(outputDir, 'onboarding.png'),
          path.join(outputDir, 'diagnostics.png'),
        ],
      })}`,
    )
    await backend.stop()
    app.exit(0)
  } catch (error) {
    console.error(`DESKTOP_SMOKE_FAIL ${error instanceof Error ? error.stack : String(error)}`)
    if (backend) console.error(backend.tail(30).join('\n'))
    try {
      if (backend) await backend.stop()
    } catch {
      /* 忽略清理错误 */
    }
    app.exit(1)
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function loadAndWait(url) {
  return new Promise((resolve, reject) => {
    if (!mainWindow) return reject(new Error('窗口未创建。'))
    const timeout = setTimeout(() => reject(new Error(`页面加载超时：${url}`)), 30000)
    const onFinish = () => {
      clearTimeout(timeout)
      mainWindow.webContents.removeListener('did-fail-load', onFail)
      resolve()
    }
    const onFail = (_event, code, description) => {
      clearTimeout(timeout)
      mainWindow.webContents.removeListener('did-finish-load', onFinish)
      reject(new Error(`页面加载失败 ${code}：${description}`))
    }
    mainWindow.webContents.once('did-finish-load', onFinish)
    mainWindow.webContents.once('did-fail-load', onFail)
    mainWindow.loadURL(url).catch((error) => {
      clearTimeout(timeout)
      reject(error)
    })
  })
}

async function capture(filePath) {
  if (!mainWindow) throw new Error('窗口未创建。')
  const image = await mainWindow.webContents.capturePage()
  fs.writeFileSync(filePath, image.toPNG())
}

async function boot() {
  hardenSession(session.defaultSession)
  settingsStore = new SettingsStore(path.join(app.getPath('userData'), 'settings.json'))
  logger = createLogger(path.join(app.getPath('userData'), 'logs'))
  logger.info(`桌面版启动（${RUNTIME.packaged ? '安装版' : '源码版'}），资源根：${RUNTIME.packaged ? RUNTIME.desktopDir : paths.REPO_ROOT}`)

  if (SMOKE_MODE) {
    registerIpc()
    createWindow()
    await smokeRun()
    return
  }

  registerIpc()
  setupAppEvents()
  createWindow()
  createTray()

  const settings = settingsStore.load()
  if (!settings.firstRunCompleted || settings.autoStartBackend) {
    // 首次运行或用户开启自动启动：自动执行幂等检查并启动后端。
    await startSystem({ demo: false })
  } else {
    sendState()
  }
}

if (process.platform === 'win32') {
  app.setAppUserModelId('com.aigroupfriend.desktop')
}
if (SMOKE_MODE) {
  app.disableHardwareAcceleration()
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => showConsole())
  app.whenReady().then(boot).catch((error) => {
    console.error(error)
    if (logger) logger.error(`应用启动失败：${error instanceof Error ? error.message : String(error)}`)
    app.exit(1)
  })
  app.on('activate', () => showConsole())
}

process.on('uncaughtException', (error) => {
  if (logger) logger.error(`未捕获异常：${error.stack || error.message}`)
})
process.on('unhandledRejection', (reason) => {
  if (logger) logger.error(`未处理的 Promise 拒绝：${reason instanceof Error ? reason.stack : String(reason)}`)
})
