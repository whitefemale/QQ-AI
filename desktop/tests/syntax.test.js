'use strict'

const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const desktopDir = path.resolve(__dirname, '..')

function collectJavaScript(dir) {
  const files = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name)
    if (entry.isDirectory()) files.push(...collectJavaScript(fullPath))
    else if (entry.name.endsWith('.js')) files.push(fullPath)
  }
  return files
}

test('Windows 启动脚本保留 PowerShell UTF-8 BOM 与 CMD 的 CRLF', () => {
  const repoRoot = path.resolve(desktopDir, '..')
  for (const name of ['launch_desktop.ps1', 'check.ps1', 'dev.ps1', 'backup.ps1']) {
    const bytes = fs.readFileSync(path.join(repoRoot, 'scripts', name))
    assert.deepEqual(
      [...bytes.subarray(0, 3)],
      [0xef, 0xbb, 0xbf],
      `${name} 需要 UTF-8 BOM，否则 PowerShell 5.1 会按 ANSI 解析中文并报语法错误`,
    )
  }

  const cmd = fs.readFileSync(path.join(repoRoot, 'start-desktop.cmd'), 'utf8')
  assert.ok(cmd.includes('\r\n'), 'start-desktop.cmd 需要 CRLF 行尾')
  assert.equal(/(^|[^\r])\n/u.test(cmd), false, 'start-desktop.cmd 不能包含单独的 LF 行尾')
})

test('主进程、preload、控制页与 lib 脚本均可被 Node 解析', () => {
  const files = [
    path.join(desktopDir, 'main.js'),
    path.join(desktopDir, 'preload.js'),
    ...collectJavaScript(path.join(desktopDir, 'lib')),
    ...collectJavaScript(path.join(desktopDir, 'shell')),
  ]
  assert.ok(files.length >= 10)
  for (const file of files) {
    assert.doesNotThrow(
      () => execFileSync(process.execPath, ['--check', file], { stdio: 'pipe' }),
      `${path.relative(desktopDir, file)} 存在语法错误`,
    )
  }
})
