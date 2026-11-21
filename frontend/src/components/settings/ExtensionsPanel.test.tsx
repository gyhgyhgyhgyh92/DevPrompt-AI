import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SettingsResponse } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { ExtensionsPanel } from './ExtensionsPanel'

vi.mock('../../api/endpoints', () => ({
  putSettings: vi.fn(),
  testMcpServer: vi.fn(),
}))

const fixture = {
  models: [],
  provider_configs: [],
  providers: [],
  model_service: {
    api_key_masked: '',
    base_url: '',
    model_id: '',
    provider: '',
    timeout: 60,
    max_tokens: null,
    temperature: null,
  },
  process: { followup_cost_budget: 1, followup_soft_round_guard: 10, telemetry: true },
  observability: {
    trace_enabled: true,
    trace_retention_days: 30,
    metrics_enabled: true,
    replay_enabled: true,
  },
  locked: { candidate_limit: 50 },
  skills: {
    dirs: ['/skills'],
    items: [
      { skill_id: '', name: '目录技能', description: '来自目录', source: 'dir', domains: [], enabled: true },
      { skill_id: 'k1', name: '自定义技能', description: '来自界面', source: 'custom', domains: [], enabled: true },
    ],
  },
  mcp_servers: [
    {
      id: 's1',
      name: '本地工具',
      transport: 'stdio',
      command: 'python',
      args: [],
      env: {},
      url: '',
      headers: {},
      enabled: true,
      tool_allowlist: [],
    },
  ],
} as unknown as SettingsResponse

afterEach(() => cleanup())

describe('ExtensionsPanel', () => {
  beforeEach(() => {
    useSettingsStore.getState().setSettings(fixture)
  })

  it('同时显示两个来源的技能与已配置的 Server', () => {
    render(<ExtensionsPanel />)
    expect(screen.getByText('技能')).toBeTruthy()
    expect(screen.getByText('目录技能')).toBeTruthy()
    expect(screen.getByText('自定义技能')).toBeTruthy()
    expect(screen.getByText('本地工具')).toBeTruthy()
  })

  it('stdio 未勾选风险确认时添加按钮禁用', () => {
    render(<ExtensionsPanel />)
    expect(screen.getByText(/等同于运行任意程序/)).toBeTruthy()
    const add = screen.getByRole('button', { name: '添加 Server' }) as HTMLButtonElement
    expect(add.disabled).toBe(true)
  })
})
