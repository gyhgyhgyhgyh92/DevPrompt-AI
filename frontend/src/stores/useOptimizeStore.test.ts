import { beforeEach, describe, expect, it } from 'vitest'
import type { FlowSnapshotResponse } from '../api/types'
import { useOptimizeStore } from './useOptimizeStore'

const ranking = {
  variant: 'B',
  gap: 0.3,
  confidence: 0.9,
  marked: true,
  reason: '分差较大',
  fit: 0.8,
  total: 0.76,
}

function snapshotOf(overrides?: Partial<FlowSnapshotResponse>): FlowSnapshotResponse {
  return {
    session_id: 'sess-1',
    state: 'RANKING',
    status: 'done',
    message: 'ok',
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
    variants: [
      { title: '保守', body: 'b1', level: 'A', changes: [] },
      { title: '标准', body: 'b2', level: 'B', changes: ['x'] },
      { title: '激进', body: 'b3', level: 'C', changes: [] },
    ],
    ranking,
    target: { name: 'build', path: 'src/app.py', line: 12 },
    facts: [{ key: 'fact_a', passed: true, evidence: '定位到 build' }],
    ...overrides,
  }
}

beforeEach(() => {
  useOptimizeStore.getState().reset()
})

describe('useOptimizeStore 快照镜像', () => {
  it('applySnapshot 更新当前态、三套方案与 ranking 视图', () => {
    useOptimizeStore.getState().applySnapshot(snapshotOf())

    const state = useOptimizeStore.getState()
    expect(state.sessionId).toBe('sess-1')
    expect(state.state).toBe('RANKING')
    expect(state.status).toBe('done')
    expect(state.variants).toHaveLength(3)
    expect(state.ranking).toMatchObject({ variant: 'B', marked: true })
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
        variants: undefined,
        ranking: undefined,
        target: undefined,
        facts: undefined,
      }),
    )

    const state = useOptimizeStore.getState()
    expect(state.questions).toEqual([])
    expect(state.cleared).toEqual([])
    expect(state.variants).toEqual([])
    expect(state.ranking).toBeNull()
    expect(state.target).toBeNull()
    expect(state.facts).toEqual([])
  })

  it('applySseMessage 合法消息更新状态（SSE 消息在 store 内处理）', () => {
    useOptimizeStore.getState().applySseMessage(JSON.stringify(snapshotOf()))

    expect(useOptimizeStore.getState().state).toBe('RANKING')
    expect(useOptimizeStore.getState().variants).toHaveLength(3)
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
    expect(next.currentTurnId).toBe('t1')
    expect(next.isThinking).toBe(true)
    expect(next.variants).toEqual([]) // 本轮快照被清
    expect(next.status).toBeNull()
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
