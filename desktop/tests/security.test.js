'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const root = path.resolve(__dirname, '..')
const mainSource = fs.readFileSync(path.join(root, 'main.js'), 'utf8')
const shellHtml = fs.readFileSync(path.join(root, 'shell', 'index.html'), 'utf8')

test('窗口 webPreferences 显式开启隔离并禁止不安全内容', () => {
  assert.match(mainSource, /contextIsolation:\s*true/u)
  assert.match(mainSource, /nodeIntegration:\s*false/u)
  assert.match(mainSource, /sandbox:\s*true/u)
  assert.match(mainSource, /webSecurity:\s*true/u)
  assert.match(mainSource, /allowRunningInsecureContent:\s*false/u)
})

test('默认会话仅允许剪贴板写入，拒绝其他权限与设备', () => {
  assert.match(mainSource, /const ALLOWED_PERMISSIONS = new Set\(\['clipboard-sanitized-write'\]\)/u)
  assert.match(mainSource, /setPermissionRequestHandler\(/u)
  assert.match(mainSource, /setPermissionCheckHandler\(/u)
  assert.match(mainSource, /setDevicePermissionHandler\(\(\) => false\)/u)
  assert.match(mainSource, /callback\(ALLOWED_PERMISSIONS\.has\(permission\)\)/u)
  assert.match(mainSource, /hardenSession\(session\.defaultSession\)/u)
  // 不允许出现无条件放行或媒介设备权限。
  assert.equal(/setPermissionRequestHandler\([^)]*callback\(true\)/u.test(mainSource), false)
  assert.equal(/media|geolocation|notifications|midi|fullscreen/u.test(
    mainSource.slice(mainSource.indexOf('ALLOWED_PERMISSIONS'), mainSource.indexOf('function hardenSession')),
  ), false)
})

test('阻止 webview 附加，导航仍受白名单约束', () => {
  assert.match(mainSource, /on\('will-attach-webview',\s*\(event\)\s*=>\s*\{\s*event\.preventDefault\(\)/u)
  assert.match(mainSource, /on\('will-navigate',\s*\(event, url\)\s*=>\s*\{\s*if \(!isAllowedNavigation\(url\)\) event\.preventDefault\(\)/u)
  assert.match(mainSource, /on\('will-redirect',\s*\(event, url\)\s*=>\s*\{\s*if \(!isAllowedNavigation\(url\)\) event\.preventDefault\(\)/u)
})

test('启动控制页带有严格 CSP，且禁止网络连接与内联脚本', () => {
  assert.match(shellHtml, /http-equiv="Content-Security-Policy"/u)
  assert.match(shellHtml, /default-src 'self'/u)
  assert.match(shellHtml, /script-src 'self'/u)
  assert.match(shellHtml, /connect-src 'none'/u)
  assert.match(shellHtml, /object-src 'none'/u)
  assert.match(shellHtml, /base-uri 'none'/u)
  assert.match(shellHtml, /form-action 'none'/u)
  assert.equal(/script-src[^;]*'unsafe-inline'/u.test(shellHtml), false)
})
