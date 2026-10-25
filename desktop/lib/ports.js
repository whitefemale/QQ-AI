'use strict'

const net = require('node:net')

const HOST = '127.0.0.1'

/** 尝试监听指定端口，确认是否可用。 */
function isPortFree(port, host = HOST) {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.unref()
    server.once('error', () => resolve(false))
    server.listen({ port, host, exclusive: true }, () => {
      server.close(() => resolve(true))
    })
  })
}

async function findFreePort(preferred = 8000, host = HOST) {
  for (let port = preferred; port < preferred + 20; port += 1) {
    if (await isPortFree(port, host)) return port
  }
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.once('error', reject)
    server.listen({ port: 0, host, exclusive: true }, () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : null
      server.close(() => {
        if (port) resolve(port)
        else reject(new Error('无法分配本地端口。'))
      })
    })
  })
}

module.exports = { HOST, isPortFree, findFreePort }
