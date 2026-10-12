import { create } from 'zustand'
import type { FlowState, SnapshotStatus, SseStatus } from '../types'

/** 单次优化流程状态（F-706）：SSE 消息统一在此处理，页面只消费状态（MUST-16）。 */
interface OptimizeState {
  flowId: string | null
  state: FlowState
  status: SnapshotStatus | null
  sseStatus: SseStatus
  isSubmitting: boolean
  setFlow: (flowId: string, state: FlowState) => void
  patchState: (state: FlowState) => void
  setStatus: (status: SnapshotStatus) => void
  setSseStatus: (sseStatus: SseStatus) => void
  setSubmitting: (isSubmitting: boolean) => void
  reset: () => void
}

const initialState: Pick<
  OptimizeState,
  'flowId' | 'state' | 'status' | 'sseStatus' | 'isSubmitting'
> = {
  flowId: null,
  state: 'INIT',
  status: null,
  sseStatus: 'idle',
  isSubmitting: false,
}

export const useOptimizeStore = create<OptimizeState>()((set) => ({
  ...initialState,
  setFlow: (flowId, state) => set({ flowId, state }),
  patchState: (state) => set({ state }),
  setStatus: (status) => set({ status }),
  setSseStatus: (sseStatus) => set({ sseStatus }),
  setSubmitting: (isSubmitting) => set({ isSubmitting }),
  reset: () => set({ ...initialState }),
}))
