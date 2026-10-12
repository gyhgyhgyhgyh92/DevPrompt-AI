import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse } from '../api/types'
import { usePreferenceStore } from '../stores/usePreferenceStore'
import { PreferencePage } from './PreferencePage'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  usePreferenceStore.getState().reset()
})

describe('PreferencePage 偏好四维展示', () => {
  it('渲染 GET /preference 四维展示条', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        headers: { get: () => null },
        json: async () =>
          envelope({
            detail_level: 0.25,
            include_diff: 0.75,
            specify_tests: 0.1,
            max_files_norm: 0.9,
          }),
      })),
    )

    render(
      <MemoryRouter>
        <PreferencePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('detail_level')).toBeTruthy()
    expect(screen.getByText('include_diff')).toBeTruthy()
    expect(screen.getByText('specify_tests')).toBeTruthy()
    expect(screen.getByText('max_files_norm')).toBeTruthy()
    expect(screen.getByText('25%')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '偏好管理' })).toBeTruthy()
  })

  it('数据缺位时渲染空态文案', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        headers: { get: () => null },
        json: async () => envelope(null),
      })),
    )

    render(
      <MemoryRouter>
        <PreferencePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('暂无偏好数据')).toBeTruthy()
  })
})
