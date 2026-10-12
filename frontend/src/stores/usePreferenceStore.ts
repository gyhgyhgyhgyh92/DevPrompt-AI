import { create } from 'zustand'
import type { HistoryItemPayload, PreferenceVectorPayload } from '../api/types'

/** 偏好向量与采纳历史（F-706）：应用级跨页面共享；数据获取在 api/hooks，store 只存结果。 */
interface PreferenceState {
  vector: PreferenceVectorPayload | null
  history: readonly HistoryItemPayload[]
  setVector: (vector: PreferenceVectorPayload) => void
  setHistory: (history: readonly HistoryItemPayload[]) => void
  reset: () => void
}

const initialState: Pick<PreferenceState, 'vector' | 'history'> = {
  vector: null,
  history: [],
}

export const usePreferenceStore = create<PreferenceState>()((set) => ({
  ...initialState,
  setVector: (vector) => set({ vector }),
  setHistory: (history) => set({ history }),
  reset: () => set({ ...initialState }),
}))
