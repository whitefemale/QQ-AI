'use strict'

const cryptoDefault = require('node:crypto')
const fsDefault = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')

const MIN_PYTHON = [3, 12]
const MIN_NODE = [20, 0]
const DEFAULT_TIMEOUT_MS = 15 * 60 * 1000
const MAX_CAPTURE = 20000

function parseVersion(text) {
  const match = String(text).match(/(\d+)\.(\d+)(?:\.(\d+))?/u)
  if (!match) return null
  return [Number(match[1]), Number(match[2]), Number(match[3] ?? 0)]
}

function atLeast(version, minimum) {
  if (!version) return false
  for (let index = 0; index < minimum.length; index += 1) {
    if (version[index] > minimum[index]) return true
    if (version[index] < minimum[index]) return false
  }
  return true
}

function shellFor(command) {
  if (process.platform !== 'win32') return false
  // Windows 上 npm/npx 实际是 .cmd 包装；直接 spawn 会 ENOENT，必须经由 cmd.exe。
  return /\.(cmd|bat)$/iu.test(command) || command === 'npm' || command === 'npx'
}

/**
 * 通过 cmd.exe 执行 .cmd 包装，并显式校验每个参数只含安全字符。
 * 不使用 spawn 的 shell 选项，避免 Node 的 DEP0190（参数未转义）警告；
 * 命令与参数仍由应用代码固定提供，渲染进程无法传入。
 */
function windowsShellPlan(command, args) {
  const safe = /^[A-Za-z0-9._:/\\=-]+$/u
  const parts = [command, ...args]
  if (!parts.every((part) => safe.test(part))) {
    throw new Error('拒绝执行包含不安全字符的安装命令。')
  }
  return {
    command: process.env.ComSpec || 'cmd.exe',
    args: ['/d', '/s', '/c', parts.join(' ')],
    shell: false,
  }
}

/**
 * 在固定目录执行白名单命令，流式回调输出。命令与参数由应用代码提供，
 * 绝不接受渲染进程传入的任意命令或路径。
 */
function createCommandRunner({ spawnImpl = spawn, logger = null } = {}) {
  return function run(command, args, { cwd, env = process.env, onLine = null, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
    let plan
    try {
      plan = shellFor(command)
        ? windowsShellPlan(command, args)
        : { command, args, shell: false }
    } catch (error) {
      return Promise.resolve({ code: -1, stdout: '', stderr: error.message })
    }

    return new Promise((resolve) => {
      let stdout = ''
      let stderr = ''
      let settled = false
      const child = spawnImpl(plan.command, plan.args, {
        cwd,
        env,
        shell: plan.shell,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      })

      const emitLine = (line) => {
        const text = line.replace(/\r$/u, '')
        if (!text) return
        if (onLine) onLine(text)
        if (logger) logger.info(`[setup] ${text}`)
      }
      const wire = (stream, isError) => {
        let pending = ''
        stream.setEncoding('utf8')
        stream.on('data', (chunk) => {
          if (isError) stderr = (stderr + chunk).slice(-MAX_CAPTURE)
          else stdout = (stdout + chunk).slice(-MAX_CAPTURE)
          pending += chunk
          const lines = pending.split(/\r?\n/u)
          pending = lines.pop() ?? ''
          for (const line of lines) emitLine(line)
        })
        stream.on('end', () => {
          if (pending) emitLine(pending)
          pending = ''
        })
      }
      if (child.stdout) wire(child.stdout, false)
      if (child.stderr) wire(child.stderr, true)

      const timer = setTimeout(() => {
        if (settled) return
        emitLine(`命令超时（${Math.round(timeoutMs / 1000)} 秒），正在终止。`)
        try {
          child.kill()
        } catch {
          /* 忽略 */
        }
      }, timeoutMs)

      child.on('error', (error) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        resolve({ code: -1, stdout, stderr: `${stderr}\n${error.message}`.trim() })
      })
      child.on('close', (code) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        resolve({ code: code ?? -1, stdout, stderr })
      })
    })
  }
}

function isConfiguredEnvValue(value) {
  const trimmed = String(value ?? '').trim()
  return Boolean(trimmed) && !trimmed.startsWith('replace-with') && !trimmed.startsWith('<')
}

function readEnvKeyState(envFile, fsImpl = fsDefault) {
  try {
    const text = fsImpl.readFileSync(envFile, 'utf8')
    const match = text.match(/^CREDENTIAL_ENCRYPTION_KEY=(.*)$/mu)
    if (!match) return 'missing'
    return isConfiguredEnvValue(match[1]) ? 'configured' : 'placeholder'
  } catch {
    return 'missing'
  }
}

function readEnvValue(text, key) {
  const match = String(text).match(new RegExp(`^${key}=(.*)$`, 'mu'))
  return match ? match[1].trim() : ''
}

/**
 * 打包版首次启动生成 userData 下的本地密钥文件。
 *
 * 已有文件绝不覆盖；缺少任一密钥时直接报错，避免轮换加密密钥导致旧凭证不可解密。
 */
function ensureLocalEnvFile({ envFile, fsImpl = fsDefault, cryptoImpl = cryptoDefault } = {}) {
  if (!envFile) throw new Error('缺少本地密钥文件路径。')
  let text = null
  try {
    text = fsImpl.readFileSync(envFile, 'utf8')
  } catch {
    text = null
  }
  if (text === null) {
    const credentialKey = cryptoImpl.randomBytes(32).toString('base64url')
    const appSecret = cryptoImpl.randomBytes(48).toString('base64url')
    const content =
      '# 由桌面版首次启动生成；请勿提交、分享或粘贴到聊天中。\n' +
      `APP_SECRET_KEY=${appSecret}\n` +
      `CREDENTIAL_ENCRYPTION_KEY=${credentialKey}\n`
    fsImpl.mkdirSync(path.dirname(envFile), { recursive: true })
    fsImpl.writeFileSync(envFile, content, { encoding: 'utf8', mode: 0o600 })
    return { created: true, envFile, keyState: 'configured' }
  }
  if (
    !isConfiguredEnvValue(readEnvValue(text, 'CREDENTIAL_ENCRYPTION_KEY')) ||
    !isConfiguredEnvValue(readEnvValue(text, 'APP_SECRET_KEY'))
  ) {
    throw new Error(
      '本地密钥文件缺少有效的 CREDENTIAL_ENCRYPTION_KEY 或 APP_SECRET_KEY。为避免破坏已有凭证，安装版不会覆盖该文件；请先备份并修复。',
    )
  }
  return { created: false, envFile, keyState: 'configured' }
}

/** 打包版自检：只读检查随附后端、前端与安装器，不执行任何命令。 */
function inspectPackagedRuntime({
  backendExecutable,
  frontendDist,
  installerExecutable = '',
  fsImpl = fsDefault,
} = {}) {
  const backendExists = Boolean(backendExecutable) && fsImpl.existsSync(backendExecutable)
  const frontendIndex = frontendDist ? path.join(frontendDist, 'index.html') : ''
  const frontendExists = Boolean(frontendIndex) && fsImpl.existsSync(frontendIndex)
  const installerExists = Boolean(installerExecutable) && fsImpl.existsSync(installerExecutable)
  const missing = []
  if (!backendExists) missing.push('内置后端')
  if (!frontendExists) missing.push('管理界面资源')
  return {
    backendExists,
    frontendExists,
    installerExists,
    missing,
    ok: missing.length === 0,
  }
}

function inspectSetup({ repoRoot, fsImpl = fsDefault } = {}) {
  const backendDir = path.join(repoRoot, 'backend')
  const frontendDir = path.join(repoRoot, 'frontend')
  const pythonPath =
    process.platform === 'win32'
      ? path.join(backendDir, '.venv', 'Scripts', 'python.exe')
      : path.join(backendDir, '.venv', 'bin', 'python')
  return {
    backendDir,
    frontendDir,
    pythonPath,
    envFile: path.join(repoRoot, '.env'),
    distIndex: path.join(frontendDir, 'dist', 'index.html'),
    nodeModules: path.join(frontendDir, 'node_modules'),
    packageLock: path.join(frontendDir, 'package-lock.json'),
    venvExists: fsImpl.existsSync(pythonPath),
    envExists: fsImpl.existsSync(path.join(repoRoot, '.env')),
    envKeyState: readEnvKeyState(path.join(repoRoot, '.env'), fsImpl),
    distExists: fsImpl.existsSync(path.join(frontendDir, 'dist', 'index.html')),
    nodeModulesExists: fsImpl.existsSync(path.join(frontendDir, 'node_modules')),
    packageLockExists: fsImpl.existsSync(path.join(frontendDir, 'package-lock.json')),
  }
}

async function detectPython(runner, cwd) {
  const candidates = [
    { command: 'python', prefix: [] },
    { command: 'py', prefix: ['-3'] },
  ]
  for (const candidate of candidates) {
    const result = await runner(candidate.command, [...candidate.prefix, '--version'], {
      cwd,
      timeoutMs: 15000,
    })
    const version = parseVersion(`${result.stdout}\n${result.stderr}`)
    if (result.code === 0 && version) {
      return { ...candidate, version: version.join('.') }
    }
  }
  return null
}

async function detectNode(runner, cwd) {
  const nodeResult = await runner('node', ['--version'], { cwd, timeoutMs: 15000 })
  const npmResult = await runner('npm', ['--version'], { cwd, timeoutMs: 20000 })
  const version = parseVersion(`${nodeResult.stdout}\n${nodeResult.stderr}`)
  return {
    nodeOk: nodeResult.code === 0 && atLeast(version, MIN_NODE),
    nodeVersion: version ? version.join('.') : '',
    npmOk: npmResult.code === 0,
  }
}

function emitStep(onStep, id, label, status, detail = '') {
  if (onStep) onStep({ id, label, status, detail })
}

/**
 * 幂等首次启动检查：只补齐缺失项，不覆盖已有 .env、数据库或构建产物。
 */
async function runSetup({
  repoRoot,
  runner,
  fsImpl = fsDefault,
  onStep = null,
  onLog = null,
  env = process.env,
  timeoutMs = DEFAULT_TIMEOUT_MS,
}) {
  const state = inspectSetup({ repoRoot, fsImpl })
  const log = (line) => {
    if (onLog) onLog(line)
  }
  const run = (command, args, cwd) =>
    runner(command, args, { cwd, env, onLine: log, timeoutMs })

  emitStep(onStep, 'environment', '检查运行环境', 'running')
  const python = await detectPython(runner, repoRoot)
  if (!python) {
    emitStep(onStep, 'environment', '检查运行环境', 'error', '未找到 Python')
    throw new Error('未找到 Python。请安装 Python 3.12+，并确保 python 或 py 命令可用。')
  }
  const pythonVersion = parseVersion(python.version)
  if (!atLeast(pythonVersion, MIN_PYTHON)) {
    emitStep(onStep, 'environment', '检查运行环境', 'error', 'Python 版本过低')
    throw new Error(`Python 版本为 ${python.version}，桌面版需要 3.12 或更高。`)
  }
  const nodeState = await detectNode(runner, repoRoot)
  if (!nodeState.nodeOk || !nodeState.npmOk) {
    emitStep(onStep, 'environment', '检查运行环境', 'error', '未找到 Node/npm')
    throw new Error('未找到可用的 Node.js 20+ 与 npm。请安装 Node.js 后重新启动。')
  }
  log(`Python ${python.version}，Node ${nodeState.nodeVersion}`)
  emitStep(onStep, 'environment', '检查运行环境', 'ok')

  if (!state.venvExists) {
    emitStep(onStep, 'venv', '创建后端虚拟环境', 'running')
    const create = await run(python.command, [...python.prefix, '-m', 'venv', '.venv'], state.backendDir)
    if (create.code !== 0) {
      emitStep(onStep, 'venv', '创建后端虚拟环境', 'error')
      throw new Error('创建 backend/.venv 失败，请查看日志。')
    }
    emitStep(onStep, 'venv', '创建后端虚拟环境', 'ok')
  } else {
    emitStep(onStep, 'venv', '创建后端虚拟环境', 'skipped', '已存在')
  }

  const currentPython = fsImpl.existsSync(state.pythonPath) ? state.pythonPath : null
  if (!currentPython) throw new Error('后端虚拟环境不完整：找不到 .venv 中的 Python。')

  emitStep(onStep, 'backend-deps', '检查后端依赖', 'running')
  // 检查项目直接依赖，而不是只导入少数包；避免残缺的虚拟环境被误判为已就绪。
  const importCheck = await run(
    currentPython,
    [
      '-c',
      'import fastapi, uvicorn, sqlalchemy, alembic, aiosqlite, httpx, websockets, cryptography, pydantic_settings',
    ],
    state.backendDir,
  )
  if (importCheck.code !== 0) {
    log('后端依赖缺失，开始安装（首次可能需要几分钟）…')
    const install = await run(currentPython, ['-m', 'pip', 'install', '-e', '.'], state.backendDir)
    if (install.code !== 0) {
      emitStep(onStep, 'backend-deps', '检查后端依赖', 'error')
      throw new Error('安装后端依赖失败，请确认网络可用并查看日志。')
    }
    emitStep(onStep, 'backend-deps', '检查后端依赖', 'ok', '已安装')
  } else {
    emitStep(onStep, 'backend-deps', '检查后端依赖', 'skipped', '已就绪')
  }

  if (!state.envExists) {
    emitStep(onStep, 'env', '生成本地安全密钥', 'running')
    const generated = await run(
      python.command,
      [...python.prefix, path.join('scripts', 'gen_keys.py'), '--write'],
      repoRoot,
    )
    if (generated.code !== 0) {
      emitStep(onStep, 'env', '生成本地安全密钥', 'error')
      throw new Error('生成 .env 失败，请查看日志。')
    }
    emitStep(onStep, 'env', '生成本地安全密钥', 'ok', '已创建 .env')
  } else {
    const keyState = readEnvKeyState(state.envFile, fsImpl)
    if (keyState !== 'configured') {
      emitStep(onStep, 'env', '生成本地安全密钥', 'error', '缺少密钥')
      throw new Error(
        '现有 .env 中缺少有效的 CREDENTIAL_ENCRYPTION_KEY。为避免破坏已有凭证，向导不会覆盖 .env；请先备份并手工修复。',
      )
    }
    emitStep(onStep, 'env', '生成本地安全密钥', 'skipped', '.env 已存在')
  }

  if (!state.distExists) {
    if (!state.nodeModulesExists) {
      emitStep(onStep, 'frontend-deps', '安装前端依赖', 'running')
      const installArgs = state.packageLockExists ? ['ci'] : ['install']
      const install = await run('npm', installArgs, state.frontendDir)
      if (install.code !== 0) {
        emitStep(onStep, 'frontend-deps', '安装前端依赖', 'error')
        throw new Error('安装前端依赖失败，请检查网络与 npm 配置。')
      }
      emitStep(onStep, 'frontend-deps', '安装前端依赖', 'ok')
    } else {
      emitStep(onStep, 'frontend-deps', '安装前端依赖', 'skipped', '已存在')
    }

    emitStep(onStep, 'frontend-build', '构建管理界面', 'running')
    const build = await run('npm', ['run', 'build'], state.frontendDir)
    if (build.code !== 0 || !fsImpl.existsSync(state.distIndex)) {
      emitStep(onStep, 'frontend-build', '构建管理界面', 'error')
      throw new Error('前端构建失败，请查看日志。')
    }
    emitStep(onStep, 'frontend-build', '构建管理界面', 'ok')
  } else {
    emitStep(onStep, 'frontend-deps', '安装前端依赖', 'skipped', '无需构建')
    emitStep(onStep, 'frontend-build', '构建管理界面', 'skipped', '已存在')
  }

  return {
    ...inspectSetup({ repoRoot, fsImpl }),
    pythonPath: state.pythonPath,
    pythonCommand: python,
    dataDir: path.join(repoRoot, 'data'),
  }
}

module.exports = {
  MIN_PYTHON,
  MIN_NODE,
  parseVersion,
  atLeast,
  createCommandRunner,
  inspectSetup,
  inspectPackagedRuntime,
  isConfiguredEnvValue,
  readEnvKeyState,
  ensureLocalEnvFile,
  runSetup,
}
