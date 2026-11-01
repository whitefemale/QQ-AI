'use strict'

const assert = require('node:assert/strict')
const http = require('node:http')
const os = require('node:os')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const { BackendManager } = require('../lib/backend')

function startHealthServer() {
  return new Promise((resolve, reject) => {
    const server = http.createServer((request, response) => {
      if (request.url === '/api/health') {
        response.writeHead(200, { 'Content-Type': 'application/json' })
        response.end(JSON.stringify({ data: { status: 'ok', app: 'AI 群友', version: '0.1.0' } }))
        return
      }
      response.writeHead(404)
      response.end()
    })
    server.once('error', reject)
    server.listen({ port: 0, host: '127.0.0.1' }, () => {
      resolve({ server, port: server.address().port })
    })
  })
}

function closeServer(server) {
  server.closeAllConnections?.()
  return new Promise((resolve) => server.close(() => resolve()))
}

function makeManager({ port, spawnImpl, dataDir, ...options }) {
  return new BackendManager({
    repoRoot: path.resolve(__dirname, '..', '..'),
    backendDir: path.resolve(__dirname, '..', '..', 'backend'),
    pythonPath: 'unused-python',
    dataDir,
    logger: null,
    preferredPort: port,
    spawnImpl,
    startupTimeoutMs: 3000,
    ...options,
  })
}

test('8000 端口已有本项目后端时直接连接，不启动第二个进程', async (t) => {
  const { server, port } = await startHealthServer()
  t.after(() => closeServer(server))
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aiqf-backend-'))
  let spawnCalled = false
  const manager = makeManager({
    port,
    dataDir,
    spawnImpl: () => {
      spawnCalled = true
      throw new Error('不应启动新进程')
    },
  })

  const info = await manager.start()
  assert.equal(spawnCalled, false)
  assert.equal(info.status, 'external')
  assert.equal(info.port, port)
  assert.equal(info.managed, false)
  assert.equal(info.version, '0.1.0')

  await assert.rejects(() => manager.restart(), /外部后端/u)
  await manager.stop()
  assert.equal(manager.getInfo().status, 'stopped')
  assert.equal(server.listening, true)
})

test('健康检查失败时会结束进程并进入错误状态', async (t) => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aiqf-backend-'))
  const fakeChild = {
    pid: 4242,
    stdout: null,
    stderr: null,
    kill() {
      this.killed = true
      this.exitCallback?.(null, 'SIGTERM')
    },
    once(event, callback) {
      if (event === 'exit') this.exitCallback = callback
    },
    on() {},
  }
  const manager = new BackendManager({
    repoRoot: path.resolve(__dirname, '..', '..'),
    backendDir: path.resolve(__dirname, '..', '..', 'backend'),
    pythonPath: 'unused-python',
    dataDir,
    logger: null,
    preferredPort: 5999,
    spawnImpl: () => fakeChild,
    fetchImpl: async () => {
      throw new Error('connection refused')
    },
    startupTimeoutMs: 250,
    killTimeoutMs: 500,
  })
  // 避免测试依赖 5999 端口是否空闲：占用时 findFreePort 会改用其他端口，行为一致。
  await assert.rejects(() => manager.start(), /后端启动失败/u)
  assert.equal(fakeChild.killed, true)
  assert.equal(manager.getInfo().status, 'error')
  await manager.stop()
  t.after(() => {
    /* 假进程无需清理 */
  })
})

test('外部后端运行期间持续健康探测，stop 时清理定时器且不停止外部进程', async (t) => {
  const { server, port } = await startHealthServer()
  t.after(() => closeServer(server))
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aiqf-backend-'))
  const timers = []
  const cleared = []
  let clock = 1000
  let probeCalls = 0
  const manager = makeManager({
    port,
    dataDir,
    healthProbe: async () => {
      probeCalls += 1
      return true
    },
    setIntervalImpl: (fn, ms) => {
      const handle = { fn, ms, unref() {} }
      timers.push(handle)
      return handle
    },
    clearIntervalImpl: (handle) => cleared.push(handle),
    now: () => {
      clock += 10
      return clock
    },
  })

  await manager.start()
  assert.equal(manager.getInfo().status, 'external')
  assert.equal(timers.length, 1)
  assert.equal(timers[0].ms, 12000)
  assert.equal(manager.getInfo().health.state, 'unknown')

  const healthy = await manager.checkHealth()
  assert.equal(probeCalls, 1)
  assert.equal(healthy.status, 'external')
  assert.equal(healthy.health.state, 'healthy')
  assert.equal(healthy.health.consecutiveFailures, 0)
  assert.equal(healthy.health.latencyMs, 10)
  assert.ok(healthy.health.lastCheckAt)

  const copy = manager.getInfo()
  copy.health.state = 'degraded'
  copy.health.consecutiveFailures = 99
  assert.equal(manager.getInfo().health.state, 'healthy')
  assert.equal(manager.getInfo().health.consecutiveFailures, 0)

  await manager.stop()
  assert.equal(cleared.length, 1)
  assert.equal(manager.getInfo().health.state, 'unknown')
  assert.equal(server.listening, true)
})

test('前两次健康失败不改状态，第三次降级，恢复后立即正常且不改变后端状态', async (t) => {
  const { server, port } = await startHealthServer()
  t.after(() => closeServer(server))
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aiqf-backend-'))
  let healthy = true
  const manager = makeManager({
    port,
    dataDir,
    healthProbe: async () => healthy,
    setIntervalImpl: () => ({ unref() {} }),
    clearIntervalImpl: () => {},
  })

  await manager.start()
  await manager.checkHealth()
  assert.equal(manager.getInfo().health.state, 'healthy')

  healthy = false
  await manager.checkHealth()
  let info = manager.getInfo()
  assert.equal(info.status, 'external')
  assert.equal(info.health.state, 'healthy')
  assert.equal(info.health.consecutiveFailures, 1)
  assert.match(info.health.message, /1 次/u)

  await manager.checkHealth()
  info = manager.getInfo()
  assert.equal(info.status, 'external')
  assert.equal(info.health.state, 'healthy')
  assert.equal(info.health.consecutiveFailures, 2)

  await manager.checkHealth()
  info = manager.getInfo()
  assert.equal(info.status, 'external')
  assert.equal(info.health.state, 'degraded')
  assert.equal(info.health.consecutiveFailures, 3)
  assert.match(info.health.message, /连续 3 次/u)

  healthy = true
  info = await manager.checkHealth()
  assert.equal(info.status, 'external')
  assert.equal(info.health.state, 'healthy')
  assert.equal(info.health.consecutiveFailures, 0)
  assert.equal(info.health.message, '')

  await manager.stop()
  assert.equal(server.listening, true)
})

test('重叠的健康探测会跳过，不会堆积请求', async (t) => {
  const { server, port } = await startHealthServer()
  t.after(() => closeServer(server))
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aiqf-backend-'))
  let release
  let probeCalls = 0
  const manager = makeManager({
    port,
    dataDir,
    healthProbe: () => {
      probeCalls += 1
      return new Promise((resolve) => {
        release = resolve
      })
    },
    setIntervalImpl: () => ({ unref() {} }),
    clearIntervalImpl: () => {},
  })

  await manager.start()
  const first = manager.checkHealth()
  const second = await manager.checkHealth()
  assert.equal(probeCalls, 1)
  assert.equal(second.health.state, 'unknown')

  release(true)
  const firstInfo = await first
  assert.equal(firstInfo.health.state, 'healthy')
  await manager.stop()
})
