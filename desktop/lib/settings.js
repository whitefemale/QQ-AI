'use strict'

/** 桌面版设置的默认值。设置只保存在 Electron userData 中，不入数据库、不上传。 */
const DEFAULT_SETTINGS = Object.freeze({
  autoStartBackend: true,
  closeToTray: true,
  showWindowOnStart: true,
  firstRunCompleted: false,
  dataDir: '',
})

const BOOLEAN_KEYS = ['autoStartBackend', 'closeToTray', 'showWindowOnStart', 'firstRunCompleted']
const ALLOWED_KEYS = new Set([...BOOLEAN_KEYS, 'dataDir'])
const MAX_DATA_DIR_LENGTH = 1000

function normalizeSettings(raw) {
  const source = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}
  const result = { ...DEFAULT_SETTINGS }
  for (const key of BOOLEAN_KEYS) {
    if (typeof source[key] === 'boolean') result[key] = source[key]
  }
  if (typeof source.dataDir === 'string' && source.dataDir.length <= MAX_DATA_DIR_LENGTH) {
    result.dataDir = source.dataDir.trim()
  }
  return result
}

/** 校验来自渲染进程的局部更新；未知字段与非法类型直接拒绝。 */
function validatePatch(patch) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) {
    throw new Error('设置更新必须是对象。')
  }
  const clean = {}
  for (const [key, value] of Object.entries(patch)) {
    if (!ALLOWED_KEYS.has(key)) {
      throw new Error(`不支持的设置项：${key}`)
    }
    if (key === 'dataDir') {
      if (typeof value !== 'string') throw new Error('dataDir 必须是字符串。')
      if (value.length > MAX_DATA_DIR_LENGTH) throw new Error('dataDir 过长。')
      clean[key] = value.trim()
    } else {
      if (typeof value !== 'boolean') throw new Error(`${key} 必须是布尔值。`)
      clean[key] = value
    }
  }
  return clean
}

class SettingsStore {
  /** @param {string} filePath @param {typeof import('node:fs')} [fsImpl] */
  constructor(filePath, fsImpl = require('node:fs')) {
    this.filePath = filePath
    this.fs = fsImpl
    this.current = null
  }

  load() {
    if (this.current) return { ...this.current }
    let raw = null
    try {
      raw = JSON.parse(this.fs.readFileSync(this.filePath, 'utf8'))
    } catch {
      raw = null
    }
    this.current = normalizeSettings(raw)
    return { ...this.current }
  }

  update(patch) {
    const clean = validatePatch(patch)
    const next = normalizeSettings({ ...this.load(), ...clean })
    this.write(next)
    this.current = next
    return { ...next }
  }

  write(settings) {
    const path = require('node:path')
    const dir = path.dirname(this.filePath)
    this.fs.mkdirSync(dir, { recursive: true })
    const tmp = `${this.filePath}.${process.pid}.tmp`
    this.fs.writeFileSync(tmp, `${JSON.stringify(settings, null, 2)}\n`, 'utf8')
    try {
      this.fs.renameSync(tmp, this.filePath)
    } catch {
      // Windows 上目标文件被占用时 rename 可能失败，退化为覆盖写。
      try {
        this.fs.unlinkSync(this.filePath)
      } catch {
        /* 目标不存在时忽略 */
      }
      this.fs.renameSync(tmp, this.filePath)
    }
  }
}

module.exports = {
  DEFAULT_SETTINGS,
  SettingsStore,
  normalizeSettings,
  validatePatch,
}
