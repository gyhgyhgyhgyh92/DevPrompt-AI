import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse, FlowSnapshotResponse } from '../api/types'
import { useOptimizeStore } from '../stores/useOptimizeStore'
import { useHistoryStore } from '../stores/useHistoryStore'
import { OptimizePage } from './OptimizePage'

// 2026-10-19：项目路径改由「浏览器扩展 + native messaging host」的系统对话框取得，
// jsdom 里没有扩展，故 mock 掉桥；页内文件夹浏览器已下线。
vi.mock('../api/nativeFolder', () => ({
  NOT_INSTALLED_HINT: '未安装扩展',
  nativePickErrorText: (e: unknown) => String(e),
  pickFolderViaNative: vi.fn(async () => ({ path: 'D:/ws/repo' })),
}))

/* mock e2e 六路径（tasks.md 6.5）：只 mock api 层返回，store 内部全真实。 */

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'e2e-rid', data }
}

function jsonResponse(payload: unknown) {
  return { status: 200, headers: { get: () => null }, json: async () => payload }
}

type FetchHandler = (input: string, init?: RequestInit) => unknown

/** POST /optimize/stream 的 mock 回应：把载荷包成一帧终态快照（无 thought）。 */
function sseResponse(payload: unknown) {
  const data = (payload as { data?: unknown }).data
  const bytes = new TextEncoder().encode(`data: ${JSON.stringify({ type: 'snapshot', data })}\n\n`)
  let sent = false
  return {
    ok: true,
    status: 200,
    headers: { get: () => null },
    body: {
      getReader: () => ({
        read: async () => {
          if (sent) return { done: true, value: undefined }
          sent = true
          return { done: false, value: bytes }
        },
        releaseLock: () => undefined,
      }),
    },
  }
}

function stubFetch(handler: FetchHandler) {
  const mock = vi.fn(async (input: string, init?: RequestInit) => {
    const payload = handler(input, init)
    // 2026-11-03：答复也走流式（/followup/{id}/stream），同样按 SSE 帧返回
    const isStream = input.includes('/optimize/stream') || input.includes('/followup/')
    return isStream ? sseResponse(payload) : jsonResponse(payload)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

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

const rankingMarked = {
  variant: 'B',
  gap: 0.25,
  confidence: 0.9,
  marked: true,
  reason: '分差明显',
  fit: 0.8,
  total: 0.75,
}

function snapshotFixture(overrides: Partial<FlowSnapshotResponse> = {}): FlowSnapshotResponse {
  return {
    session_id: 'sess-1',
    state: 'ASKING',
    status: 'ask',
    message: '',
    evidence_stale: false,
    reply_text: '',
    questions: [],
    cleared: [],
    variants: [],
    ranking: null,
    ...overrides,
  }
}

const threeVariants = [
  { title: '保守方案', body: 'body-A', level: 'A', changes: ['改一'] },
  { title: '标准方案', body: 'body-B', level: 'B', changes: ['改二'] },
  { title: '激进方案', body: 'body-C', level: 'C', changes: ['改三'] },
]

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
  useHistoryStore.getState().reset()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('mock e2e 六路径', () => {
  it('① 正常三套 + 推荐标记：三卡同屏、徽章与品牌边框命中后端指定档位', async () => {
    const user = userEvent.setup()
    const done = snapshotFixture({
      status: 'done',
      state: 'DONE',
      variants: threeVariants,
      ranking: rankingMarked,
    })
    stubApi([
      {
        match: '/project/browse',
        payload: envelope({ path: 'D:/ws/repo', parent: 'D:/ws', entries: [], truncated: false }),
      },
      { match: '/optimize', payload: envelope(done) },
      { match: '/history', payload: envelope([]) },
    ])

    renderPage()
    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))
    await screen.findByText('repo')
    await user.type(screen.getByRole('textbox', { name: '优化原句' }), '加个导出按钮')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(await screen.findByRole('article', { name: '方案 A' })).toBeTruthy()
    expect(screen.getByRole('article', { name: '方案 B' })).toBeTruthy()
    expect(screen.getByRole('article', { name: '方案 C' })).toBeTruthy()
    expect(screen.getByText(/【推荐】B/)).toBeTruthy()
    expect(screen.getByRole('article', { name: '方案 B' }).className).toContain(
      'prompt-card--recommended',
    )
    expect(screen.getByText('body-B')).toBeTruthy()

    // 对话流形态：用户气泡（右对齐浅灰）+ AI 回复块 + 分隔线 + 由 AI 生成
    const bubble = screen.getByText('加个导出按钮')
    expect(bubble.className).toContain('chat-user-bubble')
    expect(screen.getByRole('article', { name: 'AI 回复' })).toBeTruthy()
    expect(document.querySelector('.chat-reply__divider')).not.toBeNull()
    // 底部图标行（复制/重试/赞踩/AI 生成）已按用户要求移除
    expect(document.querySelector('.chat-reply__actions')).toBeNull()
  })

  it('② 反问 → 批量答复 → DONE：澄清卡数量与 answers 提交', async () => {
    const user = userEvent.setup()
    const asked = snapshotFixture({
      questions: [
        {
          key: 'target',
          reason: '缺目标定位',
          best_guess: 'build()',
          ask: '改哪里？',
          header: '',
          options: [],
          multi_select: false,
        },
        {
          key: 'scope',
          reason: '缺改造范围',
          best_guess: '仅首页',
          ask: '改多大范围？',
          header: '',
          options: [],
          multi_select: false,
        },
      ],
      cleared: ['lang'],
    })
    const done = snapshotFixture({
      status: 'done',
      state: 'DONE',
      variants: threeVariants,
      ranking: rankingMarked,
    })
    const mock = stubApi([
      {
        match: '/project/browse',
        payload: envelope({ path: 'D:/ws/repo', parent: 'D:/ws', entries: [], truncated: false }),
      },
      { match: '/optimize', payload: envelope(asked) },
      { match: '/followup', payload: envelope(done) },
      { match: '/history', payload: envelope([]) },
    ])

    renderPage()
    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))
    await screen.findByText('repo')
    await user.type(screen.getByRole('textbox', { name: '优化原句' }), '加个导出按钮')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(await screen.findByText('缺目标定位')).toBeTruthy()
    expect(screen.getAllByRole('textbox', { name: '输入自定义回答' })).toHaveLength(2)
    const inputs = screen.getAllByRole('textbox', { name: '输入自定义回答' })
    await user.type(inputs[0] as HTMLInputElement, 'build()')
    await user.type(inputs[1] as HTMLInputElement, '仅首页')
    await user.click(screen.getByRole('button', { name: '提交' }))

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/followup/sess-1'))
      expect(String(call?.[1]?.body)).toContain('"answers"')
      expect(String(call?.[1]?.body)).toContain('build()')
    })
    expect(await screen.findByRole('article', { name: '方案 B' })).toBeTruthy()
    expect(screen.getByText(/【推荐】B/)).toBeTruthy()
    expect(screen.getByRole('article', { name: 'AI 回复' })).toBeTruthy()
  })

  it('③ ASKING → 逃生 → 单套 A 无 ranking：不显推荐徽章与评分（MUST-28）', async () => {
    const user = userEvent.setup()
    const asked = snapshotFixture({
      questions: [
        {
          key: 'target',
          reason: '缺目标定位',
          best_guess: 'build()',
          ask: '改哪里？',
          header: '',
          options: [],
          multi_select: false,
        },
      ],
    })
    const escaped = snapshotFixture({
      status: 'done',
      state: 'DONE',
      variants: [{ title: '保守方案', body: 'body-A', level: 'A', changes: [] }],
      ranking: null,
    })
    const mock = stubApi([
      {
        match: '/project/browse',
        payload: envelope({ path: 'D:/ws/repo', parent: 'D:/ws', entries: [], truncated: false }),
      },
      { match: '/optimize', payload: envelope(asked) },
      { match: '/followup', payload: envelope(escaped) },
      { match: '/history', payload: envelope([]) },
    ])

    renderPage()
    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))
    await screen.findByText('repo')
    await user.type(screen.getByRole('textbox', { name: '优化原句' }), '加个导出按钮')
    await user.click(screen.getByRole('button', { name: '发送' }))

    await user.click(await screen.findByRole('button', { name: '直接生成' }))

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/followup/sess-1'))
      expect(String(call?.[1]?.body)).toContain('"escape":true')
    })
    expect(await screen.findByRole('article', { name: '方案 A' })).toBeTruthy()
    expect(screen.queryByRole('article', { name: '方案 B' })).toBeNull()
    expect(screen.queryByText(/【推荐】/)).toBeNull()
    expect(screen.queryByText('评分明细')).toBeNull()
    expect(screen.getByText('后端未产生推荐视图，请人工选择')).toBeTruthy()
  })

  it('④ 护栏裁决「继续追问」：guardrail_action=continue', async () => {
    const user = userEvent.setup()
    const seed = snapshotFixture({
      status: 'guardrail',
      state: 'ASKING',
      cleared: ['target'],
      questions: [
        {
          key: 'scope',
          reason: '缺改造范围',
          best_guess: '仅首页',
          ask: '改多大范围？',
          header: '',
          options: [],
          multi_select: false,
        },
      ],
    })
    useOptimizeStore.getState().applySnapshot(seed)
    const mock = stubApi([
      { match: '/followup', payload: envelope(snapshotFixture({ status: 'ask' })) },
      { match: '/result', payload: envelope(seed) },
    ])

    renderPage()
    await user.click(screen.getByRole('button', { name: '继续追问' }))

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/followup/sess-1'))
      expect(String(call?.[1]?.body)).toContain('"guardrail_action":"continue"')
    })
  })

  it('⑤ 护栏裁决「直接生成」：guardrail_action=generate', async () => {
    const user = userEvent.setup()
    const seed = snapshotFixture({
      status: 'guardrail',
      state: 'ASKING',
      cleared: ['target'],
    })
    useOptimizeStore.getState().applySnapshot(seed)
    const done = snapshotFixture({ status: 'done', state: 'DONE', variants: threeVariants })
    const mock = stubApi([
      { match: '/followup', payload: envelope(done) },
      { match: '/result', payload: envelope(seed) },
    ])

    renderPage()
    await user.click(screen.getByRole('button', { name: '直接生成（保守版）' }))

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/followup/sess-1'))
      expect(String(call?.[1]?.body)).toContain('"guardrail_action":"generate"')
    })
    expect(await screen.findByRole('article', { name: '方案 A' })).toBeTruthy()
  })

  it('⑥ 刷新恢复：GET /result 复原三套与 ranking 一致', async () => {
    const restored = snapshotFixture({
      status: 'done',
      state: 'DONE',
      variants: threeVariants,
      ranking: rankingMarked,
    })
    useOptimizeStore.getState().applySnapshot(snapshotFixture())
    stubApi([
      { match: '/result/sess-1', payload: envelope(restored) },
      { match: '/history', payload: envelope([]) },
    ])

    renderPage()

    expect(await screen.findByRole('article', { name: '方案 A' })).toBeTruthy()
    expect(screen.getByRole('article', { name: '方案 B' })).toBeTruthy()
    expect(screen.getByRole('article', { name: '方案 C' })).toBeTruthy()
    expect(screen.getByText(/【推荐】B/)).toBeTruthy()
    const recommended = screen.getByRole('article', { name: '方案 B' })
    expect(recommended.className).toContain('prompt-card--recommended')
    // 刷新恢复：AI 回复块存在（旧会话无原句 → 无用户气泡，仅显状态）
    expect(screen.getByRole('article', { name: 'AI 回复' })).toBeTruthy()
    expect(document.querySelector('.chat-user-bubble')).toBeNull()
  })
})
