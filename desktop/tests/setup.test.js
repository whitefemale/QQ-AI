'use strict'

const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { PassThrough } = require('node:stream')
const test = require('node:test')

const {
  atLeast,
  createCommandRunner,
  inspectSetup,
  parseVersion,
  readEnvKeyState,
  runSetup,
} = require('../lib/setup')

function pythonPathFor(repoRoot) {
  return process.platform === 'win32'
    ? path.join(repoRoot, 'backend', '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, 'backend', '.venv', 'bin', 'python')
}

function makeRepo({ venv = true, env = 'valid', dist = true, nodeModules = true } = {}) {
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'aiqf-setup-'))
  fs.mkdirSync(path.join(repoRoot, 'backend'), { recursive: true })
  fs.mkdirSync(path.join(repoRoot, 'frontend'), { recursive: true })
  fs.writeFileSync(path.join(repoRoot, 'frontend', 'package-lock.json'), '{}\n', 'utf8')

  if (venv) {
    const python = pythonPathFor(repoRoot)
    fs.mkdirSync(path.dirname(python), { recursive: true })
    fs.writeFileSync(python, '', 'utf8')
  }
  if (env === 'valid') {
    fs.writeFileSync(
      path.join(repoRoot, '.env'),
      'CREDENTIAL_ENCRYPTION_KEY=0123456789abcdef0123456789abcdef\n',
      'utf8',
    )
  } else if (env === 'placeholder') {
    fs.writeFileSync(
      path.join(repoRoot, '.env'),
      'CREDENTIAL_ENCRYPTION_KEY=replace-with-generated-key\n',
      'utf8',
    )
  }
  if (nodeModules) fs.mkdirSync(path.join(repoRoot, 'frontend', 'node_modules'), { recursive: true })
  if (dist) {
    fs.mkdirSync(path.join(repoRoot, 'frontend', 'dist'), { recursive: true })
    fs.writeFileSync(path.join(repoRoot, 'frontend', 'dist', 'index.html'), '<!doctype html>', 'utf8')
  }
  return repoRoot
}

function ok(stdout = '') {
  return { code: 0, stdout, stderr: '' }
}

/**
 * 假命令执行器：模拟 Python/Node 版本、依赖检查以及安装/构建步骤的副作用。
 * 未识别的命令直接失败，防止向导意外执行真实安装。
 */
function makeRunner(repoRoot, calls, { onCommand = null } = {}) {
  const pythonPath = pythonPathFor(repoRoot)
  return async (command, args, options = {}) => {
    const joined = args.join(' ')
    calls.push({ command, args, cwd: options.cwd })
    if (command === 'python' && joined === '--version') return ok('Python 3.13.2')
    if (command === 'node' && joined === '--version') return ok('v22.11.0')
    if (command === 'npm' && joined === '--version') return ok('10.9.0')
    if (
      command === pythonPath &&
      joined ===
        '-c import fastapi, uvicorn, sqlalchemy, alembic, aiosqlite, httpx, websockets, cryptography, pydantic_settings'
    ) {
      return ok('')
    }

    if (onCommand) {
      const result = await onCommand({ command, args, joined, cwd: options.cwd })
      if (result) return result
    }
    return { code: 0, stdout: '', stderr: '' }
  }
}

function withEffects(repoRoot) {
  return async ({ command, args, joined, cwd }) => {
    if (command === 'python' && joined === '-m venv .venv') {
      const python = pythonPathFor(repoRoot)
      fs.mkdirSync(path.dirname(python), { recursive: true })
      fs.writeFileSync(python, '', 'utf8')
      return ok()
    }
    if (command === 'python' && String(args[0] ?? '').endsWith('gen_keys.py')) {
      fs.writeFileSync(
        path.join(repoRoot, '.env'),
        'CREDENTIAL_ENCRYPTION_KEY=abcdefabcdefabcdefabcdefabcdefab\n',
        'utf8',
      )
      return ok()
    }
    if (command === 'npm' && joined === 'ci') {
      fs.mkdirSync(path.join(repoRoot, 'frontend', 'node_modules'), { recursive: true })
      return ok()
    }
    if (command === 'npm' && joined === 'run build') {
      fs.mkdirSync(path.join(repoRoot, 'frontend', 'dist'), { recursive: true })
      fs.writeFileSync(path.join(repoRoot, 'frontend', 'dist', 'index.html'), '<!doctype html>', 'utf8')
      return ok()
    }
    return null
  }
}

test('版本解析与最低版本比较', () => {
  assert.deepEqual(parseVersion('Python 3.13.2'), [3, 13, 2])
  assert.deepEqual(parseVersion('v22.11.0'), [22, 11, 0])
  assert.equal(atLeast([3, 12, 0], [3, 12]), true)
  assert.equal(atLeast([3, 11, 9], [3, 12]), false)
  assert.equal(atLeast([4, 0, 0], [3, 12]), true)
  assert.equal(atLeast(null, [3, 12]), false)
})

test('已就绪时向导只做检查，不重复安装或构建', async () => {
  const repoRoot = makeRepo()
  const calls = []
  const steps = new Map()
  const result = await runSetup({
    repoRoot,
    runner: makeRunner(repoRoot, calls),
    onStep: (step) => steps.set(step.id, step),
  })

  assert.equal(result.venvExists, true)
  assert.equal(steps.get('environment').status, 'ok')
  assert.equal(steps.get('venv').status, 'skipped')
  assert.equal(steps.get('backend-deps').status, 'skipped')
  assert.equal(steps.get('env').status, 'skipped')
  assert.equal(steps.get('frontend-deps').status, 'skipped')
  assert.equal(steps.get('frontend-build').status, 'skipped')
  assert.deepEqual(
    calls.map((call) => call.command),
    ['python', 'node', 'npm', pythonPathFor(repoRoot)],
  )
})

test('缺失的虚拟环境、密钥与构建产物会被补齐且不覆盖已有数据', async () => {
  const repoRoot = makeRepo({ venv: false, env: 'missing', dist: false, nodeModules: false })
  const calls = []
  const steps = new Map()
  await runSetup({
    repoRoot,
    runner: makeRunner(repoRoot, calls, { onCommand: withEffects(repoRoot) }),
    onStep: (step) => steps.set(step.id, step),
  })

  const joinedCalls = calls.map((call) => `${call.command} ${call.args.join(' ')}`)
  assert.ok(joinedCalls.includes('python -m venv .venv'))
  assert.ok(joinedCalls.some((line) => line.endsWith('gen_keys.py --write')))
  assert.ok(joinedCalls.includes('npm ci'))
  assert.ok(joinedCalls.includes('npm run build'))
  assert.equal(steps.get('venv').status, 'ok')
  assert.equal(steps.get('env').status, 'ok')
  assert.equal(steps.get('frontend-deps').status, 'ok')
  assert.equal(steps.get('frontend-build').status, 'ok')
  assert.equal(fs.existsSync(path.join(repoRoot, '.env')), true)
  assert.equal(fs.existsSync(path.join(repoRoot, 'frontend', 'dist', 'index.html')), true)

  const secondCalls = []
  await runSetup({
    repoRoot,
    runner: makeRunner(repoRoot, secondCalls, { onCommand: withEffects(repoRoot) }),
  })
  const secondJoined = secondCalls.map((call) => `${call.command} ${call.args.join(' ')}`)
  assert.equal(secondJoined.includes('npm ci'), false)
  assert.equal(secondJoined.includes('npm run build'), false)
  assert.equal(secondJoined.some((line) => line.includes('-m venv')), false)
})

test('现有 .env 密钥无效时拒绝覆盖并保持原文件', async () => {
  const repoRoot = makeRepo({ env: 'placeholder' })
  const original = fs.readFileSync(path.join(repoRoot, '.env'), 'utf8')
  const calls = []

  await assert.rejects(
    () => runSetup({ repoRoot, runner: makeRunner(repoRoot, calls) }),
    /不会覆盖 \.env/u,
  )
  assert.equal(fs.readFileSync(path.join(repoRoot, '.env'), 'utf8'), original)
  assert.equal(calls.some((call) => call.args.join(' ').includes('gen_keys.py')), false)
})

function fakeSpawn(record) {
  return (command, args, options) => {
    record.push({ command, args, options })
    const child = new EventEmitter()
    child.stdout = new PassThrough()
    child.stderr = new PassThrough()
    child.kill = () => {}
    setImmediate(() => {
      child.stdout.end('ok\n')
      child.stderr.end()
      child.emit('close', 0)
    })
    return child
  }
}

test('Windows 的 npm 通过 cmd.exe 执行且不再使用 shell 选项', async () => {
  const record = []
  const runner = createCommandRunner({ spawnImpl: fakeSpawn(record) })
  const result = await runner('npm', ['--version'], { cwd: os.tmpdir() })

  assert.equal(result.code, 0)
  assert.equal(record.length, 1)
  assert.equal(record[0].options.shell, false)
  if (process.platform === 'win32') {
    assert.equal(record[0].command, process.env.ComSpec || 'cmd.exe')
    assert.deepEqual(record[0].args.slice(0, 3), ['/d', '/s', '/c'])
    assert.equal(record[0].args[3], 'npm --version')
  } else {
    assert.equal(record[0].command, 'npm')
    assert.deepEqual(record[0].args, ['--version'])
  }
})

test('含 shell 元字符的命令参数被拒绝且不会启动进程', async () => {
  const record = []
  const runner = createCommandRunner({ spawnImpl: fakeSpawn(record) })
  const result = await runner('npm', ['install', '&&', 'evil'], { cwd: os.tmpdir() })

  assert.equal(result.code, -1)
  assert.match(result.stderr, /不安全字符/u)
  assert.equal(record.length, 0)
})

test('readEnvKeyState 区分缺失、占位与已配置', () => {
  const repoRoot = makeRepo({ env: 'missing' })
  const envFile = path.join(repoRoot, '.env')
  assert.equal(readEnvKeyState(envFile), 'missing')
  fs.writeFileSync(envFile, 'APP_NAME=AI 群友\n', 'utf8')
  assert.equal(readEnvKeyState(envFile), 'missing')
  fs.writeFileSync(envFile, 'CREDENTIAL_ENCRYPTION_KEY=replace-with-key\n', 'utf8')
  assert.equal(readEnvKeyState(envFile), 'placeholder')
  fs.writeFileSync(envFile, 'CREDENTIAL_ENCRYPTION_KEY=0123456789abcdef\n', 'utf8')
  assert.equal(readEnvKeyState(envFile), 'configured')
  assert.equal(inspectSetup({ repoRoot }).envKeyState, 'configured')
})
