import { create } from 'zustand'
import type { HistoryItemPayload, PreferenceVectorPayload } from '../api/types'

/** 偏好向量与采纳历史（F-706）：应用级跨页面共享；数据获取在 api/hooks，store 只存结果。 */
interface PreferenceState {
  vector: PreferenceVectorPayload | null
  history: readonly HistoryItemPayload[]
  setVector: (vector: PreferenceVectorPayload) => void
  setHistory: (history: readonly HistoryItemPayload[]) => void
}

export const usePreferenceStore = create<PreferenceState>()((set) => ({
  vector: null,
  history: [],
  setVector: (vector) => set({ vector }),
  setHistory: (history) => set({ history }),
}))
