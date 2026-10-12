import { beforeEach, describe, expect, it } from 'vitest'
import { usePreferenceStore } from './usePreferenceStore'

beforeEach(() => {
  usePreferenceStore.getState().reset()
})

describe('usePreferenceStore', () => {
  it('setVector 更新 L3 偏好向量', () => {
    usePreferenceStore.getState().setVector({
      detail_level: 0.25,
      include_diff: 0.75,
      specify_tests: 0.1,
      max_files_norm: 0.9,
    })

    expect(usePreferenceStore.getState().vector).toMatchObject({ detail_level: 0.25 })
  })

  it('setHistory 更新采纳历史列表', () => {
    usePreferenceStore.getState().setHistory([
      {
        session_id: 'sess-1',
        state: 'DONE',
        project: 'D:/repo',
        title: '加个导出按钮',
        pinned: false,
        updated_at: '2026-10-12T00:00:00Z',
      },
    ])

    expect(usePreferenceStore.getState().history).toHaveLength(1)
  })

  it('reset 清空向量与历史', () => {
    usePreferenceStore.getState().setVector({
      detail_level: 0.25,
      include_diff: 0.75,
      specify_tests: 0.1,
      max_files_norm: 0.9,
    })

    usePreferenceStore.getState().reset()

    expect(usePreferenceStore.getState().vector).toBeNull()
    expect(usePreferenceStore.getState().history).toEqual([])
  })
})
