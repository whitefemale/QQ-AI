'use strict'

const assert = require('node:assert/strict')
const http = require('node:http')
const test = require('node:test')

const { probeExistingBackend, readHealth, waitForHealth } = require('../lib/health')

function startServer(handler) {
  return new Promise((resolve, reject) => {
    const server = http.createServer(handler)
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

test('读取健康检查成功并识别本项目', async (t) => {
  const { server, port } = await startServer((request, response) => {
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ data: { status: 'ok', app: 'AI 群友', version: '0.1.0' } }))
  })
  t.after(() => closeServer(server))

  const health = await readHealth(port)
  assert.equal(health.status, 'ok')
  assert.equal(health.version, '0.1.0')

  const probe = await probeExistingBackend({ port })
  assert.equal(probe.matches, true)
  assert.equal(probe.port, port)
})

test('非 JSON、异常状态与其他应用均返回 null', async (t) => {
  const { server, port } = await startServer((request, response) => {
    if (request.url === '/bad-json') {
      response.writeHead(200, { 'Content-Type': 'text/plain' })
      response.end('not-json')
      return
    }
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ data: { status: 'ok', app: '另一个应用' } }))
  })
  t.after(() => closeServer(server))

  assert.equal((await probeExistingBackend({ port })).matches, false)

  const other = await startServer((request, response) => {
    response.writeHead(500, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ data: { status: 'ok' } }))
  })
  t.after(() => closeServer(other.server))
  assert.equal(await readHealth(other.port), null)

  const bad = await startServer((request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/plain' })
    response.end('not-json')
  })
  t.after(() => closeServer(bad.server))
  assert.equal(await readHealth(bad.port), null)
})

test('超时返回 null 而不是抛出', async (t) => {
  const { server, port } = await startServer(() => {
    /* 故意不响应 */
  })
  t.after(() => closeServer(server))

  const health = await readHealth(port, { timeoutMs: 120 })
  assert.equal(health, null)
})

test('waitForHealth 轮询直到成功，并支持取消', async () => {
  let attempts = 0
  const fetchImpl = async () => {
    attempts += 1
    if (attempts < 3) {
      return { ok: false, json: async () => ({}) }
    }
    return { ok: true, json: async () => ({ data: { status: 'ok', version: '9.9.9' } }) }
  }
  const result = await waitForHealth({
    port: 8000,
    timeoutMs: 5000,
    intervalMs: 1,
    fetchImpl,
    sleep: async () => {},
  })
  assert.equal(result.ok, true)
  assert.equal(result.version, '9.9.9')
  assert.equal(attempts, 3)

  const cancelled = await waitForHealth({
    port: 8000,
    timeoutMs: 5000,
    fetchImpl: async () => ({ ok: false, json: async () => ({}) }),
    sleep: async () => {},
    isCancelled: () => true,
  })
  assert.equal(cancelled.ok, false)
  assert.equal(cancelled.cancelled, true)
})
