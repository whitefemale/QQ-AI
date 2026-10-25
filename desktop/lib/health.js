'use strict'

const DEFAULT_APP_NAME = 'AI 群友'

function timeoutFetch(fetchImpl, url, timeoutMs) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  return fetchImpl(url, { signal: controller.signal }).finally(() => clearTimeout(timer))
}

/** 读取健康检查数据；失败返回 null，不抛出。 */
async function readHealth(port, { fetchImpl = globalThis.fetch, timeoutMs = 1500 } = {}) {
  try {
    const response = await timeoutFetch(fetchImpl, `http://127.0.0.1:${port}/api/health`, timeoutMs)
    if (!response.ok) return null
    const payload = await response.json()
    const data = payload && typeof payload === 'object' ? payload.data : null
    if (!data || data.status !== 'ok') return null
    return data
  } catch {
    return null
  }
}

/** 探测 8000 上是否已有本项目后端，避免重复打开同一数据库。 */
async function probeExistingBackend({
  port = 8000,
  appName = DEFAULT_APP_NAME,
  fetchImpl = globalThis.fetch,
  timeoutMs = 1200,
} = {}) {
  const data = await readHealth(port, { fetchImpl, timeoutMs })
  if (!data) return null
  return {
    port,
    version: typeof data.version === 'string' ? data.version : '',
    app: typeof data.app === 'string' ? data.app : '',
    matches: data.app === appName,
  }
}

/** 轮询健康检查，直到成功或超时。 */
async function waitForHealth({
  port,
  timeoutMs = 60000,
  intervalMs = 500,
  fetchImpl = globalThis.fetch,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  isCancelled = () => false,
}) {
  const startedAt = Date.now()
  let lastError = '后端尚未响应。'
  while (Date.now() - startedAt < timeoutMs) {
    if (isCancelled()) return { ok: false, cancelled: true, error: '启动已取消。' }
    const data = await readHealth(port, { fetchImpl })
    if (data) return { ok: true, version: data.version || '', elapsedMs: Date.now() - startedAt }
    lastError = '等待 /api/health 响应…'
    await sleep(intervalMs)
  }
  return { ok: false, error: lastError, elapsedMs: Date.now() - startedAt }
}

module.exports = {
  DEFAULT_APP_NAME,
  readHealth,
  probeExistingBackend,
  waitForHealth,
}
