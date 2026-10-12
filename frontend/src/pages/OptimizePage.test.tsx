import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse, FlowSnapshotResponse } from '../api/types'
import { useOptimizeStore } from '../stores/useOptimizeStore'
import { usePreferenceStore } from '../stores/usePreferenceStore'
import { OptimizePage } from './OptimizePage'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

function jsonResponse(payload: unknown) {
  return {
    status: 200,
    headers: { get: () => null },
    json: async () => payload,
  }
}

type FetchHandler = (input: string, init?: RequestInit) => unknown

function stubFetch(handler: FetchHandler) {
  const mock = vi.fn(async (input: string, init?: RequestInit) =>
    jsonResponse(handler(input, init)),
  )
  vi.stubGlobal('fetch', mock)
  return mock
}

/** 按 URL 片段路由的 api mock（不 mock store 内部，只替换 api 层返回）。 */
function stubApi(routes: readonly { match: string; payload: unknown }[]) {
  return stubFetch((input) => {
    const found = routes.find((route) => input.includes(route.match))
    return found ? found.payload : envelope(null)
  })
}

class MockEventSource {
  static instances: MockEventSource[] = []
  readonly url: string
  isClosed = false
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  close(): void {
    this.isClosed = true
  }
}

const vectorFixture = {
  detail_level: 0.25,
  include_diff: 0.75,
  specify_tests: 0.1,
  max_files_norm: 0.9,
}

function snapshotFixture(overrides: Partial<FlowSnapshotResponse> = {}): FlowSnapshotResponse {
  return {
    session_id: 'sess-1',
    state: 'ASKING',
    status: 'ask',
    message: '',
    questions: [],
    cleared: [],
    variants: [],
    ranking: null,
    ...overrides,
  }
}

const rankingFixture = {
  variant: 'B',
  gap: 0.25,
  confidence: 0.9,
  marked: true,
  reason: '分差明显',
  fit: 0.8,
  pref: 0.7,
  total: 0.75,
}

function renderPage() {
  return render(
    <MemoryRouter>
      <OptimizePage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  MockEventSource.instances = []
  vi.stubGlobal('EventSource', MockEventSource)
  useOptimizeStore.getState().reset()
  usePreferenceStore.getState().reset()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('OptimizePage 三栏工作台', () => {
  it('初始态渲染居中 ConsoleInput（无侧栏 / 无结果区）', () => {
    stubApi([{ match: '/preference', payload: envelope(vectorFixture) }])

    renderPage()

    expect(screen.getByRole('textbox', { name: '优化原句' })).toBeTruthy()
    expect(screen.queryByRole('complementary', { name: '上下文面板' })).toBeNull()
  })

  it('上下文信息以内嵌小节渲染目标定位与取证事实', () => {
    const seed = snapshotFixture({
      target: { name: 'build', path: 'src/app.py', line: 12 },
      facts: [
        { key: 'fact_a', passed: true, evidence: '定位到 build' },
        { key: 'fact_b', passed: false, evidence: '共 3 处调用' },
      ],
    })
    useOptimizeStore.getState().applySnapshot(seed)
    stubApi([{ match: '/result', payload: envelope(seed) }])

    renderPage()

    const panel = screen.getByRole('region', { name: '上下文信息' })
    expect(within(panel).getByText('build@src/app.py:12')).toBeTruthy()
    expect(within(panel).getByText('fact_a')).toBeTruthy()
    expect(within(panel).getByText('✗')).toBeTruthy()
    expect(within(panel).getByText('共 3 处调用')).toBeTruthy()
  })

  it('无流程时渲染启动卡片（原句输入 + 发送 + 选择文件夹）', () => {
    stubApi([{ match: '/preference', payload: envelope(vectorFixture) }])

    renderPage()

    expect(screen.getByRole('textbox', { name: '优化原句' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '发送' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '选择文件夹' })).toBeTruthy()
    expect(screen.queryByText('直接生成（A 保守版 + 待确认清单）')).toBeNull()
  })

  it('提交优化调用 POST /optimize 并切换到反问态', async () => {
    const user = userEvent.setup()
    const asked = snapshotFixture({
      questions: [{ key: 'target', reason: '缺目标定位', best_guess: 'build()', ask: '改哪里？' }],
    })
    const mock = stubApi([
      { match: '/optimize', payload: envelope(asked) },
      { match: '/history', payload: envelope([]) },
    ])

    renderPage()
    await user.click(screen.getByRole('button', { name: '选择文件夹' }))
    await user.type(screen.getByRole('textbox', { name: '项目路径' }), 'D:/ws/repo')
    await user.type(screen.getByRole('textbox', { name: '优化原句' }), '加个导出按钮')
    await user.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/optimize'))
      expect(call?.[1]?.method).toBe('POST')
      expect(String(call?.[1]?.body)).toContain('"sentence":"加个导出按钮"')
    })
    expect(await screen.findByText('缺目标定位')).toBeTruthy()
    expect(screen.getByRole('button', { name: '提交答复' })).toBeTruthy()
  })
})

describe('OptimizePage 三态容器', () => {
  it('反问态渲染澄清卡、已澄清 chips 与逃生按钮', () => {
    const seed = snapshotFixture({
      questions: [
        { key: 'scope', reason: '缺改造范围', best_guess: '仅首页', ask: '改多大范围？' },
      ],
      cleared: ['target'],
    })
    useOptimizeStore.getState().applySnapshot(seed)
    stubApi([{ match: '/result', payload: envelope(seed) }])

    renderPage()

    expect(screen.getByText('缺改造范围')).toBeTruthy()
    expect(screen.getByText('scope')).toBeTruthy()
    expect(screen.getByText('target')).toBeTruthy()
    expect(screen.getByRole('button', { name: /直接生成（A 保守版/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '采纳 A' })).toBeNull()
  })

  it('escape 逃生按钮以 escape 模式调用 POST /followup', async () => {
    const user = userEvent.setup()
    const seed = snapshotFixture()
    useOptimizeStore.getState().applySnapshot(seed)
    const mock = stubApi([
      { match: '/followup', payload: envelope(snapshotFixture({ status: 'done', state: 'DONE' })) },
      { match: '/result', payload: envelope(seed) },
    ])

    renderPage()
    await user.click(screen.getByRole('button', { name: /直接生成（A 保守版/ }))

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/followup/sess-1'))
      expect(call?.[1]?.method).toBe('POST')
      expect(String(call?.[1]?.body)).toContain('"escape":true')
    })
  })

  it('结果态在后端标记推荐时显示【推荐】与置信度', () => {
    const seed = snapshotFixture({
      status: 'done',
      state: 'DONE',
      variants: [
        { title: '保守方案', body: 'b1', level: 'A', changes: ['改动一'] },
        { title: '标准方案', body: 'b2', level: 'B', changes: [] },
      ],
      ranking: rankingFixture,
    })
    useOptimizeStore.getState().applySnapshot(seed)
    stubApi([{ match: '/result', payload: envelope(seed) }])

    renderPage()

    expect(screen.getByText('标准方案')).toBeTruthy()
    expect(screen.getByText('改动一')).toBeTruthy()
    expect(screen.getByText(/【推荐】B/)).toBeTruthy()
    expect(screen.getByText(/0.9/)).toBeTruthy()
  })

  it('结果态未标记推荐时展示后端 reason 文案（不静默）', () => {
    const seed = snapshotFixture({
      status: 'done',
      state: 'DONE',
      ranking: { ...rankingFixture, marked: false, reason: '三套适配度接近，建议人工选择' },
    })
    useOptimizeStore.getState().applySnapshot(seed)
    stubApi([{ match: '/result', payload: envelope(seed) }])

    renderPage()

    expect(screen.getByText('三套适配度接近，建议人工选择')).toBeTruthy()
    expect(screen.queryByText(/【推荐】/)).toBeNull()
  })

  it('反馈按钮以 adopt 动作调用 POST /feedback', async () => {
    const user = userEvent.setup()
    const seed = snapshotFixture({
      status: 'done',
      state: 'DONE',
      variants: [{ title: '保守方案', body: 'b1', level: 'A', changes: [] }],
    })
    useOptimizeStore.getState().applySnapshot(seed)
    const mock = stubApi([
      { match: '/feedback', payload: envelope(null) },
      { match: '/result', payload: envelope(seed) },
    ])

    renderPage()
    await user.click(screen.getByRole('button', { name: '采纳 A' }))

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/feedback'))
      expect(call?.[1]?.method).toBe('POST')
      expect(String(call?.[1]?.body)).toContain('"action":"adopt"')
      expect(String(call?.[1]?.body)).toContain('"variant":"A"')
    })
  })
})

describe('OptimizePage 恢复与侧栏', () => {
  it('挂载时经 GET /result/{flow_id} 做服务端权威恢复', async () => {
    useOptimizeStore.getState().applySnapshot(snapshotFixture())
    const mock = stubApi([
      {
        match: '/result/sess-1',
        payload: envelope(snapshotFixture({ state: 'CONFIRMING', status: 'ask' })),
      },
    ])

    renderPage()

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/result/sess-1'))
      expect(call?.[1]?.method).toBe('GET')
    })
    expect(await screen.findByText('CONFIRMING')).toBeTruthy()
  })

  it('优化页不再内嵌会话侧栏（已迁至 AppShell）', async () => {
    stubApi([{ match: '/preference', payload: envelope(vectorFixture) }])

    renderPage()

    expect(screen.queryByRole('complementary', { name: '会话侧栏' })).toBeNull()
    expect(await screen.findByRole('textbox', { name: '优化原句' })).toBeTruthy()
  })
})
