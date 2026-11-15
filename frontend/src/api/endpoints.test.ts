import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  compareObsTraces,
  createObsReplay,
  getHealth,
  getHistory,
  getResult,
  getSettings,
  postFollowup,
  postOptimize,
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
  variant: {
    title: '标准方案',
    body: 'b',
    changes: [],
    claims: [],
    fallback: false,
  },
}

const settings = {
  models: [],
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.example.com',
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
  observability: {
    trace_enabled: true,
    trace_retention_days: 30,
    metrics_enabled: true,
    replay_enabled: true,
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

    await expect(
      postOptimize({ sentence: '加个按钮', project: 'D:/repo', base_turn_id: '' }),
    ).rejects.toBeInstanceOf(ApiError)
    expect(fetchMock.mock.calls).toHaveLength(1)
    const init = fetchMock.mock.calls[0]?.[1]
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe(
      JSON.stringify({ sentence: '加个按钮', project: 'D:/repo', base_turn_id: '' }),
    )
  })

  it('Replay 请求体只编码一次（不得二次 JSON.stringify）', async () => {
    const createMock = stubFetchJson(
      envelope({ run: { run_id: 'r1', status: 'running' }, nodes: [] }),
    )
    await createObsReplay({ mode: 'verify', left_trace_id: 't1' })
    const createBody = JSON.parse(String(createMock.mock.calls[0]?.[1]?.body))
    expect(createBody).toEqual({ mode: 'verify', left_trace_id: 't1' })

    vi.unstubAllGlobals()
    const compareMock = stubFetchJson(envelope({ nodes: [], final: {} }))
    await compareObsTraces('t1', 't2')
    const compareBody = JSON.parse(String(compareMock.mock.calls[0]?.[1]?.body))
    expect(compareBody).toEqual({ left_trace_id: 't1', right_trace_id: 't2' })
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

  it('scanProject 对 project 参数做 URL 编码', async () => {
    const fetchMock = stubFetchJson(
      envelope({ total_symbols: 12, total_files: 3, kind_counts: { function: 4 } }),
    )

    await scanProject('D:/我的 项目')
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/v1/project/scan?project=${encodeURIComponent('D:/我的 项目')}`,
    )
  })
})

describe('api/endpoints 偏好与设置', () => {
  it('getHistory 返回分页会话摘要', async () => {
    stubFetchJson(
      envelope({
        items: [
          {
            session_id: 'sess-1',
            state: 'DONE',
            project: 'D:/repo',
            project_root: 'D:/repo',
            title: '加个导出按钮',
            pinned: false,
            updated_at: '2026-10-12T00:00:00Z',
          },
        ],
        has_more: true,
        limit: 50,
        offset: 0,
      }),
    )

    const page = await getHistory()
    expect(page.items).toHaveLength(1)
    expect(page.has_more).toBe(true)
    expect(page.items[0]?.session_id).toBe('sess-1')
  })

  it('getHistory 透传分页参数到查询串', async () => {
    const fetchMock = stubFetchJson(envelope({ items: [], has_more: false, limit: 20, offset: 40 }))

    await getHistory({ limit: 20, offset: 40 })

    expect(fetchMock.mock.calls[0]?.[0]).toContain('limit=20')
    expect(fetchMock.mock.calls[0]?.[0]).toContain('offset=40')
  })

  it('getSettings / putSettings 读写设置视图', async () => {
    const fetchMock = stubFetchJson(envelope(settings))

    await expect(getSettings()).resolves.toMatchObject({ locked: { candidate_limit: 25 } })
    await expect(putSettings({ process: { telemetry: false } })).resolves.toMatchObject({
      model_service: { model_id: 'demo' },
    })
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/v1/settings')
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe('PUT')
  })

  it('putSettings 多模型段（models + active_model_id）随请求体透传', async () => {
    const fetchMock = stubFetchJson(envelope(settings))

    await putSettings({
      models: [{ id: 'm-1', provider_id: 'p-1', model_id: 'x' }],
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
