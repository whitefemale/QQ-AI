'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')

const paths = require('../lib/paths')
const { buildBackendEnv } = require('../lib/backend-env')
const { BackendManager } = require('../lib/backend')
const { ensureLocalEnvFile, inspectPackagedRuntime } = require('../lib/setup')

function tempDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix))
}

test('安装包布局从 resources 与 userData 派生，不依赖仓库', () => {
  const runtime = paths.resolveRuntime({
    isPackaged: true,
    resourcesPath: 'D:/Program Files/AI Group Friend/resources',
    userDataPath: 'C:/Users/demo/AppData/Roaming/AI Group Friend',
    repoRoot: 'D:/Program Files/AI Group Friend/resources',
    appRoot: 'D:/Program Files/AI Group Friend/resources/app.asar',
    platform: 'win32',
  })

  assert.equal(runtime.packaged, true)
  assert.equal(runtime.backendMode, 'bundled')
  assert.equal(runtime.backendExecutable, path.join(runtime.backendDir, 'aiqf-backend.exe'))
  assert.equal(runtime.frontendDist, path.join('D:/Program Files/AI Group Friend/resources', 'frontend', 'dist'))
  assert.equal(runtime.installerExecutable, path.join(runtime.backendDir, 'tools', 'aiqf-napcat-installer.exe'))
  assert.equal(runtime.envFile, path.join('C:/Users/demo/AppData/Roaming/AI Group Friend', '.env'))
  assert.equal(runtime.defaultDataDir, path.join('C:/Users/demo/AppData/Roaming/AI Group Friend', 'data'))
  assert.equal(
    runtime.defaultConnectorsDir,
    path.join('C:/Users/demo/AppData/Roaming/AI Group Friend', 'connectors', 'napcat'),
  )
  assert.equal(runtime.shellHtml, path.join('D:/Program Files/AI Group Friend/resources/app.asar', 'shell', 'index.html'))
})

test('安装包后端环境显式指定前端、密钥与安装器，并清理继承的重定向变量', () => {
  const runtime = paths.resolveRuntime({
    isPackaged: true,
    resourcesPath: 'D:/app/resources',
    userDataPath: 'C:/Users/demo/AppData/Roaming/AI Group Friend',
    appRoot: 'D:/app/resources/app.asar',
    platform: 'win32',
  })
  const env = buildBackendEnv({
    baseEnv: {
      PATH: 'keep-me',
      AI_GROUP_FRIEND_ENV_FILE: 'D:/repo/.env',
      AI_GROUP_FRIEND_RESOURCE_ROOT: 'D:/repo/backend',
      CONNECTORS_DIR: 'D:/repo/connectors/napcat',
    },
    repoRoot: runtime.repoRoot,
    dataDir: runtime.defaultDataDir,
    port: 8000,
    connectorsDir: runtime.defaultConnectorsDir,
    frontendDist: runtime.frontendDist,
    envFile: runtime.envFile,
    installerExecutable: runtime.installerExecutable,
  })

  assert.equal(env.PATH, 'keep-me')
  assert.equal(env.FRONTEND_DIST, runtime.frontendDist)
  assert.equal(env.AI_GROUP_FRIEND_ENV_FILE, runtime.envFile)
  assert.equal(env.AI_GROUP_FRIEND_INSTALLER_EXE, runtime.installerExecutable)
  assert.equal(env.CONNECTORS_DIR, runtime.defaultConnectorsDir)
  assert.equal(env.AI_GROUP_FRIEND_RESOURCE_ROOT, undefined)
  assert.equal(env.DATA_DIR, path.resolve(runtime.defaultDataDir))
  assert.equal(env.APP_HOST, '127.0.0.1')
})

test('安装包后端以固定可执行文件启动，不经过 Python', async () => {
  const dataDir = tempDir('aiqf-packaged-data-')
  const captures = []
  let spawned = false
  const fakeChild = {
    pid: 4242,
    stdout: null,
    stderr: null,
    kill() {
      this.exitCallback?.(null, 'SIGTERM')
    },
    once(event, callback) {
      if (event === 'exit') this.exitCallback = callback
    },
    on() {},
  }
  const manager = new BackendManager({
    repoRoot: tempDir('aiqf-packaged-root-'),
    backendDir: tempDir('aiqf-packaged-backend-'),
    pythonPath: 'must-not-be-used',
    backendMode: 'bundled',
    backendExecutable: 'D:/app/resources/backend/aiqf-backend.exe',
    frontendDist: 'D:/app/resources/frontend/dist',
    envFile: 'C:/Users/demo/AppData/Roaming/AI Group Friend/.env',
    installerExecutable: 'D:/app/resources/backend/tools/aiqf-napcat-installer.exe',
    dataDir,
    logger: null,
    preferredPort: 18991,
    spawnImpl: (command, args, options) => {
      captures.push({ command, args, options })
      spawned = true
      return fakeChild
    },
    fetchImpl: async () => {
      if (!spawned) throw new Error('connection refused')
      return {
        ok: true,
        json: async () => ({ data: { status: 'ok', app: 'AI 群友', version: require('../package.json').version } }),
      }
    },
    healthProbe: async () => true,
    setIntervalImpl: () => ({ unref() {} }),
    clearIntervalImpl: () => {},
  })

  await manager.start()
  assert.equal(captures.length, 1)
  assert.equal(captures[0].command, 'D:/app/resources/backend/aiqf-backend.exe')
  assert.deepEqual(captures[0].args, [])
  assert.match(captures[0].options.env.FRONTEND_DIST, /frontend[\\/]dist$/u)
  assert.match(captures[0].options.env.AI_GROUP_FRIEND_ENV_FILE, /[\\/]\.env$/u)
  assert.equal(manager.getInfo().status, 'running')
  await manager.stop()
})

test('安装版首次启动生成密钥文件，且绝不覆盖已有密钥', () => {
  const dir = tempDir('aiqf-env-')
  const envFile = path.join(dir, 'nested', '.env')
  const first = ensureLocalEnvFile({ envFile })
  assert.equal(first.created, true)
  const text = fs.readFileSync(envFile, 'utf8')
  assert.match(text, /^APP_SECRET_KEY=.{20,}$/mu)
  assert.match(text, /^CREDENTIAL_ENCRYPTION_KEY=.{40,}$/mu)

  const second = ensureLocalEnvFile({ envFile })
  assert.equal(second.created, false)
  assert.equal(fs.readFileSync(envFile, 'utf8'), text)

  fs.writeFileSync(envFile, 'APP_SECRET_KEY=short\n', 'utf8')
  assert.throws(() => ensureLocalEnvFile({ envFile }), /不会覆盖/u)
  assert.equal(fs.readFileSync(envFile, 'utf8'), 'APP_SECRET_KEY=short\n')
})

test('安装版自检只读检查随附资源，不执行命令', () => {
  const root = tempDir('aiqf-pack-')
  const backend = path.join(root, 'backend', 'aiqf-backend.exe')
  const frontend = path.join(root, 'frontend', 'dist')
  const installer = path.join(root, 'backend', 'tools', 'aiqf-napcat-installer.exe')
  fs.mkdirSync(path.dirname(backend), { recursive: true })
  fs.writeFileSync(backend, '', 'utf8')
  fs.mkdirSync(frontend, { recursive: true })
  fs.writeFileSync(path.join(frontend, 'index.html'), '<!doctype html>', 'utf8')
  fs.mkdirSync(path.dirname(installer), { recursive: true })
  fs.writeFileSync(installer, '', 'utf8')

  const okState = inspectPackagedRuntime({ backendExecutable: backend, frontendDist: frontend, installerExecutable: installer })
  assert.equal(okState.ok, true)
  assert.equal(okState.installerExists, true)

  fs.unlinkSync(backend)
  const broken = inspectPackagedRuntime({ backendExecutable: backend, frontendDist: frontend, installerExecutable: installer })
  assert.equal(broken.ok, false)
  assert.deepEqual(broken.missing, ['内置后端'])
})
