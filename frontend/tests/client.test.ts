import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  api,
  downloadApiFile,
  filenameFromDisposition,
  getAdminToken,
  setAdminToken,
} from '@/api/client'

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  setAdminToken(null)
})

function abortableFetch() {
  return vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          reject(new DOMException('Aborted', 'AbortError'))
        })
      }),
  )
}

describe('request timeout', () => {
  it('aborts a slow JSON request with TIMEOUT', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', abortableFetch())

    const pending = api('/health', { timeoutMs: 50 }).catch((error: unknown) => error)
    await vi.advanceTimersByTimeAsync(60)

    const error = await pending
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'TIMEOUT', status: 0 })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('keeps caller cancellation distinct from timeout', async () => {
    vi.stubGlobal('fetch', abortableFetch())
    const controller = new AbortController()

    const pending = api('/health', { signal: controller.signal }).catch((error: unknown) => error)
    controller.abort()

    const error = await pending
    expect((error as Error).name).toBe('AbortError')
  })

  it('times out downloads and clears the timer', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', abortableFetch())

    const pending = downloadApiFile('/usage/export.csv', { timeoutMs: 40 }).catch(
      (error: unknown) => error,
    )
    await vi.advanceTimersByTimeAsync(50)

    expect(await pending).toMatchObject({ code: 'TIMEOUT', status: 0 })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('clears the timer after a successful download', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('a,b\r\n1,2\r\n', { status: 200 })))

    await downloadApiFile('/usage/export.csv', { timeoutMs: 1000 })

    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('admin token storage', () => {
  it('keeps the admin token in sessionStorage only', () => {
    localStorage.clear()
    sessionStorage.clear()

    setAdminToken('admin-secret')

    expect(sessionStorage.getItem('aiqf.adminToken')).toBe('admin-secret')
    expect(localStorage.getItem('aiqf.adminToken')).toBeNull()
    expect(localStorage.length).toBe(0)
    expect(getAdminToken()).toBe('admin-secret')

    setAdminToken(null)
    expect(sessionStorage.getItem('aiqf.adminToken')).toBeNull()
    expect(getAdminToken()).toBe('')
  })
})

describe('download filename handling', () => {
  it('uses a safe fallback and decodes UTF-8 names', () => {
    expect(filenameFromDisposition(null)).toBe('download')
    expect(filenameFromDisposition('attachment; filename="llm-usage.csv"')).toBe('llm-usage.csv')
    expect(filenameFromDisposition("attachment; filename*=UTF-8''%E7%94%A8%E9%87%8F.csv")).toBe(
      '用量.csv',
    )
  })

  it('never keeps path separators from a header value', () => {
    const name = filenameFromDisposition('attachment; filename="../../evil.csv"')
    expect(name).not.toContain('/')
    expect(name).not.toContain('\\')
    expect(name.endsWith('.csv')).toBe(true)
  })
})

describe('downloadApiFile', () => {
  it('returns the raw blob with the server filename and admin token', async () => {
    setAdminToken('admin-test-token')
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('created_at_utc,status\r\n2026-01-01T00:00:00Z,success\r\n', {
        status: 200,
        headers: {
          'Content-Type': 'text/csv; charset=utf-8',
          'Content-Disposition': 'attachment; filename="llm-usage-test.csv"',
        },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const file = await downloadApiFile('/usage/export.csv', { query: { group_id: 'group-1' } })

    expect(file.filename).toBe('llm-usage-test.csv')
    const text = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = () => reject(reader.error)
      reader.readAsText(file.blob)
    })
    expect(text).toContain('created_at_utc,status')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/api/usage/export.csv?group_id=group-1')
    const headers = init.headers as Record<string, string>
    expect(headers.Accept).toContain('text/csv')
    expect(headers['X-Admin-Token']).toBe('admin-test-token')
  })

  it('surfaces the backend error envelope instead of downloading it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            data: null,
            error: { code: 'VALIDATION_ERROR', message: '导出开始时间不能晚于结束时间。' },
            request_id: 'req-1',
          }),
          { status: 400, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    const error = await downloadApiFile('/usage/export.csv').catch((err: unknown) => err)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'VALIDATION_ERROR', status: 400 })
  })

  it('reports a network failure without leaking request details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('failed to fetch')))

    await expect(downloadApiFile('/usage/export.csv')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      status: 0,
    })
  })
})
