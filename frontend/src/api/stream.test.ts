import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamOptimize } from './endpoints'
import { ApiError } from './errors'

const snapshot = {
  session_id: 'sess-stream',
  state: 'DONE',
  status: 'done',
  message: '',
  questions: [],
  cleared: [],
  variant: { title: '标准方案', body: 'b', changes: [], claims: [], fallback: false },
}

/** 手写 reader：不依赖 jsdom 是否实现 ReadableStream。 */
function streamResponse(chunks: string[]) {
  let index = 0
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => {
          if (index >= chunks.length) return { done: true, value: undefined }
          const value = new TextEncoder().encode(chunks[index])
          index += 1
          return { done: false, value }
        },
        releaseLock: () => undefined,
      }),
    },
  }
}

function stubFetch(chunks: string[]) {
  const mock = vi.fn(async (_input: string, _init: RequestInit) => streamResponse(chunks))
  vi.stubGlobal('fetch', mock)
  return mock
}

function handlers() {
  return {
    onThought: vi.fn<(text: string) => void>(),
    onAction: vi.fn<(action: unknown) => void>(),
    onSnapshot: vi.fn<(value: unknown) => void>(),
    onError: vi.fn<(error: ApiError) => void>(),
    onOpen: vi.fn<() => void>(),
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('streamOptimize', () => {
  it('按帧解析 thought 与终态 snapshot', async () => {
    stubFetch([
      `data: {"type":"thought","text":"先检索代码"}\n\n`,
      `data: {"type":"thought","text":"已选中目标"}\n\n`,
      `data: ${JSON.stringify({ type: 'snapshot', data: snapshot })}\n\n`,
    ])
    const spy = handlers()

    await streamOptimize({ sentence: '改按钮', project: '.', base_turn_id: '' }, spy)

    expect(spy.onThought.mock.calls).toEqual([
      ['先检索代码', ''],
      ['已选中目标', ''],
    ])
    expect(spy.onSnapshot).toHaveBeenCalledTimes(1)
    expect(spy.onSnapshot.mock.calls[0]?.[0]).toMatchObject({ session_id: 'sess-stream' })
    expect(spy.onError).not.toHaveBeenCalled()
  })

  it('跨 TCP 分片的半帧也能拼回来', async () => {
    const frame = `data: {"type":"thought","text":"检索到 25 条候选"}\n\n`
    stubFetch([frame.slice(0, 12), frame.slice(12)])

    const spy = handlers()
    await streamOptimize({ sentence: '改按钮', project: '.', base_turn_id: '' }, spy)

    expect(spy.onThought).toHaveBeenCalledWith('检索到 25 条候选', '')
  })

  it('action 帧映射成卡片载荷', async () => {
    stubFetch([
      `data: ${JSON.stringify({
        type: 'action',
        title: '检索符号',
        detail: 'rg -n Foo --glob src/a.ts',
        scope: '命中 2 行',
      })}\n\n`,
    ])
    const spy = handlers()

    await streamOptimize({ sentence: '改按钮', project: '.', base_turn_id: '' }, spy)

    expect(spy.onAction).toHaveBeenCalledWith(
      {
        title: '检索符号',
        detail: 'rg -n Foo --glob src/a.ts',
        scope: '命中 2 行',
        output: '',
        // 2026-11-04 起 action 帧带 status，旧帧缺省按 ok（见 schemas/stream.ts）
        status: 'ok',
      },
      '',
    )
  })

  it('缺字段的 action 帧被丢弃（契约破坏不重试）', async () => {
    stubFetch([`data: ${JSON.stringify({ type: 'action', title: '检索' })}\n\n`])
    const spy = handlers()

    await streamOptimize({ sentence: '改按钮', project: '.', base_turn_id: '' }, spy)

    expect(spy.onAction).not.toHaveBeenCalled()
    expect(spy.onError).not.toHaveBeenCalled()
  })

  it('忽略保活注释帧与畸形帧', async () => {
    stubFetch([
      ': ping\n\n',
      'data: 不是JSON\n\n',
      `data: ${JSON.stringify({ type: 'thought', text: '继续' })}\n\n`,
    ])

    const spy = handlers()
    await streamOptimize({ sentence: '改按钮', project: '.', base_turn_id: '' }, spy)

    expect(spy.onThought.mock.calls).toEqual([['继续', '']])
    expect(spy.onError).not.toHaveBeenCalled()
  })

  it('error 帧转成 ApiError 并保留业务码', async () => {
    stubFetch([
      `data: {"type":"error","code":4001,"message":"生成阶段失败","request_id":"rid-1"}\n\n`,
    ])

    const spy = handlers()
    await streamOptimize({ sentence: '改按钮', project: '.', base_turn_id: '' }, spy)

    const error = spy.onError.mock.calls[0]?.[0]
    expect(error).toBeInstanceOf(ApiError)
    expect(error?.code).toBe(4001)
    expect(error?.message).toBe('生成阶段失败')
    expect(spy.onSnapshot).not.toHaveBeenCalled()
  })

  it('原句走请求体、URL 不含原句（MUST-19）', async () => {
    const mock = stubFetch([])
    const sentence = '把提交按钮改成 primary-500'

    await streamOptimize({ sentence, project: 'D:/repo', base_turn_id: '' }, handlers())

    const call = mock.mock.calls[0]
    if (call === undefined) throw new Error('fetch 未被调用')
    const [url, init] = call
    expect(url).not.toContain(sentence)
    expect(String(init.body)).toContain(sentence)
    expect((init.headers as Record<string, string>).accept).toBe('text/event-stream')
  })
})
