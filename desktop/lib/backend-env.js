'use strict'

const path = require('node:path')

const DB_FILENAME = 'ai_group_friend.db'

/** sqlite+aiosqlite URL 使用正斜杠；Windows 盘符形式为 sqlite+aiosqlite:///D:/... */
function sqliteUrl(dbPath) {
  const normalized = path.resolve(dbPath).replace(/\\/g, '/')
  return `sqlite+aiosqlite:///${normalized}`
}

/**
 * 构造后端子进程环境。显式传入绝对路径，避免 .env 中相对 DATABASE_URL
 * 随工作目录漂移；不覆盖密钥等由 .env 提供的配置。
 */
function buildBackendEnv({ baseEnv = process.env, repoRoot, dataDir, port }) {
  // 相对目录以仓库根为基准解析，避免依赖 Electron 进程的当前工作目录。
  const resolvedDataDir = path.resolve(repoRoot, dataDir)
  const databaseUrl = sqliteUrl(path.join(resolvedDataDir, DB_FILENAME))
  return {
    ...baseEnv,
    APP_HOST: '127.0.0.1',
    APP_PORT: String(port),
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    DATA_DIR: resolvedDataDir,
    DATABASE_URL: databaseUrl,
    FRONTEND_DIST: path.join(repoRoot, 'frontend', 'dist'),
    AUTO_MIGRATE: 'true',
    // 桌面窗口与后端同源，不需要开发期 Vite 来源；保留 .env 的值也无害。
  }
}

module.exports = { DB_FILENAME, sqliteUrl, buildBackendEnv }
