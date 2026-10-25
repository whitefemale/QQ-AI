'use strict'

const { EventEmitter } = require('node:events')
const { execFile, spawn } = require('node:child_process')

const { findFreePort, isPortFree } = require('./ports')
const { buildBackendEnv } = require('./backend-env')
const { probeExistingBackend, waitForHealth } = require('./health')

const MAX_LOG_LINES = 240

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * 管理本地 uvicorn 子进程。
 *
 * 若 8000 上已经有本项目后端（例如用户手工启动），则直接连接它，不再启动第二个
 * 进程，避免两个进程同时写同一个 SQLite 数据库。外部后端不会被本应用停止。
 */
class BackendManager extends EventEmitter {
  constructor({
    repoRoot,
    backendDir,
    pythonPath,
    dataDir,
    logger,
    envBase = process.env,
    spawnImpl = spawn,
    execFileImpl = execFile,
    fetchImpl = globalThis.fetch,
    preferredPort = 8000,
    startupTimeoutMs = 60000,
    killTimeoutMs = 6000,
    maxLogLines = MAX_LOG_LINES,
  }) {
    super()
    this.repoRoot = repoRoot
    this.backendDir = backendDir
    this.pythonPath = pythonPath
    this.dataDir = dataDir
    this.logger = logger
    this.envBase = envBase
    this.spawnImpl = spawnImpl
    this.execFileImpl = execFileImpl
    this.fetchImpl = fetchImpl
    this.preferredPort = preferredPort
    this.startupTimeoutMs = startupTimeoutMs
    this.killTimeoutMs = killTimeoutMs
    this.maxLogLines = maxLogLines

    this.child = null
    this._exitPromise = null
    this._stopRequested = false
    this._starting = null
    this._logs = []
    this.info = {
      status: 'stopped',
      port: null,
      pid: null,
      managed: true,
      version: '',
      error: '',
    }
  }

  getInfo() {
    return { ...this.info }
  }

  tail(count = 40) {
    return this._logs.slice(-count)
  }

  _set(patch) {
    this.info = { ...this.info, ...patch }
    this.emit('state', this.getInfo())
  }

  _appendLog(line) {
    const text = line.replace(/\r$/u, '')
    if (!text) return
    this._logs.push(text)
    if (this._logs.length > this.maxLogLines) this._logs.shift()
    if (this.logger) this.logger.info(`[backend] ${text}`)
    this.emit('log', text)
  }

  _wireOutput(stream) {
    let pending = ''
    stream.setEncoding('utf8')
    stream.on('data', (chunk) => {
      pending += chunk
      const lines = pending.split(/\r?\n/u)
      pending = lines.pop() ?? ''
      for (const line of lines) this._appendLog(line)
    })
    stream.on('end', () => {
      if (pending) this._appendLog(pending)
      pending = ''
    })
    stream.on('error', (error) => this._appendLog(`日志流读取失败：${error.message}`))
  }

  async _choosePort() {
    const existing = await probeExistingBackend({
      port: this.preferredPort,
      fetchImpl: this.fetchImpl,
    })
    if (existing && existing.matches) {
      this._set({
        status: 'external',
        port: existing.port,
        pid: null,
        managed: false,
        version: existing.version,
        error: '',
      })
      this._appendLog(`检测到已有后端，已连接 http://127.0.0.1:${existing.port}（不会停止该进程）。`)
      return { external: true, port: existing.port }
    }
    if (await isPortFree(this.preferredPort)) {
      return { external: false, port: this.preferredPort }
    }
    const port = await findFreePort(this.preferredPort + 1)
    this._appendLog(`端口 ${this.preferredPort} 已被占用，改用 ${port}。`)
    return { external: false, port }
  }

  async start() {
    if (this.info.status === 'running' || this.info.status === 'external') return this.getInfo()
    if (this._starting) return this._starting

    this._starting = this._startInternal().finally(() => {
      this._starting = null
    })
    return this._starting
  }

  async _startInternal() {
    this._stopRequested = false
    this._set({ status: 'starting', error: '', version: '' })

    const choice = await this._choosePort()
    if (choice.external) return this.getInfo()

    const port = choice.port
    this._set({ port, managed: true, pid: null })
    const env = buildBackendEnv({
      baseEnv: this.envBase,
      repoRoot: this.repoRoot,
      dataDir: this.dataDir,
      port,
    })
    const args = [
      '-m',
      'uvicorn',
      'app.main:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
      '--log-level',
      'info',
    ]
    this._appendLog(`启动后端：${this.pythonPath} ${args.join(' ')}`)
    this._appendLog(`数据目录：${this.dataDir}`)

    let child
    try {
      child = this.spawnImpl(this.pythonPath, args, {
        cwd: this.backendDir,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      })
    } catch (error) {
      this._set({ status: 'error', error: `无法启动 Python：${error.message}` })
      throw new Error(this.info.error)
    }

    this.child = child
    this._set({ pid: child.pid ?? null })
    this._exitPromise = new Promise((resolve) => {
      child.once('exit', (code, signal) => resolve({ code, signal }))
    })

    if (child.stdout) this._wireOutput(child.stdout)
    if (child.stderr) this._wireOutput(child.stderr)
    child.on('error', (error) => {
      this._appendLog(`后端进程错误：${error.message}`)
      if (this.info.status === 'starting') {
        this._set({ status: 'error', error: `后端进程错误：${error.message}` })
      }
    })
    child.once('exit', (code, signal) => {
      const wasStopping = this._stopRequested
      this.child = null
      this._appendLog(`后端进程已退出（code=${code ?? 'null'}, signal=${signal ?? 'null'}）。`)
      if (wasStopping) {
        this._set({ status: 'stopped', pid: null, port: null, version: '', managed: true })
      } else if (this.info.status !== 'error') {
        const reason =
          code === 0
            ? '后端已退出。'
            : `后端异常退出（code=${code ?? signal ?? '未知'}）。请查看下方日志。`
        this._set({ status: 'error', error: reason, pid: null })
      }
    })

    const result = await waitForHealth({
      port,
      timeoutMs: this.startupTimeoutMs,
      fetchImpl: this.fetchImpl,
      isCancelled: () => this._stopRequested || this.info.status === 'error',
    })
    if (!result.ok) {
      const tail = this.tail(8).join('\n')
      await this.stop()
      this._set({
        status: 'error',
        error: `${result.error ?? '后端启动超时。'}${tail ? `\n${tail}` : ''}`,
      })
      throw new Error(`后端启动失败：${result.error ?? '未知错误'}`)
    }

    this._set({
      status: 'running',
      port,
      managed: true,
      version: result.version || '',
      error: '',
    })
    this._appendLog(`后端已就绪：http://127.0.0.1:${port}/`)
    return this.getInfo()
  }

  async _waitExit(timeoutMs) {
    if (!this._exitPromise) return true
    return Promise.race([
      this._exitPromise.then(() => true),
      sleep(timeoutMs).then(() => false),
    ])
  }

  async _forceKill(pid) {
    if (process.platform === 'win32') {
      await new Promise((resolve) => {
        this.execFileImpl('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true }, () =>
          resolve(),
        )
      })
      return
    }
    try {
      process.kill(pid, 'SIGKILL')
    } catch {
      /* 进程可能已经退出 */
    }
  }

  async stop() {
    if (this.info.status === 'external') {
      this._appendLog('已断开外部后端连接（进程保持运行）。')
      this._set({ status: 'stopped', port: null, pid: null, version: '', managed: true })
      return this.getInfo()
    }
    const child = this.child
    if (!child) {
      if (this.info.status !== 'starting') {
        this._set({ status: 'stopped', port: null, pid: null, version: '', managed: true })
      }
      return this.getInfo()
    }

    this._stopRequested = true
    const pid = child.pid
    this._set({ status: 'stopping' })
    this._appendLog('正在停止后端…')
    try {
      child.kill()
    } catch {
      /* 忽略重复停止 */
    }
    const exited = await this._waitExit(this.killTimeoutMs)
    if (!exited && pid) {
      this._appendLog('后端未在超时内退出，尝试结束进程树。')
      await this._forceKill(pid)
      await this._waitExit(3000)
    }
    this.child = null
    this._exitPromise = null
    this._stopRequested = false
    this._set({ status: 'stopped', port: null, pid: null, version: '', managed: true })
    return this.getInfo()
  }

  async restart() {
    if (this.info.status === 'external') {
      throw new Error('当前连接的是外部后端，请先在启动它的终端中停止，再重启桌面版。')
    }
    await this.stop()
    return this.start()
  }

  async dispose() {
    return this.stop()
  }
}

module.exports = { BackendManager }
