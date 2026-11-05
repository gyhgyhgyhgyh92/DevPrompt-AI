import { create } from 'zustand'

import type { HistoryItemPayload } from '../api/types'

/** 会话历史（2026-10-21 三层记忆的第三层）：应用级跨页面共享，store 只存结果。 */
interface HistoryState {
  history: readonly HistoryItemPayload[]
  /** 是否还有更早的会话（分页：服务端按 has_more 告知，前端不猜）。 */
  hasMore: boolean
  setHistory: (history: readonly HistoryItemPayload[], hasMore?: boolean) => void
  /** 追加一页（分页增量合并）；重复项按 session_id 去重。 */
  appendHistory: (items: readonly HistoryItemPayload[], hasMore: boolean) => void
  reset: () => void
}

const initialState: Pick<HistoryState, 'history' | 'hasMore'> = { history: [], hasMore: false }

export const useHistoryStore = create<HistoryState>()((set) => ({
  ...initialState,
  setHistory: (history, hasMore = false) => set({ history, hasMore }),
  appendHistory: (items, hasMore) =>
    set((state) => {
      const seen = new Set(state.history.map((item) => item.session_id))
      const merged = [...state.history, ...items.filter((item) => !seen.has(item.session_id))]
      return { history: merged, hasMore }
    }),
  reset: () => set({ ...initialState }),
}))
