'use strict'

const assert = require('node:assert/strict')
const net = require('node:net')
const test = require('node:test')

const { findFreePort, isPortFree } = require('../lib/ports')

function listenOnRandomPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', reject)
    server.listen({ port: 0, host: '127.0.0.1', exclusive: true }, () => {
      resolve({ server, port: server.address().port })
    })
  })
}

function closeServer(server) {
  return new Promise((resolve) => server.close(() => resolve()))
}

test('能识别已占用与空闲端口', async (t) => {
  const { server, port } = await listenOnRandomPort()
  t.after(() => closeServer(server))

  assert.equal(await isPortFree(port), false)
  const { server: spare, port: sparePort } = await listenOnRandomPort()
  await closeServer(spare)
  assert.equal(await isPortFree(sparePort), true)
})

test('findFreePort 会跳过被占用的端口', async (t) => {
  const { server, port } = await listenOnRandomPort()
  t.after(() => closeServer(server))

  const free = await findFreePort(port)
  assert.notEqual(free, port)
  assert.ok(free > port)
  assert.equal(await isPortFree(free), true)
})
