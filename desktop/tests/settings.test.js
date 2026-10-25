'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')

const {
  DEFAULT_SETTINGS,
  SettingsStore,
  normalizeSettings,
  validatePatch,
} = require('../lib/settings')

function tempSettingsPath() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'aiqf-settings-'))
  return path.join(dir, 'settings.json')
}

test('默认设置包含自动启动与关闭到托盘', () => {
  assert.deepEqual(normalizeSettings(null), { ...DEFAULT_SETTINGS })
  assert.equal(DEFAULT_SETTINGS.autoStartBackend, true)
  assert.equal(DEFAULT_SETTINGS.closeToTray, true)
  assert.equal(DEFAULT_SETTINGS.dataDir, '')
})

test('设置原子写入并可重新加载', () => {
  const filePath = tempSettingsPath()
  const store = new SettingsStore(filePath)
  assert.deepEqual(store.load(), { ...DEFAULT_SETTINGS })

  const updated = store.update({ closeToTray: false, dataDir: '  D:\\data\\aiqf  ' })
  assert.equal(updated.closeToTray, false)
  assert.equal(updated.dataDir, 'D:\\data\\aiqf')

  const reloaded = new SettingsStore(filePath)
  assert.deepEqual(reloaded.load(), updated)
  assert.equal(fs.existsSync(`${filePath}.${process.pid}.tmp`), false)
  assert.doesNotThrow(() => JSON.parse(fs.readFileSync(filePath, 'utf8')))
})

test('非法设置字段与类型被拒绝', () => {
  assert.throws(() => validatePatch({ unknown: true }), /不支持的设置项/u)
  assert.throws(() => validatePatch({ closeToTray: 'yes' }), /必须是布尔值/u)
  assert.throws(() => validatePatch({ dataDir: 42 }), /必须是字符串/u)
  assert.throws(() => validatePatch(null), /必须是对象/u)
  assert.deepEqual(validatePatch({ showWindowOnStart: false }), { showWindowOnStart: false })
})

test('损坏的设置文件回退到默认值，非法类型被忽略', () => {
  const filePath = tempSettingsPath()
  fs.writeFileSync(filePath, '{not-json', 'utf8')
  assert.deepEqual(new SettingsStore(filePath).load(), { ...DEFAULT_SETTINGS })

  assert.deepEqual(normalizeSettings({ closeToTray: 'no', dataDir: 7 }), { ...DEFAULT_SETTINGS })
  assert.deepEqual(normalizeSettings({ autoStartBackend: false }), {
    ...DEFAULT_SETTINGS,
    autoStartBackend: false,
  })
})
