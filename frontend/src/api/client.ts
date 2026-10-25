/** 统一 API 客户端：包裹后端 { data, error, request_id } 响应，并处理网络与鉴权错误。 */

export interface ApiErrorBody {
  code: string
  message: string
  details?: Record<string, unknown> | null
}

export interface ApiEnvelope<T> {
  data: T | null
  error: ApiErrorBody | null
  request_id: string
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details: Record<string, unknown>

  constructor(code: string, message: string, status: number, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

const ADMIN_TOKEN_KEY = 'aiqf.adminToken'

/** 远程管理 Token 只保存在 sessionStorage，关闭标签页即失效；绝不写入 LocalStorage。 */
export function setAdminToken(token: string | null): void {
  if (token && token.trim()) {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, token.trim())
  } else {
    sessionStorage.removeItem(ADMIN_TOKEN_KEY)
  }
}

export function getAdminToken(): string {
  return sessionStorage.getItem(ADMIN_TOKEN_KEY) ?? ''
}

export type QueryValue = string | number | boolean | null | undefined

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  query?: Record<string, QueryValue>
  signal?: AbortSignal
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = new URL(path.startsWith('/api') ? path : `/api${path}`, window.location.origin)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue
      url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

function authHeaders(accept: string): Record<string, string> {
  const headers: Record<string, string> = { Accept: accept }
  const token = getAdminToken()
  if (token) {
    headers['X-Admin-Token'] = token
  }
  return headers
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = authHeaders('application/json')
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw new ApiError('NETWORK_ERROR', '无法连接后端服务，请确认后端已启动。', 0)
  }

  const text = await response.text()
  let payload: ApiEnvelope<T> | null = null
  if (text) {
    try {
      payload = JSON.parse(text) as ApiEnvelope<T>
    } catch {
      payload = null
    }
  }

  if (!response.ok || payload?.error) {
    const body = payload?.error
    throw new ApiError(
      body?.code ?? `HTTP_${response.status}`,
      body?.message ?? `请求失败（HTTP ${response.status}）。`,
      response.status,
      (body?.details as Record<string, unknown> | null) ?? {},
    )
  }
  return (payload?.data ?? null) as T
}

export interface DownloadedFile {
  blob: Blob
  filename: string
}

export function filenameFromDisposition(value: string | null): string {
  if (!value) return 'download'
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(value)
  let raw = ''
  if (encoded) {
    try {
      raw = decodeURIComponent(encoded[1].trim())
    } catch {
      raw = encoded[1].trim()
    }
  } else {
    const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(value)
    raw = plain?.[1]?.trim() ?? ''
  }
  const safe = raw.replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').slice(0, 120)
  return safe || 'download'
}

/** 下载非 JSON 响应（如 CSV）；后端错误包仍按统一 ApiError 抛出。 */
export async function downloadApiFile(
  path: string,
  options: RequestOptions = {},
): Promise<DownloadedFile> {
  let response: Response
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers: authHeaders('text/csv, text/plain, */*'),
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw new ApiError('NETWORK_ERROR', '无法连接后端服务，请确认后端已启动。', 0)
  }

  if (!response.ok) {
    const text = await response.text()
    let payload: ApiEnvelope<unknown> | null = null
    if (text) {
      try {
        payload = JSON.parse(text) as ApiEnvelope<unknown>
      } catch {
        payload = null
      }
    }
    const body = payload?.error
    throw new ApiError(
      body?.code ?? `HTTP_${response.status}`,
      body?.message ?? `下载失败（HTTP ${response.status}）。`,
      response.status,
      (body?.details as Record<string, unknown> | null) ?? {},
    )
  }

  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(response.headers.get('Content-Disposition')),
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  if (error instanceof Error) {
    return error.message
  }
  return '发生未知错误。'
}

export function errorCode(error: unknown): string {
  return error instanceof ApiError ? error.code : 'UNKNOWN'
}
