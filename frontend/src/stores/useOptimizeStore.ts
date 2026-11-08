import { create } from 'zustand'
import type {
  DeliveryGatePayload,
  FlowSnapshotResponse,
  RankingViewPayload,
  TurnDetailPayload,
  TurnSummaryPayload,
  UnknownItemPayload,
  VariantPayload,
} from '../api/types'
import { FlowSnapshotSchema } from '../schemas/optimize'
import type { ActionPayload, ThinkingItem } from '../schemas/stream'
import type { SseStatus } from '../types'
import type { RunEvent } from '../api/protocol'
import {
  CheckpointPayloadSchema,
  CompactedPayloadSchema,
  DelegationRejectedPayloadSchema,
  DelegationWavePayloadSchema,
  parseEventPayload,
} from '../api/protocol'

/** 契约载荷按生成类型派生（F-705：勿在 api/types.ts 之外手写结构）。 */
type SymbolPayload = NonNullable<FlowSnapshotResponse['target']>
type FactPayload = NonNullable<FlowSnapshotResponse['facts']>[number]

/**
 * 单次优化流程状态（F-706）：SSE 消息统一在此处理，页面只消费状态（MUST-16）。
 * state/status 只镜像后端字符串，转移逻辑唯一在后端 state.py（MUST-07）。
 */
interface OptimizeState {
  /** 流程标识：契约 session_id，同时是 /progress、/followup、/result 的 flow_id 路径参数。 */
  sessionId: string | null
  /** 当前态镜像（后端 9 态字符串）。 */
  state: string
  /** 快照状态镜像（ask / done / guardrail / aborted）。 */
  status: string | null
  message: string
  questions: readonly UnknownItemPayload[]
  cleared: readonly string[]
  /** 三套方案（契约 variants 列表）。 */
  variants: readonly VariantPayload[]
  /** 推荐视图（契约 ranking；null 表示后端未产生推荐）。 */
  ranking: RankingViewPayload | null
  /** 未产生推荐的原因（2026-11-06）：single-variant / score-failed；null 表示有推荐。 */
  rankingSkipReason: string | null
  /** 目标定位镜像（契约 target；null 表示未定位，MUST-07 只镜像不判定）。 */
  target: SymbolPayload | null
  /** 取证事实镜像（契约 facts，F-104 判定结果只读透出）。 */
  facts: readonly FactPayload[]
  sseStatus: SseStatus
  isSubmitting: boolean
  /** 当前会话的轮次摘要（升序）；多轮历史渲染用，正文按需懒加载。 */
  turns: readonly TurnSummaryPayload[]
  /** 是否还有更早的轮次（分页：服务端按 has_more 告知，前端不猜）。 */
  hasMoreTurns: boolean
  setTurns: (turns: readonly TurnSummaryPayload[], hasMore?: boolean) => void
  /** 追加更早的一页（分页增量合并）；重复项按 turn_id 去重后仍按 turn_index 升序。 */
  appendTurns: (items: readonly TurnSummaryPayload[], hasMore: boolean) => void
  /** 历史轮正文常驻（2026-11-05 形态层）：切页面/折叠都不再丢，展开零请求。 */
  turnBodies: Readonly<Record<string, TurnDetailPayload>>
  setTurnBody: (turnId: string, detail: TurnDetailPayload) => void
  /** 当前展示轮次（最新一轮在 ChatStream 里渲染，历史列表据此排除它）。 */
  currentTurnId: string | null
  setCurrentTurnId: (turnId: string | null) => void
  /** agentic 进度镜像（2026-11-04）：仅 status === 'running' 时非空。 */
  agentStep: number | null
  agentAction: string | null
  agentElapsedMs: number | null
  /** 交付时证据已过期（2026-11-05）：期间代码被改，方案基于旧证据。 */
  evidenceStale: boolean
  /** 纯回答轮正文（2026-11-05）：本轮只回答、不产出方案。 */
  replyText: string
  /** 交付证据门（当前轮，2026-11-05 形态层）：null 表示未过门（进行中 / 反问中）。 */
  deliveryGate: DeliveryGatePayload | null
  /** 思考过程时间线（文字段与动作卡片按到达顺序排列）。 */
  thinking: readonly ThinkingItem[]
  /** 思考流进行中（传输层状态，不是 FlowState，MUST-07 不新增状态机态）。 */
  isThinking: boolean
  beginThinking: () => void
  /** 答复后重新研判（2026-11-03）：只清过程、开闸，不动 sessionId 与当前阶段（后端会推 phase）。 */
  beginReprobe: () => void
  /** 用后端帧里的 phase 同步当前阶段（回答后 CONFIRMING→GENERATING→RANKING 的推进来源）。 */
  notePhase: (phase: string) => void
  appendThought: (text: string, phase?: string) => void
  appendAction: (action: ActionPayload, phase?: string) => void
  endThinking: () => void
  /** 应用流程快照（POST /optimize、GET /result、SSE 推送共用同一入口）。 */
  applySnapshot: (snapshot: FlowSnapshotResponse) => void
  /** 处理 SSE 原始消息：畸形即丢弃（契约破坏不重试，MUST-15），合法才更新状态。 */
  applySseMessage: (raw: string) => void
  /** 应用运行时事件（多端协议入口）：按 type 分发到既有动作，状态机仍在后端。 */
  applyRunEvent: (event: RunEvent) => void
  setSseStatus: (sseStatus: SseStatus) => void
  setSubmitting: (isSubmitting: boolean) => void
  reset: () => void
}

const initialState: Pick<
  OptimizeState,
  | 'sessionId'
  | 'state'
  | 'status'
  | 'message'
  | 'questions'
  | 'cleared'
  | 'variants'
  | 'ranking'
  | 'rankingSkipReason'
  | 'target'
  | 'facts'
  | 'sseStatus'
  | 'isSubmitting'
  | 'turns'
  | 'hasMoreTurns'
  | 'turnBodies'
  | 'currentTurnId'
  | 'agentStep'
  | 'agentAction'
  | 'agentElapsedMs'
  | 'evidenceStale'
  | 'replyText'
  | 'deliveryGate'
  | 'thinking'
  | 'isThinking'
> = {
  sessionId: null,
  state: 'INIT',
  status: null,
  message: '',
  questions: [],
  cleared: [],
  variants: [],
  ranking: null,
  rankingSkipReason: null,
  target: null,
  facts: [],
  sseStatus: 'idle',
  isSubmitting: false,
  turns: [],
  hasMoreTurns: false,
  turnBodies: {},
  currentTurnId: null,
  agentStep: null,
  agentAction: null,
  agentElapsedMs: null,
  evidenceStale: false,
  replyText: '',
  deliveryGate: null,
  thinking: [],
  isThinking: false,
}

/** 时间线条目 id：只用于 React key，不入契约。 */
let thinkingSeq = 0
function nextThinkingId(): string {
  thinkingSeq += 1
  return `think-${thinkingSeq}`
}

export const useOptimizeStore = create<OptimizeState>()((set, get) => ({
  ...initialState,
  // 新一轮提交：清掉上一轮快照与 sessionId——否则旧会话的 SSE 仍在心跳，
  // 会把上一轮快照推回来并提前结束思考。
  setTurns: (turns, hasMore = false) => set({ turns, hasMoreTurns: hasMore }),
  appendTurns: (items, hasMore) =>
    set((state) => {
      const seen = new Set(state.turns.map((turn) => turn.turn_id))
      const merged = [...state.turns, ...items.filter((turn) => !seen.has(turn.turn_id))]
      merged.sort((a, b) => a.turn_index - b.turn_index)
      return { turns: merged, hasMoreTurns: hasMore }
    }),
  setCurrentTurnId: (turnId) => set({ currentTurnId: turnId }),
  // 历史轮正文常驻：写入即缓存，重复展开零请求（正文不再随组件卸载丢失）
  setTurnBody: (turnId, detail) =>
    set((state) => ({ turnBodies: { ...state.turnBodies, [turnId]: detail } })),
  // 多轮：新一轮不清容器（session 与历史轮次保留），只重置本轮快照与思考区
  // 提交新一轮（2026-11-04）：清空本轮快照的同时**释放「当前轮」指向**（置 null）。
  // 若保留上一轮 id，TurnList 会把它当作「当前轮」过滤掉，而 ChatStream 的方案已被清空，
  // 于是上一轮正文在生成窗口内消失（用户报障：第二轮开始后第一轮结果直接不见）。
  // 置 null 后历史轮全部留在 TurnList，等终态快照的 current_turn_id 再推进。
  beginThinking: () =>
    set((state) => ({
      ...initialState,
      sessionId: state.sessionId,
      turns: state.turns,
      hasMoreTurns: state.hasMoreTurns,
      currentTurnId: null,
      isThinking: true,
    })),
  // 答复后的过程流：保留 sessionId / 当前阶段 / 已答清单，只把过程区清空并开闸。
  // 不能用 beginThinking——它会展开 initialState，把 state 打回 INIT、questions 清空，
  // 于是阶段高亮错位、反问卡消失（2026-11-03 实测）。
  beginReprobe: () => set({ thinking: [], isThinking: true, sseStatus: 'open' }),
  notePhase: (phase) =>
    set((state) => (phase === '' || phase === state.state ? state : { state: phase })),
  appendThought: (text, phase = '') =>
    set((state) => {
      if (!state.isThinking) return { thinking: state.thinking }
      const last = state.thinking.at(-1)
      // 同一阶段的文字段合并，避免碎片化；跨阶段另起一段
      if (last?.kind === 'text' && last.phase === phase) {
        return {
          thinking: [...state.thinking.slice(0, -1), { ...last, text: last.text + text }],
        }
      }
      return {
        thinking: [...state.thinking, { id: nextThinkingId(), kind: 'text', text, phase }],
      }
    }),
  appendAction: (action, phase = '') =>
    set((state) => {
      if (!state.isThinking) return { thinking: state.thinking }
      // 契约是 snake_case（duration_ms），视图模型是 camelCase（durationMs）：
      // 在这里一次性转换，组件不再关心契约命名（MUST-16：store 只存结果）。
      const { duration_ms: durationMs, ...rest } = action
      return {
        thinking: [
          ...state.thinking,
          {
            id: nextThinkingId(),
            kind: 'action',
            ...rest,
            durationMs: durationMs ?? undefined,
            phase,
          },
        ],
      }
    }),
  endThinking: () => set({ isThinking: false }),
  applySnapshot: (snapshot) =>
    set((state) => ({
      sessionId: snapshot.session_id,
      state: snapshot.state,
      status: snapshot.status,
      message: snapshot.message,
      questions: snapshot.questions ?? [],
      cleared: snapshot.cleared ?? [],
      variants: snapshot.variants ?? [],
      ranking: snapshot.ranking ?? null,
      rankingSkipReason: snapshot.ranking_skip_reason ?? null,
      target: snapshot.target ?? null,
      facts: snapshot.facts ?? [],
      // 归属以服务端为准（2026-11-04）；老后端/测试夹具无该字段时保留现值，不误清
      currentTurnId: snapshot.current_turn_id ?? state.currentTurnId,
      // agentic 进度（2026-11-04）：仅 running 快照带值；其余状态清零避免时间线残留
      agentStep: snapshot.status === 'running' ? (snapshot.agent_step ?? null) : null,
      agentAction: snapshot.status === 'running' ? (snapshot.agent_action ?? null) : null,
      agentElapsedMs: snapshot.status === 'running' ? (snapshot.agent_elapsed_ms ?? null) : null,
      // 证据过期标记与 status 无关：终态也要保留，否则交付后就看不到了
      evidenceStale: snapshot.evidence_stale ?? false,
      // 纯回答轮正文：仅在快照带值时有内容，其余轮为空串（避免上一轮回答串到这一轮）
      replyText: snapshot.reply_text ?? '',
      // 交付证据门：null = 本轮未过门（进行中 / 反问中）
      deliveryGate: snapshot.delivery_gate ?? null,
      // 终态快照即思考结束：无论流何时关闭，都不留「思考中」
      isThinking: false,
    })),
  applySseMessage: (raw) => {
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch {
      return
    }
    const result = FlowSnapshotSchema.safeParse(parsed)
    if (!result.success) {
      return
    }
    get().applySnapshot(result.data)
  },
  applyRunEvent: (event) => {
    const store = get()
    switch (event.type) {
      case 'run.started':
        set({ isThinking: true, sseStatus: 'open' })
        return
      case 'thought': {
        const text = typeof event.data.text === 'string' ? event.data.text : ''
        const phase = typeof event.data.phase === 'string' ? event.data.phase : ''
        if (text !== '') store.appendThought(text, phase)
        return
      }
      case 'action': {
        const title = typeof event.data.title === 'string' ? event.data.title : ''
        if (title === '') return
        store.appendAction(
          {
            title,
            detail: typeof event.data.detail === 'string' ? event.data.detail : '',
            scope: typeof event.data.scope === 'string' ? event.data.scope : '',
            output: typeof event.data.output === 'string' ? event.data.output : '',
            status: event.data.status === 'failed' ? 'failed' : 'ok',
          },
          typeof event.data.phase === 'string' ? event.data.phase : '',
        )
        return
      }
      case 'snapshot': {
        const parsed = FlowSnapshotSchema.safeParse(event.data)
        if (parsed.success) store.applySnapshot(parsed.data)
        return
      }
      case 'error': {
        set({
          message: typeof event.data.message === 'string' ? event.data.message : '运行失败',
          status: 'aborted',
          isThinking: false,
          sseStatus: 'idle',
        })
        return
      }
      case 'stop':
        set({ isThinking: false, sseStatus: 'idle' })
        return
      case 'agent.checkpoint': {
        // 每 5 步的执行进度：直写步骤镜像（snapshot 帧之外的增量进度源）
        const payload = parseEventPayload(CheckpointPayloadSchema, event.data)
        if (!payload) return
        set({ agentStep: payload.step, agentAction: payload.action })
        return
      }
      case 'delegation.rejected': {
        const payload = parseEventPayload(DelegationRejectedPayloadSchema, event.data)
        if (!payload) return
        store.appendAction(
          { title: '委派被拒', detail: payload.reason, scope: '', output: '', status: 'failed' },
          '',
        )
        return
      }
      case 'delegation.wave': {
        const payload = parseEventPayload(DelegationWavePayloadSchema, event.data)
        if (!payload) return
        store.appendAction(
          {
            title: `委派波次 ${payload.wave + 1}/${payload.total}`,
            detail: payload.orders.join('、'),
            scope: '',
            output: '',
            status: 'ok',
          },
          '',
        )
        return
      }
      case 'context.compacted': {
        const payload = parseEventPayload(CompactedPayloadSchema, event.data)
        if (!payload) return
        store.appendThought('上下文已压缩：窗口外的旧轮折叠为摘要', 'compaction')
        return
      }
      default:
        return
    }
  },
  setSseStatus: (sseStatus) => set({ sseStatus }),
  setSubmitting: (isSubmitting) => set({ isSubmitting }),
  reset: () => set({ ...initialState }),
}))
