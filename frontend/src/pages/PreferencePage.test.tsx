import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse, PreferenceVectorPayload } from '../api/types'
import { usePreferenceStore } from '../stores/usePreferenceStore'
import { PreferencePage } from './PreferencePage'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

function vectorFixture(overrides: Partial<PreferenceVectorPayload> = {}): PreferenceVectorPayload {
  return {
    detail_level: 0.25,
    include_diff: 0.75,
    specify_tests: 0.1,
    max_files_norm: 0.9,
    ...overrides,
  }
}

/** 按方法分派的 fetch 桩：GET 读向量、PUT 写入并回填。 */
function stubFetch(handler: (method: string, body: unknown) => { status?: number; data: unknown }) {
  return vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    const { status = 200, data } = handler(method, body)
    return {
      status,
      headers: { get: () => null },
      json: async () => envelope(data),
    }
  })
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  usePreferenceStore.getState().reset()
})

describe('PreferencePage 偏好四维独立编辑', () => {
  it('渲染四维滑杆（中文标签）与当前生效值', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch((method) => ({ data: method === 'GET' ? vectorFixture() : null })),
    )

    render(
      <MemoryRouter>
        <PreferencePage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: '偏好管理' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '← 工作台' })).toBeTruthy()
    for (const label of ['细节程度', '包含 diff', '指定测试', '涉及文件范围']) {
      expect(screen.getByLabelText(label)).toBeTruthy()
    }
    // Slider 以两位小数回显当前值
    expect(screen.getByText('0.25')).toBeTruthy()
    expect(screen.getByText('0.75')).toBeTruthy()
  })

  it('契约破坏（data 为 null）视为读取失败而非空数据', async () => {
    // GET /preference 契约要求返回完整 vector 对象；null/缺字段会被 Zod 拒绝，
    // 属契约破坏（SHOULD-10「Zod 对畸形响应的拒绝」），不得静默渲染为「无偏好」
    vi.stubGlobal(
      'fetch',
      stubFetch((method) => ({ data: method === 'GET' ? null : null })),
    )

    render(
      <MemoryRouter>
        <PreferencePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/偏好读取失败/)).toBeTruthy()
    expect(screen.queryByLabelText('细节程度')).toBeNull()
  })

  it('读取失败时渲染失败提示与手动重载入口（不自动重试）', async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error('network down')
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <MemoryRouter>
        <PreferencePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/偏好读取失败/)).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    vi.stubGlobal(
      'fetch',
      stubFetch((method) => ({ data: method === 'GET' ? vectorFixture() : null })),
    )
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByLabelText('细节程度')).toBeTruthy()
  })

  it('未修改时保存按钮禁用', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch((method) => ({ data: method === 'GET' ? vectorFixture() : null })),
    )

    render(
      <MemoryRouter>
        <PreferencePage />
      </MemoryRouter>,
    )

    await screen.findByLabelText('细节程度')
    expect((screen.getByRole('button', { name: '保存偏好' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect((screen.getByRole('button', { name: '放弃修改' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
  })

  it('拖动滑杆后保存：调 PUT /preference 并以服务端返回值回填', async () => {
    let serverVector = vectorFixture()
    const calls: { method: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      stubFetch((method, body) => {
        calls.push({ method, body })
        if (method === 'PUT') {
          serverVector = body as PreferenceVectorPayload
          return { data: serverVector }
        }
        return { data: serverVector }
      }),
    )

    render(
      <MemoryRouter>
        <PreferencePage />
      </MemoryRouter>,
    )

    const slider = (await screen.findByLabelText('细节程度')) as HTMLInputElement
    fireEvent.change(slider, { target: { value: '0.4' } })

    // 拖动本身不得发请求（显式保存，避免每次拖动打有副作用端点，MUST-15）
    expect(calls.filter((call) => call.method === 'PUT')).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: '保存偏好' }))

    await waitFor(() => {
      expect(calls.filter((call) => call.method === 'PUT')).toHaveLength(1)
    })
    const put = calls.find((call) => call.method === 'PUT')
    expect(put?.body).toMatchObject({ detail_level: 0.4 })
    expect(await screen.findByText('偏好已保存')).toBeTruthy()
    // 保存成功后草稿与基准同步，按钮回到禁用态
    expect((screen.getByRole('button', { name: '保存偏好' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect(usePreferenceStore.getState().vector).toEqual(serverVector)
  })

  it('放弃修改可恢复为服务端当前值', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch((method) => ({ data: method === 'GET' ? vectorFixture() : null })),
    )

    render(
      <MemoryRouter>
        <PreferencePage />
      </MemoryRouter>,
    )

    const slider = (await screen.findByLabelText('细节程度')) as HTMLInputElement
    fireEvent.change(slider, { target: { value: '0.9' } })
    expect((screen.getByRole('button', { name: '保存偏好' }) as HTMLButtonElement).disabled).toBe(
      false,
    )

    fireEvent.click(screen.getByRole('button', { name: '放弃修改' }))
    expect((screen.getByRole('button', { name: '保存偏好' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect((screen.getByLabelText('细节程度') as HTMLInputElement).value).toBe('0.25')
  })

  it('保存失败时给出提示、保留草稿且不自动重试', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (method === 'PUT') throw new Error('rejected')
      return {
        status: 200,
        headers: { get: () => null },
        json: async () => envelope(vectorFixture()),
      }
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <MemoryRouter>
        <PreferencePage />
      </MemoryRouter>,
    )

    const slider = (await screen.findByLabelText('细节程度')) as HTMLInputElement
    fireEvent.change(slider, { target: { value: '0.6' } })
    fireEvent.click(screen.getByRole('button', { name: '保存偏好' }))

    expect(await screen.findByText('保存失败')).toBeTruthy()
    // 草稿保留，用户可修正后重试；失败不自动重发（MUST-15）
    expect((screen.getByLabelText('细节程度') as HTMLInputElement).value).toBe('0.6')
    const putCalls = fetchMock.mock.calls.filter((call) => call[1]?.method === 'PUT')
    expect(putCalls).toHaveLength(1)
  })

  it('保存进行中禁用保存按钮，避免重复提交', async () => {
    // definite assignment：`resolve` 在 executor 内赋值，TS 控制流分析不会把它收窄为null
    let resolvePut!: (value: PreferenceVectorPayload) => void
    const pendingPut = new Promise<PreferenceVectorPayload>((resolve) => {
      resolvePut = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        if (method === 'PUT') {
          const saved = await pendingPut
          return { status: 200, headers: { get: () => null }, json: async () => envelope(saved) }
        }
        return {
          status: 200,
          headers: { get: () => null },
          json: async () => envelope(vectorFixture()),
        }
      }),
    )

    render(
      <MemoryRouter>
        <PreferencePage />
      </MemoryRouter>,
    )

    const slider = (await screen.findByLabelText('细节程度')) as HTMLInputElement
    fireEvent.change(slider, { target: { value: '0.3' } })
    fireEvent.click(screen.getByRole('button', { name: '保存偏好' }))

    const saving = await screen.findByRole('button', { name: '保存中…' })
    expect((saving as HTMLButtonElement).disabled).toBe(true)

    resolvePut(vectorFixture({ detail_level: 0.3 }))
    expect(await screen.findByText('偏好已保存')).toBeTruthy()
  })
})
