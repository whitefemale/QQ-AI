'use strict'

const assert = require('node:assert/strict')
const test = require('node:test')

const pkg = require('../package.json')

// 这些断言只校验 electron-builder 的静态配置值。
// 它们不执行 NSIS 安装器，也不证明真实升级、回滚或卸载行为。
test('NSIS 配置保持可交互安装、per-user 且卸载保留用户数据', () => {
  const build = pkg.build
  const nsis = build.nsis
  const target = build.win.target[0]

  assert.equal(target.target, 'nsis')
  assert.deepEqual(target.arch, ['x64'])
  assert.equal(nsis.oneClick, false)
  assert.equal(nsis.perMachine, false)
  assert.equal(nsis.allowToChangeInstallationDirectory, true)
  assert.equal(nsis.deleteAppDataOnUninstall, false)
  assert.equal(build.directories.output, '../release')
  assert.match(build.win.artifactName, /\$\{version\}/u)
  assert.match(build.win.artifactName, /\$\{arch\}/u)
  assert.match(build.win.artifactName, /\.\$\{ext\}$/u)
})
