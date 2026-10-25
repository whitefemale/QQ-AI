'use strict'

const bridge = window.aiGroupFriendDesktop

const elements = {
  version: document.getElementById('desktop-version'),
  title: document.getElementById('title'),
  subtitle: document.getElementById('subtitle'),
  badge: document.getElementById('status-badge'),
  notice: document.getElementById('notice'),
  noticeText: document.getElementById('notice-text'),
  noticeAction: document.getElementById('notice-action'),
  dataDir: document.getElementById('data-dir'),
  steps: document.getElementById('steps'),
  demo: document.getElementById('demo'),
  demoWrap: document.getElementById('demo-wrap'),
  primary: document.getElementById('primary'),
  openLog: document.getElementById('open-log'),
  openData: document.getElementById('open-data'),
  quit: document.getElementById('quit'),
  log: document.getElementById('log'),
  clearLog: document.getElementById('clear-log'),
}

let state = null
let logs = []
let busy = false

const STATUS_LABEL = {
  stopped: '未启动',
  starting: '启动中',
  stopping: '停止中',
  running: '运行中',
  external: '外部后端',
  error: '需要处理',
}

const STEP_ICON = {
  pending: '·',
  running: '…',
  ok: '✓',
  skipped: '✓',
  error: '!',
}

function backendRunning() {
  const status = state?.backend?.status
  return status === 'running' || status === 'external'
}

function appendLog(entry, { render = true } = {}) {
  if (!entry || typeof entry.line !== 'string') return
  const source = entry.source === 'backend' ? '后端' : '向导'
  logs.push(`[${source}] ${entry.line}`)
  if (logs.length > 400) logs.shift()
  if (render) renderLogs()
}

function renderLogs() {
  elements.log.textContent = logs.length ? logs.join('\n') : '等待启动…'
  elements.log.scrollTop = elements.log.scrollHeight
}

function renderSteps(steps) {
  elements.steps.replaceChildren()
  for (const step of steps ?? []) {
    const item = document.createElement('li')
    item.className = `step ${step.status || 'pending'}`
    const icon = document.createElement('span')
    icon.className = 'step-icon'
    icon.textContent = STEP_ICON[step.status] ?? '·'
    const label = document.createElement('span')
    label.className = 'step-label'
    label.textContent = step.label
    const detail = document.createElement('span')
    detail.className = 'step-detail'
    detail.textContent = step.detail || ''
    item.append(icon, label, detail)
    elements.steps.append(item)
  }
}

function renderNotice() {
  const error = state?.setup?.error
  const warning = state?.setup?.warning
  elements.notice.hidden = !error && !warning
  elements.notice.classList.toggle('error', Boolean(error))
  elements.noticeText.textContent = error || warning || ''
  elements.noticeAction.hidden = !warning || Boolean(error) || !backendRunning()
}

function render() {
  if (!state) return
  const setup = state.setup ?? {}
  const backend = state.backend ?? {}
  const status = backend.status || 'stopped'
  const running = backendRunning()

  elements.version.textContent = state.desktopVersion || '—'
  elements.dataDir.textContent = state.dataDir || ''
  elements.dataDir.title = state.dataDir || ''

  elements.badge.className = 'badge'
  elements.badge.textContent = setup.error ? '需要处理' : STATUS_LABEL[status] ?? status
  elements.badge.classList.add(setup.error ? 'error' : running ? 'ok' : status === 'error' ? 'error' : 'pending')

  if (setup.error) {
    elements.title.textContent = '启动没有完成'
    elements.subtitle.textContent = '请根据下方提示处理后重试；已完成的步骤不会重复执行。'
  } else if (running) {
    elements.title.textContent = '本地后端已就绪'
    elements.subtitle.textContent =
      status === 'external'
        ? `已连接外部后端（端口 ${backend.port}）。桌面版不会停止或重启该进程。`
        : `服务运行在 http://127.0.0.1:${backend.port}/，你可以打开控制台开始管理。`
  } else if (setup.running || status === 'starting') {
    elements.title.textContent = '正在启动 AI 群友'
    elements.subtitle.textContent = '首次启动可能需要安装依赖或构建界面，请保持窗口打开。'
  } else {
    elements.title.textContent = '欢迎使用 AI 群友'
    elements.subtitle.textContent = '桌面版会检查本地依赖并启动后端；所有数据只保存在这台电脑上。'
  }

  renderSteps(setup.steps)
  renderNotice()

  elements.demoWrap.hidden = running || setup.running
  elements.primary.disabled = busy || setup.running || status === 'starting' || status === 'stopping'

  if (running || (setup.warning && backend.port)) {
    elements.primary.textContent = busy ? '正在打开…' : '打开控制台'
  } else if (setup.running || status === 'starting') {
    elements.primary.textContent = '正在准备…'
  } else if (busy) {
    elements.primary.textContent = '正在启动…'
  } else if (setup.error) {
    elements.primary.textContent = '重试'
  } else {
    elements.primary.textContent = '启动 AI 群友'
  }
}

function applyState(next) {
  state = next
  if (Array.isArray(next.logs)) {
    logs = next.logs.map((entry) => `[${entry.source === 'backend' ? '后端' : '向导'}] ${entry.line}`)
    renderLogs()
  }
  render()
}

async function onPrimary() {
  if (!bridge) return
  if (backendRunning() || (state?.setup?.warning && state?.backend?.port)) {
    busy = true
    render()
    try {
      await bridge.openConsole()
    } catch (error) {
      showTransientError(error)
    } finally {
      busy = false
      render()
    }
    return
  }
  busy = true
  state = {
    ...state,
    setup: { ...(state?.setup ?? {}), error: '', warning: '', running: true },
  }
  render()
  try {
    await bridge.startBackend({ demo: Boolean(elements.demo.checked) })
  } catch (error) {
    showTransientError(error)
  } finally {
    busy = false
    render()
  }
}

function showTransientError(error) {
  const message = error instanceof Error ? error.message : String(error)
  appendLog({ source: 'setup', line: `操作失败：${message}` })
  elements.notice.hidden = false
  elements.notice.classList.add('error')
  elements.noticeText.textContent = message
  elements.noticeAction.hidden = true
}

async function openFolder(kind) {
  try {
    await bridge?.openFolder(kind)
  } catch (error) {
    showTransientError(error)
  }
}

elements.primary.addEventListener('click', onPrimary)
elements.openLog.addEventListener('click', () => openFolder('logs'))
elements.openData.addEventListener('click', () => openFolder('data'))
elements.quit.addEventListener('click', () => bridge?.quit())
elements.clearLog.addEventListener('click', () => {
  logs = []
  renderLogs()
})
elements.noticeAction.addEventListener('click', () => {
  bridge?.openConsole().catch(showTransientError)
})

if (!bridge) {
  elements.title.textContent = '无法连接桌面进程'
  elements.subtitle.textContent = '请从 start-desktop.cmd 启动，或检查 preload 是否加载成功。'
  elements.primary.disabled = true
  elements.demoWrap.hidden = true
  appendLog({ source: 'setup', line: '未检测到桌面桥接接口（window.aiGroupFriendDesktop）。' })
} else {
  bridge.onState(applyState)
  bridge.onSetupProgress((setup) => {
    if (!state) return
    state = { ...state, setup }
    render()
  })
  bridge.onLog((entry) => appendLog(entry))
  bridge
    .getInfo()
    .then(applyState)
    .catch((error) => {
      showTransientError(error)
    })
  render()
}
