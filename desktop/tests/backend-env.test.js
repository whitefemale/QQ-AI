'use strict'

const assert = require('node:assert/strict')
const path = require('node:path')
const test = require('node:test')

const { buildBackendEnv, sqliteUrl } = require('../lib/backend-env')

test('后端环境使用绝对数据目录与 SQLite 路径', () => {
  const repoRoot = path.resolve('D:/repo/ai-group-friend')
  const dataDir = path.resolve('D:/repo/ai-group-friend/data')
  const env = buildBackendEnv({
    baseEnv: {
      PATH: 'keep-me',
      CREDENTIAL_ENCRYPTION_KEY: 'secret-from-env',
      DATABASE_URL: 'sqlite+aiosqlite:///relative.db',
    },
    repoRoot,
    dataDir: 'data',
    port: 8123,
  })

  assert.equal(env.PATH, 'keep-me')
  assert.equal(env.CREDENTIAL_ENCRYPTION_KEY, 'secret-from-env')
  assert.equal(env.APP_HOST, '127.0.0.1')
  assert.equal(env.APP_PORT, '8123')
  assert.equal(env.PYTHONUTF8, '1')
  assert.equal(env.PYTHONIOENCODING, 'utf-8')
  assert.equal(env.DATA_DIR, dataDir)
  assert.equal(env.DATABASE_URL, sqliteUrl(path.join(dataDir, 'ai_group_friend.db')))
  assert.equal(env.FRONTEND_DIST, path.join(repoRoot, 'frontend', 'dist'))
  assert.equal(env.AUTO_MIGRATE, 'true')
})

test('SQLite URL 使用正斜杠，不包含反斜杠', () => {
  const url = sqliteUrl('D:\\repo\\data\\ai_group_friend.db')
  assert.equal(url.startsWith('sqlite+aiosqlite:///'), true)
  assert.equal(url.includes('\\'), false)
  assert.match(url, /ai_group_friend\.db$/u)
})
