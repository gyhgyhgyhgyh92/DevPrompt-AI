import { create } from 'zustand'
import type {
  FlowSnapshotResponse,
  RankingViewPayload,
  TurnSummaryPayload,
  UnknownItemPayload,
  VariantPayload,
} from '../api/types'
import { FlowSnapshotSchema } from '../schemas/optimize'
import type { ActionPayload, ThinkingItem } from '../schemas/stream'
import type { SseStatus } from '../types'

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
  /** 目标定位镜像（契约 target；null 表示未定位，MUST-07 只镜像不判定）。 */
  target: SymbolPayload | null
  /** 取证事实镜像（契约 facts，F-104 判定结果只读透出）。 */
  facts: readonly FactPayload[]
  sseStatus: SseStatus
  isSubmitting: boolean
  /** 当前会话的轮次摘要（升序）；多轮历史渲染用，正文按需懒加载。 */
  turns: readonly TurnSummaryPayload[]
  setTurns: (turns: readonly TurnSummaryPayload[]) => void
  /** 当前展示轮次（最新一轮在 ChatStream 里渲染，历史列表据此排除它）。 */
  currentTurnId: string | null
  setCurrentTurnId: (turnId: string | null) => void
  /** 思考过程时间线（文字段与动作卡片按到达顺序排列）。 */
  thinking: readonly ThinkingItem[]
  /** 思考流进行中（传输层状态，不是 FlowState，MUST-07 不新增状态机态）。 */
  isThinking: boolean
  beginThinking: () => void
  appendThought: (text: string, phase?: string) => void
  appendAction: (action: ActionPayload, phase?: string) => void
  endThinking: () => void
  /** 应用流程快照（POST /optimize、GET /result、SSE 推送共用同一入口）。 */
  applySnapshot: (snapshot: FlowSnapshotResponse) => void
  /** 处理 SSE 原始消息：畸形即丢弃（契约破坏不重试，MUST-15），合法才更新状态。 */
  applySseMessage: (raw: string) => void
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
  | 'target'
  | 'facts'
  | 'sseStatus'
  | 'isSubmitting'
  | 'turns'
  | 'currentTurnId'
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
  target: null,
  facts: [],
  sseStatus: 'idle',
  isSubmitting: false,
  turns: [],
  currentTurnId: null,
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
  setTurns: (turns) => set({ turns }),
  setCurrentTurnId: (turnId) => set({ currentTurnId: turnId }),
  // 多轮：新一轮不清容器（session 与历史轮次保留），只重置本轮快照与思考区
  beginThinking: () =>
    set((state) => ({
      ...initialState,
      sessionId: state.sessionId,
      turns: state.turns,
      currentTurnId: state.currentTurnId,
      isThinking: true,
    })),
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
    set((state) =>
      state.isThinking
        ? {
            thinking: [
              ...state.thinking,
              { id: nextThinkingId(), kind: 'action', ...action, phase },
            ],
          }
        : { thinking: state.thinking },
    ),
  endThinking: () => set({ isThinking: false }),
  applySnapshot: (snapshot) =>
    set({
      sessionId: snapshot.session_id,
      state: snapshot.state,
      status: snapshot.status,
      message: snapshot.message,
      questions: snapshot.questions ?? [],
      cleared: snapshot.cleared ?? [],
      variants: snapshot.variants ?? [],
      ranking: snapshot.ranking ?? null,
      target: snapshot.target ?? null,
      facts: snapshot.facts ?? [],
      // 终态快照即思考结束：无论流何时关闭，都不留「思考中」
      isThinking: false,
    }),
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
  setSseStatus: (sseStatus) => set({ sseStatus }),
  setSubmitting: (isSubmitting) => set({ isSubmitting }),
  reset: () => set({ ...initialState }),
}))
