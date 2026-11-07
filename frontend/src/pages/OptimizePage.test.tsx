import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  notInstalledHint: () => '未安装扩展',
  nativePickErrorText: (e: unknown) => String(e),
  pickFolderViaNative: vi.fn(async () => ({ path: 'D:/ws/repo' })),
}))

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

/** 可控流：先吐 thought / action 帧，快照帧挂起直到 release()，用于断言「思考中」的中间态。 */
function gatedStream(
  thoughts: string[],
  actions: readonly { title: string; detail: string; scope: string }[],
  payload: unknown,
) {
  const data = (payload as { data?: unknown }).data
  const encoder = new TextEncoder()
  const thoughtFrames = [
    ...thoughts.map((text) =>
      encoder.encode(`data: ${JSON.stringify({ type: 'thought', text })}\n\n`),
    ),
    ...actions.map((action) =>
      encoder.encode(`data: ${JSON.stringify({ type: 'action', ...action })}\n\n`),
    ),
  ]
  const snapshotFrame = encoder.encode(`data: ${JSON.stringify({ type: 'snapshot', data })}\n\n`)
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let step = 0
  let sent = false
  return {
    release: () => release(),
    response: {
      ok: true,
      status: 200,
      headers: { get: () => null },
      body: {
        getReader: () => ({
          read: async () => {
            if (step < thoughtFrames.length) {
              const value = thoughtFrames[step]
              step += 1
              return { done: false, value }
            }
            if (sent) return { done: true, value: undefined }
            await gate
            sent = true
            return { done: false, value: snapshotFrame }
          },
          releaseLock: () => undefined,
        }),
      },
    },
  }
}

/** 带阶段标签的可控流：回答反问后的 CONFIRMING→GENERATING 推进（2026-11-03）。 */
function gatedPhasedStream(frames: readonly Record<string, unknown>[], payload: unknown) {
  const encoder = new TextEncoder()
  const chunks = [
    ...frames.map((frame) => encoder.encode(`data: ${JSON.stringify(frame)}\n\n`)),
    encoder.encode(
      `data: ${JSON.stringify({ type: 'snapshot', data: (payload as { data?: unknown }).data })}\n\n`,
    ),
  ]
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let step = 0
  let sent = false
  return {
    release: () => release(),
    response: {
      ok: true,
      status: 200,
      headers: { get: () => null },
      body: {
        getReader: () => ({
          read: async () => {
            if (step < chunks.length - 1) {
              const value = chunks[step]
              step += 1
              return { done: false, value }
            }
            if (sent) return { done: true, value: undefined }
            await gate
            sent = true
            return { done: false, value: chunks[chunks.length - 1] }
          },
          releaseLock: () => undefined,
        }),
      },
    },
  }
}

function stubFetch(handler: FetchHandler) {
  const mock = vi.fn(async (input: string, init?: RequestInit) => {
    const payload = handler(input, init)
    const isStream = input.includes('/optimize/stream') || input.includes('/followup/')
    return isStream ? sseResponse(payload) : jsonResponse(payload)
  })
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

const rankingFixture = {
  variant: 'B',
  gap: 0.25,
  confidence: 0.9,
  marked: true,
  reason: '分差明显',
  fit: 0.8,
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
  useHistoryStore.getState().reset()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('OptimizePage 三栏工作台', () => {
  it('初始态渲染居中 ConsoleInput（无侧栏 / 无结果区）', () => {
    stubApi([])

    renderPage()

    expect(screen.getByRole('textbox', { name: '优化原句' })).toBeTruthy()
    expect(screen.queryByRole('complementary', { name: '上下文面板' })).toBeNull()
  })

  it('无流程时渲染启动卡片（原句输入 + 发送 + 选择文件夹（本地））', () => {
    stubApi([])

    renderPage()

    expect(screen.getByRole('textbox', { name: '优化原句' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '发送' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '选择文件夹（本地）' })).toBeTruthy()
    expect(screen.queryByText('直接生成')).toBeNull()
  })

  it('提交优化调用 POST /optimize 并切换到反问态', async () => {
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
    const mock = stubApi([
      {
        match: '/project/browse',
        payload: envelope({ path: 'D:/ws/repo', parent: 'D:/ws', entries: [], truncated: false }),
      },
      { match: '/optimize', payload: envelope(asked) },
      { match: '/history', payload: envelope([]) },
    ])

    renderPage()
    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))
    await screen.findByText('repo')
    await user.type(screen.getByRole('textbox', { name: '优化原句' }), '加个导出按钮')
    await user.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/optimize'))
      expect(call?.[1]?.method).toBe('POST')
      expect(String(call?.[1]?.body)).toContain('"sentence":"加个导出按钮"')
    })
    expect(await screen.findByText('缺目标定位')).toBeTruthy()
    expect(screen.getByRole('button', { name: '提交' })).toBeTruthy()
  })

  it('结果态输入区常驻，第二轮提交带上一次 session_id（多轮）', async () => {
    const user = userEvent.setup()
    const done = snapshotFixture({ status: 'done', state: 'DONE' })
    const mock = stubApi([
      { match: '/optimize', payload: envelope(done) },
      { match: '/history', payload: envelope([]) },
    ])
    // 模拟「已有一轮结果」：直接种快照，页面上应有常驻输入区
    useOptimizeStore.getState().applySnapshot(done)

    renderPage()

    const input = await screen.findByRole('textbox', { name: '优化原句' })
    await user.type(input, '再加一个禁用态')
    await user.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      const call = mock.mock.calls.filter(([url]) => String(url).includes('/optimize')).at(-1)
      const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as { session_id?: string }
      expect(body.session_id).toBe('sess-1')
    })
  })

  it('结果态对话区贴底跟随；用户上滚后新内容不再强拉（对齐 Codex 滚动行为）', async () => {
    const done = snapshotFixture({ status: 'done', state: 'DONE' })
    stubApi([{ match: '/history', payload: envelope([]) }])
    useOptimizeStore.getState().applySnapshot(done)
    renderPage()

    const thread = await waitFor(() => {
      const node = document.querySelector('[class*="optimize-page__thread"]')
      if (node === null) throw new Error('对话流滚动区未渲染')
      return node as HTMLElement
    })
    Object.defineProperty(thread, 'scrollHeight', { value: 500, configurable: true })
    Object.defineProperty(thread, 'clientHeight', { value: 200, configurable: true })

    // 仍在底部附近（距底 < 80px）：新内容到达 → 跟随到底
    thread.scrollTop = 320
    fireEvent.scroll(thread)
    useOptimizeStore.getState().applySnapshot({ ...done, message: '第二轮结论' })
    await waitFor(() => expect(thread.scrollTop).toBe(500))

    // 上滚 300px 回看历史：新内容不得把视口拽到底
    thread.scrollTop = 0
    fireEvent.scroll(thread)
    useOptimizeStore.getState().applySnapshot({ ...done, message: '第三轮结论' })
    await waitFor(() => expect(thread.scrollTop).toBe(0))
  })

  it('提交即切思考视图，快照到达后折叠思考并显示反问卡', async () => {
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
    const gate = gatedStream(
      ['正在检索相关代码'],
      [{ title: '检索符号', detail: 'rg -n Foo --glob src/a.ts', scope: '命中 2 行' }],
      envelope(asked),
    )
    const mock = vi.fn(async (input: string) =>
      input.includes('/optimize/stream') ? gate.response : jsonResponse(envelope(null)),
    )
    vi.stubGlobal('fetch', mock)

    renderPage()
    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))
    await screen.findByText('repo')
    await user.type(screen.getByRole('textbox', { name: '优化原句' }), '加个导出按钮')
    await user.click(screen.getByRole('button', { name: '发送' }))

    // 尚未收到快照：步骤时间轴已出现，过程挂在对应步骤下，反问卡还不该出现
    expect(document.querySelector('[class*="chat-reply__phases"]')).not.toBeNull()
    expect(await screen.findByText(/正在检索相关代码/)).toBeTruthy()
    expect(await screen.findByText('命令已执行')).toBeTruthy()
    expect(screen.queryByText('缺目标定位')).toBeNull()

    gate.release()

    expect(await screen.findByText('缺目标定位')).toBeTruthy()
    // 反问出现后过程仍保持展开（2026-11-07 裁定：结束不自动折叠），折叠按钮可用
    expect(document.querySelector('[class*="chat-reply__phases"]')).not.toBeNull()
    const toggle = screen.getByRole('button', { name: /折叠过程/ })
    await user.click(toggle)
    expect(document.querySelector('[class*="chat-reply__phases"]')).toBeNull()
    expect(screen.getByText(/个动作 ·/)).toBeTruthy()
  })
})

describe('OptimizePage 三态容器', () => {
  it('反问态渲染澄清卡、已澄清 chips 与逃生按钮', () => {
    const seed = snapshotFixture({
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
      cleared: ['target'],
    })
    useOptimizeStore.getState().applySnapshot(seed)
    stubApi([{ match: '/result', payload: envelope(seed) }])

    renderPage()

    expect(screen.getByText('缺改造范围')).toBeTruthy()
    expect(screen.getByText('scope')).toBeTruthy()
    expect(screen.getByText('target')).toBeTruthy()
    expect(screen.getByRole('button', { name: /直接生成/ })).toBeTruthy()
    expect(document.querySelector('[class*="chat-suggestions"]')).toBeNull()
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
    await user.click(screen.getByRole('button', { name: /直接生成/ }))

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/followup/sess-1'))
      expect(call?.[1]?.method).toBe('POST')
      expect(String(call?.[1]?.body)).toContain('"escape":true')
    })
  })

  it('回答反问后走流式端点：展示重新研判过程并推进阶段（2026-11-03）', async () => {
    const user = userEvent.setup()
    const asked = snapshotFixture({
      questions: [
        {
          key: '红色的落地方式选哪种?',
          reason: '需求存在需要确认的决策点',
          best_guess: '',
          ask: '红色的落地方式选哪种?',
          header: '方案',
          options: [
            { label: '新增主题变量', description: '改变量层' },
            { label: '复用现有变量', description: '最小改动' },
          ],
          multi_select: false,
        },
      ],
      cleared: [],
    })
    const done = snapshotFixture({ status: 'done', state: 'DONE' })
    useOptimizeStore.getState().applySnapshot(asked)

    const stream = gatedPhasedStream(
      [
        { type: 'thought', text: '正在根据你的答复重新研判…', phase: 'CONFIRMING' },
        {
          type: 'action',
          title: '重新研判',
          detail: '七项取证 + 已答 1 项',
          scope: 'PROBING',
          phase: 'CONFIRMING',
        },
      ],
      envelope(done),
    )
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string) =>
        String(input).includes('/followup/') ? stream.response : jsonResponse(envelope(null)),
      ),
    )

    renderPage()
    await user.click(screen.getByRole('button', { name: /新增主题变量/ }))
    await user.click(screen.getByRole('button', { name: '提交' }))

    // 过程帧到达：文字块可见，阶段高亮由 ASKING 推进到 CONFIRMING（整理答复）
    expect(await screen.findByText('正在根据你的答复重新研判…')).toBeTruthy()
    expect(document.querySelector('[class*="chat-reply__phase--current"]')?.textContent).toContain(
      '整理答复',
    )

    stream.release()

    await waitFor(() => expect(useOptimizeStore.getState().status).toBe('done'))
    expect(document.querySelector('[class*="ask-panel"]')).toBeNull()
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

  it('挂载时经 GET /result/{flow_id} 做服务端权威恢复', async () => {
    useOptimizeStore.getState().applySnapshot(snapshotFixture())
    const mock = stubApi([
      {
        match: '/result/sess-1',
        // CONFIRMING = 刚提交过答复，故带 cleared（2026-11-04 阶段按路径渲染，没答过不出现这一步）
        payload: envelope(
          snapshotFixture({ state: 'CONFIRMING', status: 'ask', cleared: ['scope'] }),
        ),
      },
    ])

    renderPage()

    await waitFor(() => {
      const call = mock.mock.calls.find(([input]) => input.includes('/api/v1/result/sess-1'))
      expect(call?.[1]?.method).toBe('GET')
    })
    await waitFor(() => {
      const labels = Array.from(
        document.querySelectorAll('[class*="chat-reply__phase-label"]'),
      ).map((el) => el.textContent)
      expect(labels).toContain('整理答复')
    })
  })

  it('优化页不再内嵌会话侧栏（已迁至 AppShell）', async () => {
    stubApi([])

    renderPage()

    expect(screen.queryByRole('complementary', { name: '会话侧栏' })).toBeNull()
    expect(await screen.findByRole('textbox', { name: '优化原句' })).toBeTruthy()
  })
})

describe('多轮归属（2026-11-04）', () => {
  const firstTurn = {
    turn_id: 't1',
    turn_index: 0,
    state: 'DONE',
    target: 'Button',
    conclusion: '第一轮结论：复用令牌',
    open_items: [],
    created_at: '',
  }
  const firstDetail = {
    ...firstTurn,
    input: '把提交按钮改成 primary-500',
    variants: [{ title: '保守版', body: '第一轮方案正文', level: 'A', changes: [] }],
  }

  function stubTwoTurns(secondSnapshot: unknown) {
    const gate = gatedStream(['正在检索相关代码'], [], secondSnapshot)
    const mock = vi.fn(async (input: string) => {
      const url = String(input)
      if (url.includes('/optimize/stream')) return gate.response
      if (url.includes('/history/sess-1/turns')) return jsonResponse(envelope([firstTurn]))
      if (url.includes('/turns/t1')) return jsonResponse(envelope(firstDetail))
      if (url.includes('/result/sess-1')) {
        return jsonResponse(
          envelope(snapshotFixture({ status: 'done', state: 'DONE', current_turn_id: 't1' })),
        )
      }
      if (url.includes('/history')) return jsonResponse(envelope([]))
      return jsonResponse(envelope(null))
    })
    vi.stubGlobal('fetch', mock)
    return { gate, mock }
  }

  it('第二轮生成期间第一轮结论仍在，终态后两轮各只渲染一次', async () => {
    const user = userEvent.setup()
    // 种入「第一轮已完成」的状态（含归属）
    useOptimizeStore
      .getState()
      .applySnapshot(snapshotFixture({ status: 'done', state: 'DONE', current_turn_id: 't1' }))
    useOptimizeStore.getState().setTurns([firstTurn])
    useOptimizeStore.getState().setCurrentTurnId('t1')

    const { gate } = stubTwoTurns(
      envelope(
        snapshotFixture({
          status: 'done',
          state: 'DONE',
          current_turn_id: 't2',
          variants: [{ title: '第二轮方案', body: '第二轮方案正文', level: 'B', changes: [] }],
        }),
      ),
    )

    renderPage()
    const input = await screen.findByRole('textbox', { name: '优化原句' })
    await user.type(input, '再加一个禁用态')
    await user.click(screen.getByRole('button', { name: '发送' }))

    // 生成窗口内：第一轮必须仍是历史轮（此前会被当作「当前轮」过滤掉 → 正文消失）
    expect(await screen.findByText('第一轮结论：复用令牌')).toBeTruthy()
    expect(document.querySelectorAll('[class*="thread__turn"]')).toHaveLength(1)

    gate.release()

    await waitFor(() => expect(screen.getByText('第二轮方案正文')).toBeTruthy())
    // 终态：第一轮留在历史，第二轮只由 ChatStream 渲染，两轮都不重复
    expect(screen.getByText('第一轮结论：复用令牌')).toBeTruthy()
    expect(document.querySelectorAll('[class*="thread__turn"]')).toHaveLength(1)
    expect(useOptimizeStore.getState().currentTurnId).toBe('t2')
  })
})
