import { create } from 'zustand'

import type { HistoryItemPayload } from '../api/types'

/** 会话历史（2026-10-21 三层记忆的第三层）：应用级跨页面共享，store 只存结果。 */
interface HistoryState {
  history: readonly HistoryItemPayload[]
  setHistory: (history: readonly HistoryItemPayload[]) => void
  reset: () => void
}

const initialState: Pick<HistoryState, 'history'> = { history: [] }

export const useHistoryStore = create<HistoryState>()((set) => ({
  ...initialState,
  setHistory: (history) => set({ history }),
  reset: () => set({ ...initialState }),
}))
