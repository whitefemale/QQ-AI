'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const source = fs.readFileSync(path.resolve(__dirname, '..', 'preload.js'), 'utf8')

test('preload 只暴露白名单方法，不暴露 ipcRenderer/fs/child_process', () => {
  assert.match(source, /chooseConnectorsDir:\s*\(\)\s*=>\s*ipcRenderer\.invoke\('desktop:choose-connectors-dir'\)/u)
  assert.match(source, /openFolder:\s*\(kind\)\s*=>\s*ipcRenderer\.invoke\('desktop:open-folder', kind\)/u)
  const exposed = source.slice(source.indexOf('exposeInMainWorld('))
  assert.equal(exposed.includes('ipcRenderer:'), false)
  assert.equal(exposed.includes('fs:'), false)
  assert.equal(exposed.includes('child_process:'), false)
  assert.equal(/\brequire\('node:fs'\)|\brequire\('node:child_process'\)/u.test(source), false)
})
