import { afterEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'
import { request } from './client'
import { ApiError, SUCCESS_CODE } from './errors'
import type { ApiResponse } from './types'

const DemoSchema = z.object({ ok: z.boolean() })

function envelope<T>(data: T, overrides?: Partial<ApiResponse<T>>): ApiResponse<T> {
  return { code: SUCCESS_CODE, message: 'ok', request_id: 'env-rid', data, ...overrides }
}

function mockResponse(payload: unknown, requestId: string | null = null, status = 200) {
  return {
    status,
    headers: {
      get: (name: string) => (name.toLowerCase() === 'x-request-id' ? requestId : null),
    },
    json: async () => payload,
  }
}

type FetchImpl = (input: string, init: RequestInit) => Promise<unknown>

function stubFetch(impl: FetchImpl): ReturnType<typeof vi.fn<FetchImpl>> {
  const mock = vi.fn<FetchImpl>(impl)
  vi.stubGlobal('fetch', mock)
  return mock
}

/** 挂起直到 abort 的 fetch，用于超时与中止路径。 */
function hangingFetch(_input: string, init: RequestInit): Promise<unknown> {
  return new Promise((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
  })
}

async function captureError(pending: Promise<unknown>): Promise<ApiError> {
  try {
    await pending
  } catch (error) {
    return error as ApiError
  }
  throw new Error('期望抛出 ApiError，实际未抛')
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('api/client 信封解包', () => {
  it('code=0 时取 data 并经目标 schema 校验后返回', async () => {
    stubFetch(async () => mockResponse(envelope({ ok: true })))

    await expect(request('/api/v1/demo', { method: 'GET', schema: DemoSchema })).resolves.toEqual({
      ok: true,
    })
  })

  it('code 非 0 抛业务错误，携带 code/message/request_id', async () => {
    stubFetch(async () => mockResponse(envelope(null, { code: 6001, message: '状态非法' })))

    const error = await captureError(request('/api/v1/demo', { method: 'GET', schema: DemoSchema }))

    expect(error).toBeInstanceOf(ApiError)
    expect(error.kind).toBe('business')
    expect(error.code).toBe(6001)
    expect(error.message).toBe('状态非法')
    expect(error.requestId).toBe('env-rid')
  })

  it('request_id 优先取 X-Request-ID 响应头，信封值兜底', async () => {
    stubFetch(async () =>
      mockResponse(envelope(null, { code: 9002, message: '配置错误' }), 'hdr-rid'),
    )

    const error = await captureError(request('/api/v1/demo', { method: 'GET', schema: DemoSchema }))

    expect(error.requestId).toBe('hdr-rid')
  })

  it('信封畸形（缺字段）抛契约错误', async () => {
    stubFetch(async () => mockResponse({ unexpected: 1 }))

    const error = await captureError(request('/api/v1/demo', { method: 'GET', schema: DemoSchema }))

    expect(error.kind).toBe('contract')
  })

  it('data 畸形被 Zod 拒绝，且不发起重试', async () => {
    const fetchMock = stubFetch(async () => mockResponse(envelope({ nope: 1 })))

    const error = await captureError(request('/api/v1/demo', { method: 'GET', schema: DemoSchema }))

    expect(error.kind).toBe('contract')
    expect(fetchMock.mock.calls).toHaveLength(1)
  })

  it('响应不是合法 JSON 时抛契约错误', async () => {
    stubFetch(async () => ({
      status: 502,
      headers: { get: () => null },
      json: async () => {
        throw new Error('bad json')
      },
    }))

    const error = await captureError(request('/api/v1/demo', { method: 'GET', schema: DemoSchema }))

    expect(error.kind).toBe('contract')
  })
})

describe('api/client 超时与中止', () => {
  it('超时即中止并抛 timeout 错误，不重试', async () => {
    vi.useFakeTimers()
    const fetchMock = stubFetch(hangingFetch)

    const assertion = expect(
      request('/api/v1/demo', { method: 'GET', schema: DemoSchema }),
    ).rejects.toMatchObject({ kind: 'timeout' })
    await vi.advanceTimersByTimeAsync(61_000)
    await assertion

    expect(fetchMock.mock.calls).toHaveLength(1)
  })

  it('调用方中止信号触发 aborted 错误', async () => {
    stubFetch(hangingFetch)
    const caller = new AbortController()

    const assertion = expect(
      request('/api/v1/demo', { method: 'GET', schema: DemoSchema, signal: caller.signal }),
    ).rejects.toMatchObject({ kind: 'aborted' })
    caller.abort()
    await assertion
  })

  it('已中止的信号直接拒绝，不发起请求', async () => {
    const fetchMock = stubFetch(async () => mockResponse(envelope({ ok: true })))
    const caller = new AbortController()
    caller.abort()

    await expect(
      request('/api/v1/demo', { method: 'GET', schema: DemoSchema, signal: caller.signal }),
    ).rejects.toMatchObject({ kind: 'aborted' })
    expect(fetchMock.mock.calls).toHaveLength(0)
  })

  it('网络失败抛 network 错误且不发起重试', async () => {
    const fetchMock = stubFetch(async () => {
      throw new Error('offline')
    })

    const error = await captureError(request('/api/v1/demo', { method: 'GET', schema: DemoSchema }))

    expect(error.kind).toBe('network')
    expect(fetchMock.mock.calls).toHaveLength(1)
  })
})

describe('api/request 请求标注', () => {
  it('POST 带 body 时声明 JSON 头并透传禁重试语义标注', async () => {
    const fetchMock = stubFetch(async () => mockResponse(envelope({ ok: true })))

    await request('/api/v1/demo', {
      method: 'POST',
      schema: DemoSchema,
      body: { a: 1 },
      hasSideEffect: true,
    })

    const init = fetchMock.mock.calls[0]?.[1]
    expect(init?.headers).toMatchObject({
      accept: 'application/json',
      'content-type': 'application/json',
    })
    expect(init?.body).toBe(JSON.stringify({ a: 1 }))
    expect(init?.signal).toBeInstanceOf(AbortSignal)
  })
})
