import { create } from 'zustand'
import type { HistoryItemPayload, PreferenceVectorPayload } from '../api/types'
import { APPEARANCE_KEY, STORAGE_PREFIX } from './useSettingsStore'

/** 偏好向量与采纳历史（F-706）：应用级跨页面共享；数据获取在 api/hooks，store 只存结果。 */
interface PreferenceState {
  vector: PreferenceVectorPayload | null
  history: readonly HistoryItemPayload[]
  setVector: (vector: PreferenceVectorPayload) => void
  setHistory: (history: readonly HistoryItemPayload[]) => void
  clearLocalHistory: () => void
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
  // 服务端清空走 DELETE /preference/adoptions 且成功后才调本方法：此处只清前端本地留存，外观设置键保留
  clearLocalHistory: () => {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(STORAGE_PREFIX) && key !== APPEARANCE_KEY) {
        localStorage.removeItem(key)
      }
    }
    set({ history: [] })
  },
  reset: () => set({ ...initialState }),
}))
