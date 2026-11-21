import { beforeEach, describe, expect, it } from 'vitest'
import type { FlowSnapshotResponse } from '../api/types'
import { useOptimizeStore } from './useOptimizeStore'

const variant = {
  title: '标准方案',
  body: 'b2',
  changes: ['x'],
  claims: [],
  fallback: false,
}

function snapshotOf(overrides?: Partial<FlowSnapshotResponse>): FlowSnapshotResponse {
  return {
    session_id: 'sess-1',
    state: 'DONE',
    status: 'done',
    message: 'ok',
    evidence_stale: false,
    reply_text: '',
    questions: [
      {
        key: 'target',
        reason: '缺失',
        best_guess: 'Foo',
        ask: '改哪里？',
        header: '',
        options: [],
        multi_select: false,
      },
    ],
    cleared: ['scope'],
    variant,
    target: { name: 'build', path: 'src/app.py', line: 12 },
    facts: [{ key: 'fact_a', passed: true, evidence: '定位到 build' }],
    ...overrides,
  }
}

beforeEach(() => {
  useOptimizeStore.getState().reset()
})

describe('useOptimizeStore 快照镜像', () => {
  it('applySnapshot 更新当前态与单套方案', () => {
    useOptimizeStore.getState().applySnapshot(snapshotOf())

    const state = useOptimizeStore.getState()
    expect(state.sessionId).toBe('sess-1')
    expect(state.state).toBe('DONE')
    expect(state.status).toBe('done')
    expect(state.variant).toMatchObject({ title: '标准方案', body: 'b2', fallback: false })
    expect(state.questions).toHaveLength(1)
    expect(state.cleared).toEqual(['scope'])
    expect(state.target).toMatchObject({ name: 'build', path: 'src/app.py', line: 12 })
    expect(state.facts).toEqual([{ key: 'fact_a', passed: true, evidence: '定位到 build' }])
  })

  it('applySnapshot 可选字段缺省时回退空集合与 null', () => {
    useOptimizeStore.getState().applySnapshot(
      snapshotOf({
        questions: undefined,
        cleared: undefined,
        variant: undefined,
        target: undefined,
        facts: undefined,
      }),
    )

    const state = useOptimizeStore.getState()
    expect(state.questions).toEqual([])
    expect(state.cleared).toEqual([])
    expect(state.variant).toBeNull()
    expect(state.target).toBeNull()
    expect(state.facts).toEqual([])
  })

  it('applySseMessage 合法消息更新状态（SSE 消息在 store 内处理）', () => {
    useOptimizeStore.getState().applySseMessage(JSON.stringify(snapshotOf()))

    expect(useOptimizeStore.getState().state).toBe('DONE')
    expect(useOptimizeStore.getState().variant).toMatchObject({ title: '标准方案' })
  })

  it('applySseMessage 非法 JSON 直接丢弃，状态不变', () => {
    useOptimizeStore.getState().applySseMessage('not-json')

    expect(useOptimizeStore.getState().state).toBe('INIT')
  })

  it('applySseMessage 契约不符（缺 session_id）丢弃，状态不变', () => {
    useOptimizeStore.getState().applySseMessage(JSON.stringify({ state: 'DONE', status: 'done' }))

    expect(useOptimizeStore.getState().state).toBe('INIT')
  })

  it('beginThinking 保留会话容器（多轮），只重置本轮快照', () => {
    const store = useOptimizeStore.getState()
    store.applySnapshot(snapshotOf())
    store.setTurns([
      {
        turn_id: 't1',
        turn_index: 0,
        state: 'DONE',
        target: 'Button',
        conclusion: '复用令牌',
        open_items: [],
        created_at: '',
      },
    ])
    store.setCurrentTurnId('t1')

    useOptimizeStore.getState().beginThinking()

    const next = useOptimizeStore.getState()
    expect(next.sessionId).toBe('sess-1') // 容器不丢，下一轮复用
    expect(next.turns).toHaveLength(1)
    // 归属释放（2026-11-04）：新轮开始时上一轮不再是「当前轮」，否则会被 TurnList 过滤掉
    expect(next.currentTurnId).toBeNull()
    expect(next.isThinking).toBe(true)
    expect(next.variant).toBeNull() // 本轮快照被清
    expect(next.status).toBeNull()
  })

  it('applySnapshot 采用服务端 current_turn_id（归属不再靠列表末位推断）', () => {
    useOptimizeStore.getState().setCurrentTurnId('old')

    useOptimizeStore.getState().applySnapshot(snapshotOf({ current_turn_id: 't2' }))

    expect(useOptimizeStore.getState().currentTurnId).toBe('t2')
  })

  it('applySnapshot 缺 current_turn_id 时保留现值（兼容老后端与测试夹具）', () => {
    useOptimizeStore.getState().setCurrentTurnId('keep')

    useOptimizeStore.getState().applySnapshot(snapshotOf())

    expect(useOptimizeStore.getState().currentTurnId).toBe('keep')
  })

  it('reset 清空流程状态回初始值', () => {
    useOptimizeStore.getState().applySnapshot(snapshotOf())
    useOptimizeStore.getState().setSubmitting(true)

    useOptimizeStore.getState().reset()

    const state = useOptimizeStore.getState()
    expect(state.sessionId).toBeNull()
    expect(state.state).toBe('INIT')
    expect(state.isSubmitting).toBe(false)
  })
})

describe('useOptimizeStore 运行时事件守卫', () => {
  it('agent.checkpoint 帧直写执行进度镜像', () => {
    useOptimizeStore.getState().applyRunEvent({
      seq: 1,
      type: 'agent.checkpoint',
      run_id: 'r1',
      data: { step: 5, action: 'retrieve', facts_passed: 3, request_id: 'x' },
      ts: '',
    })
    const state = useOptimizeStore.getState()
    expect(state.agentStep).toBe(5)
    expect(state.agentAction).toBe('retrieve')
  })

  it('delegation.wave / rejected / context.compacted 帧进思考时间线', () => {
    const store = useOptimizeStore.getState()
    store.setSubmitting(true)
    useOptimizeStore.setState({ isThinking: true })
    useOptimizeStore.getState().applyRunEvent({
      seq: 2,
      type: 'delegation.wave',
      run_id: 'r1',
      data: { wave: 0, total: 2, orders: ['delegate-x-0'] },
      ts: '',
    })
    useOptimizeStore.getState().applyRunEvent({
      seq: 3,
      type: 'delegation.rejected',
      run_id: 'r1',
      data: { reason: '占位冲突' },
      ts: '',
    })
    useOptimizeStore.getState().applyRunEvent({
      seq: 4,
      type: 'context.compacted',
      run_id: 'r1',
      data: { layers: ['compacted:micro'] },
      ts: '',
    })
    const thinking = useOptimizeStore.getState().thinking
    expect(thinking.some((item) => item.kind === 'action' && item.title === '委派波次 1/2')).toBe(
      true,
    )
    expect(thinking.some((item) => item.kind === 'action' && item.status === 'failed')).toBe(true)
    expect(
      thinking.some((item) => item.kind === 'text' && item.text.includes('上下文已压缩')),
    ).toBe(true)
  })

  it('重连快照的 pending 恢复审批条，空 pending 清掉旧条', () => {
    useOptimizeStore.getState().applyRunEvent({
      seq: 0,
      type: 'snapshot',
      run_id: '',
      data: {
        session_id: 's1',
        pending: [
          {
            request_id: 'req-1',
            kind: 'approval',
            payload: { tool: 'fetch_page' },
          },
        ],
        last_seq: 9,
      },
      ts: '',
    })
    expect(useOptimizeStore.getState().pendingApproval).toEqual({
      requestId: 'req-1',
      tool: 'fetch_page',
    })

    useOptimizeStore.getState().applyRunEvent({
      seq: 0,
      type: 'snapshot',
      run_id: '',
      data: { session_id: 's1', pending: [], last_seq: 9 },
      ts: '',
    })
    expect(useOptimizeStore.getState().pendingApproval).toBeNull()
  })

  it('畸形载荷安全丢弃不崩', () => {
    expect(() =>
      useOptimizeStore.getState().applyRunEvent({
        seq: 5,
        type: 'agent.checkpoint',
        run_id: 'r1',
        data: { step: 'oops' },
        ts: '',
      }),
    ).not.toThrow()
    expect(useOptimizeStore.getState().agentStep).not.toBe('oops')
  })
})

describe('useOptimizeStore 流式动作归并（2026-11-15）', () => {
  it('同一 callId 的增量帧追加到同一张卡，完成帧替换输出并补齐范围与耗时', () => {
    const store = useOptimizeStore.getState()
    store.beginThinking()

    store.appendAction(
      {
        title: '检索符号',
        detail: 'rg -n Foo',
        scope: '',
        output: '',
        status: 'ok',
        id: 'c1',
        delta: 'hit-1\n',
      },
      'RETRIEVING',
    )
    store.appendAction(
      {
        title: '检索符号',
        detail: 'rg -n Foo',
        scope: '',
        output: '',
        status: 'ok',
        id: 'c1',
        delta: 'hit-2\n',
      },
      'RETRIEVING',
    )

    let items = useOptimizeStore.getState().thinking
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ kind: 'action', output: 'hit-1\nhit-2\n' })

    store.appendAction(
      {
        title: '检索符号',
        detail: 'rg -n Foo',
        scope: '命中 2 行',
        output: 'hit-1\nhit-2\n',
        status: 'ok',
        id: 'c1',
        delta: '',
        duration_ms: 42,
      },
      'RETRIEVING',
    )

    items = useOptimizeStore.getState().thinking
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({
      output: 'hit-1\nhit-2\n',
      scope: '命中 2 行',
      durationMs: 42,
    })
  })

  it('无 callId 的旧帧各自新建卡片（向后兼容）', () => {
    const store = useOptimizeStore.getState()
    store.beginThinking()

    store.appendAction(
      { title: 'A', detail: '', scope: '', output: 'x', status: 'ok', id: '', delta: '' },
      'RETRIEVING',
    )
    store.appendAction(
      { title: 'B', detail: '', scope: '', output: 'y', status: 'ok', id: '', delta: '' },
      'RETRIEVING',
    )

    expect(useOptimizeStore.getState().thinking).toHaveLength(2)
  })
})
