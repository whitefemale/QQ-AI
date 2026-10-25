'use strict'

const fs = require('node:fs')
const path = require('node:path')

function timestamp() {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(
    now.getMinutes(),
  )}:${pad(now.getSeconds())}`
}

/**
 * 简单的桌面端日志：写入 userData/logs/desktop.log，同时在内存保留最近若干行。
 * 不记录 API Key、Token 或完整环境变量。
 */
function createLogger(logDir, { fsImpl = fs, maxLines = 300 } = {}) {
  const logPath = path.join(logDir, 'desktop.log')
  const buffer = []
  try {
    fsImpl.mkdirSync(logDir, { recursive: true })
  } catch {
    /* 日志目录不可写时不阻止应用启动 */
  }

  function push(level, message) {
    const line = `[${timestamp()}] [${level}] ${String(message).replace(/\s+$/u, '')}`
    buffer.push(line)
    if (buffer.length > maxLines) buffer.shift()
    try {
      fsImpl.appendFileSync(logPath, `${line}\n`, 'utf8')
    } catch {
      /* 忽略日志写入失败 */
    }
    return line
  }

  return {
    logPath,
    info: (message) => push('INFO', message),
    warn: (message) => push('WARN', message),
    error: (message) => push('ERROR', message),
    lines: () => buffer.slice(),
  }
}

module.exports = { createLogger }
