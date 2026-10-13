import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  clearAdoptions,
  getBrowse,
  getHealth,
  getHistory,
  getPreference,
  getResult,
  getSettings,
  postFeedback,
  postFollowup,
  postOptimize,
  putPreference,
  putSettings,
  scanProject,
} from './endpoints'
import { ApiError, SUCCESS_CODE } from './errors'
import type { ApiResponse } from './types'

function envelope<T>(data: T, overrides?: Partial<ApiResponse<T>>): ApiResponse<T> {
  return { code: SUCCESS_CODE, message: 'ok', request_id: 'env-rid', data, ...overrides }
}

function mockResponse(payload: unknown) {
  return {
    status: 200,
    headers: { get: () => null },
    json: async () => payload,
  }
}

function stubFetchJson(payload: unknown) {
  const mock = vi.fn(async (_input: string, _init: RequestInit) => mockResponse(payload))
  vi.stubGlobal('fetch', mock)
  return mock
}

const snapshot = {
  session_id: 'sess-1',
  state: 'ASKING',
  status: 'ask',
  message: '',
  questions: [{ key: 'target', reason: '缺失', best_guess: 'Foo', ask: '改哪里？' }],
  cleared: ['scope'],
  variants: [{ title: 'A', body: 'b', level: 'A', changes: [] }],
  ranking: null,
}

const settings = {
  models: [],
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.example.com',
    decider: 'auto',
    model_id: 'demo',
    provider: 'DeepSeek',
    timeout: 60,
    max_tokens: null,
    temperature: null,
  },
  process: {
    followup_cost_budget: 1,
    followup_soft_round_guard: 10,
    telemetry: true,
  },
  locked: { candidate_limit: 25 },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api/endpoints 12 操作', () => {
  it('getHealth 请求 GET /api/v1/health', async () => {
    const fetchMock = stubFetchJson(
      envelope({ checks: [{ name: 'llm', ok: true, detail: '' }], is_healthy: true }),
    )

    await expect(getHealth()).resolves.toEqual({
      checks: [{ name: 'llm', ok: true, detail: '' }],
      is_healthy: true,
    })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/health')
  })

  it('postOptimize 发送 POST 与 JSON body，失败不重试（禁重试语义）', async () => {
    const fetchMock = vi.fn(async (_input: string, _init: RequestInit) => {
      throw new Error('offline')
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(postOptimize({ sentence: '加个按钮', project: 'D:/repo' })).rejects.toBeInstanceOf(
      ApiError,
    )
    expect(fetchMock.mock.calls).toHaveLength(1)
    const init = fetchMock.mock.calls[0]?.[1]
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe(JSON.stringify({ sentence: '加个按钮', project: 'D:/repo' }))
  })

  it('postFollowup 三模式互斥：混合请求体直接拒绝且不发请求', async () => {
    const fetchMock = stubFetchJson(envelope(snapshot))

    await expect(
      postFollowup('sess-1', { answers: { target: 'Foo' }, escape: true }),
    ).rejects.toMatchObject({ kind: 'contract' })
    expect(fetchMock.mock.calls).toHaveLength(0)
  })

  it('postFollowup answers 模式合法放行', async () => {
    const fetchMock = stubFetchJson(envelope(snapshot))

    await expect(
      postFollowup('sess-1', { answers: { target: 'Foo' }, escape: false }),
    ).resolves.toMatchObject({ session_id: 'sess-1' })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/followup/sess-1')
  })

  it('getResult 走 GET /result/{flow_id}（服务端权威恢复）', async () => {
    const fetchMock = stubFetchJson(envelope(snapshot))

    await expect(getResult('sess-1')).resolves.toMatchObject({ state: 'ASKING' })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/result/sess-1')
  })

  it('postFeedback 契约 data 恒为 null，成功返回 void', async () => {
    const fetchMock = stubFetchJson(envelope(null))

    await expect(
      postFeedback({ session_id: 'sess-1', action: 'adopt', variant: 'A' }),
    ).resolves.toBeUndefined()
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/feedback')
  })

  it('scanProject 对 project 参数做 URL 编码', async () => {
    const fetchMock = stubFetchJson(
      envelope({ total_symbols: 12, total_files: 3, kind_counts: { function: 4 } }),
    )

    await scanProject('D:/我的 项目')
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/v1/project/scan?project=${encodeURIComponent('D:/我的 项目')}`,
    )
  })

  it('getBrowse 以 GET 携带编码 path 调用；空 path 不携带参数（驱动器列表）', async () => {
    const fetchMock = stubFetchJson(
      envelope({ path: 'D:/ws/repo', parent: 'D:/ws', entries: [], truncated: false }),
    )

    await expect(getBrowse('D:/我的 项目')).resolves.toMatchObject({ path: 'D:/ws/repo' })
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/v1/project/browse?path=${encodeURIComponent('D:/我的 项目')}`,
    )
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('GET')
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBeUndefined()

    fetchMock.mockClear()
    await getBrowse('')
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/project/browse')
  })
})

describe('api/endpoints 偏好与设置', () => {
  it('getPreference / putPreference 读写 L3 向量', async () => {
    const vector = {
      detail_level: 0.25,
      include_diff: 0.75,
      specify_tests: 0.1,
      max_files_norm: 0.9,
    }
    const fetchMock = stubFetchJson(envelope(vector))

    await expect(getPreference()).resolves.toEqual(vector)
    await expect(putPreference({ detail_level: 0.4 })).resolves.toEqual(vector)
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/v1/preference')
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe('PUT')
    expect(fetchMock.mock.calls[1]?.[1]?.body).toBe(JSON.stringify({ detail_level: 0.4 }))
  })

  it('getHistory 返回会话摘要列表', async () => {
    stubFetchJson(
      envelope([
        {
          session_id: 'sess-1',
          state: 'DONE',
          project: 'D:/repo',
          project_root: 'D:/repo',
          title: '加个导出按钮',
          pinned: false,
          updated_at: '2026-10-12T00:00:00Z',
        },
      ]),
    )

    await expect(getHistory()).resolves.toHaveLength(1)
  })

  it('clearAdoptions 走 DELETE /preference/adoptions 并返回清空条数', async () => {
    const fetchMock = stubFetchJson(envelope({ cleared: 3 }))

    await expect(clearAdoptions()).resolves.toEqual({ cleared: 3 })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/preference/adoptions')
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('DELETE')
  })

  it('getSettings / putSettings 读写设置视图', async () => {
    const fetchMock = stubFetchJson(envelope(settings))

    await expect(getSettings()).resolves.toMatchObject({ locked: { candidate_limit: 25 } })
    await expect(putSettings({ process: { telemetry: false } })).resolves.toMatchObject({
      model_service: { decider: 'auto' },
    })
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/v1/settings')
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe('PUT')
  })

  it('putSettings 多模型段（models + active_model_id）随请求体透传', async () => {
    const fetchMock = stubFetchJson(envelope(settings))

    await putSettings({
      models: [
        { id: 'm-1', label: 'A', provider: 'DeepSeek', base_url: 'https://a', model_id: 'x' },
      ],
      active_model_id: 'm-1',
    })

    const body = String(fetchMock.mock.calls[0]?.[1]?.body)
    expect(body).toContain('"models"')
    expect(body).toContain('"active_model_id":"m-1"')
  })

  it('设置响应契约破坏（telemetry 非布尔）抛契约错误', async () => {
    stubFetchJson(
      envelope({
        ...settings,
        process: { ...settings.process, telemetry: 'yes' },
      }),
    )

    await expect(getSettings()).rejects.toMatchObject({ kind: 'contract' })
  })
})
