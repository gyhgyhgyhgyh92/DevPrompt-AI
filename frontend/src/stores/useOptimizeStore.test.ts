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
