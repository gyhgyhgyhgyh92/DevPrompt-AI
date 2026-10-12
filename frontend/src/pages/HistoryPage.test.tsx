import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse, HistoryItemPayload } from '../api/types'
import { usePreferenceStore } from '../stores/usePreferenceStore'
import { HistoryPage } from './HistoryPage'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  usePreferenceStore.getState().reset()
})

describe('HistoryPage 历史列表', () => {
  it('渲染 GET /history 列表（时间/state/项目名）', async () => {
    const items: HistoryItemPayload[] = [
      {
        session_id: 'sess-1',
        state: 'DONE',
        project: 'D:/ws/repo',
        title: '加个导出按钮',
        pinned: false,
        updated_at: '2026-10-12T08:00:00Z',
      },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        headers: { get: () => null },
        json: async () => envelope(items),
      })),
    )

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('DONE')).toBeTruthy()
    expect(screen.getByText('repo')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '历史记录' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '← 工作台' })).toBeTruthy()
  })

  it('列表为空时渲染空态文案', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        headers: { get: () => null },
        json: async () => envelope([]),
      })),
    )

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('暂无历史记录')).toBeTruthy()
  })
})
