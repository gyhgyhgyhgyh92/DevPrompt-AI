import { create } from 'zustand'
import type {
  FlowSnapshotResponse,
  RankingViewPayload,
  UnknownItemPayload,
  VariantPayload,
} from '../api/types'
import { FlowSnapshotSchema } from '../schemas/optimize'
import type { SseStatus } from '../types'

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
  sseStatus: SseStatus
  isSubmitting: boolean
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
  | 'sseStatus'
  | 'isSubmitting'
> = {
  sessionId: null,
  state: 'INIT',
  status: null,
  message: '',
  questions: [],
  cleared: [],
  variants: [],
  ranking: null,
  sseStatus: 'idle',
  isSubmitting: false,
}

export const useOptimizeStore = create<OptimizeState>()((set, get) => ({
  ...initialState,
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
