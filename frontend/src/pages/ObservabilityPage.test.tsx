import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import { getHistory, getSettings } from '../api/endpoints'
import type { SettingsResponse } from '../api/types'
import { useSettingsStore } from '../stores/useSettingsStore'
import { ObservabilityPage } from './ObservabilityPage'

vi.mock('../api/endpoints', () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  getHistory: vi.fn(),
  getSessionEvents: vi.fn(async () => []),
  openSessionStream: vi.fn(() => () => undefined),
  getObsTraces: vi.fn(),
  getObsEvents: vi.fn(),
  getObsEvent: vi.fn(),
  getObsMetricsSummary: vi.fn(async () => ({ items: [], schema_version: 1 })),
  getObsAlerts: vi.fn(async () => ({ items: [], limit: 50, offset: 0, schema_version: 1 })),
  getObsMetricsConfig: vi.fn(async () => ({ config: {}, schema_version: 1 })),
  getObsReplayRun: vi.fn(),
}))

function settingsFixture(overrides: Partial<SettingsResponse['observability']> = {}) {
  return {
    models: [],
    model_service: {
      api_key_masked: '',
      base_url: '',
      model_id: '',
      provider: '',
      timeout: 60,
      max_tokens: null,
      temperature: null,
    },
    process: { followup_cost_budget: 2, followup_soft_round_guard: 12, telemetry: true },
    observability: {
      trace_enabled: true,
      trace_retention_days: 30,
      metrics_enabled: true,
      replay_enabled: true,
      ...overrides,
    },
    locked: { candidate_limit: 30 },
  } satisfies SettingsResponse
}

beforeEach(() => {
  useSettingsStore.setState({ settings: null })
  vi.mocked(getSettings).mockResolvedValue(settingsFixture())
  vi.mocked(getHistory).mockResolvedValue({
    items: [
      {
        session_id: 's-1',
        state: 'DONE',
        project: 'demo',
        project_root: 'C:/demo',
        updated_at: '2026-11-12T00:00:00Z',
        title: '可观测性会话',
        pinned: false,
      },
    ],
    has_more: false,
    limit: 50,
    offset: 0,
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  useSettingsStore.setState({ settings: null })
})

describe('ObservabilityPage', () => {
  it('渲染页面标题与返回工作台链接', () => {
    render(
      <MemoryRouter>
        <ObservabilityPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { level: 1, name: '可观测性' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '← 工作台' }).getAttribute('href')).toBe('/')
  })

  it('设置未就绪时回读后端设置并据此决定模块标签可见性', async () => {
    vi.mocked(getSettings).mockResolvedValue(settingsFixture({ metrics_enabled: false }))

    render(
      <MemoryRouter>
        <ObservabilityPage />
      </MemoryRouter>,
    )

    await waitFor(() => expect(getSettings).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByRole('tab', { name: 'Metrics' })).toBeNull())
    expect(screen.getByRole('tab', { name: 'Session Log' })).toBeTruthy()
  })

  it('设置已在 store 时不重复回读', async () => {
    useSettingsStore.setState({ settings: settingsFixture() })

    render(
      <MemoryRouter>
        <ObservabilityPage />
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByRole('tab', { name: 'Session Log' })).toBeTruthy())
    expect(getSettings).not.toHaveBeenCalled()
  })
})
