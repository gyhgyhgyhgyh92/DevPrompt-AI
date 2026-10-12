import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getHealth, putSettings } from '../../api/endpoints'
import type { SettingsResponse } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { ModelServicePanel } from './ModelServicePanel'

vi.mock('../../api/endpoints', () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  getHealth: vi.fn(),
  getPreference: vi.fn(),
  putPreference: vi.fn(),
  getHistory: vi.fn(),
}))

const settingsFixture: SettingsResponse = {
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.example.com',
    decider: 'auto',
    model_id: 'demo-model',
    timeout: 60,
    max_tokens: null,
    temperature: null,
  },
  process: {
    followup_cost_budget: 2,
    followup_soft_round_guard: 12,
    telemetry: true,
  },
  locked: { candidate_limit: 30 },
}

function apiKeyInput(): HTMLInputElement {
  return screen.getByLabelText('API Key') as HTMLInputElement
}

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.setState({ settings: settingsFixture })
  vi.mocked(putSettings).mockResolvedValue(settingsFixture)
  vi.mocked(getHealth).mockResolvedValue({
    checks: [{ name: 'llm_config', ok: true, detail: 'https://api.example.com / demo-model' }],
    is_healthy: true,
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ModelServicePanel 模型服务', () => {
  it('API Key 回显恒脱敏且输入为 password 类型', () => {
    render(<ModelServicePanel />)

    const input = apiKeyInput()
    expect(input.type).toBe('password')
    expect(input.placeholder).toBe('sk-••••3f7a')
    expect(input.value).toBe('')
    expect(screen.getByText(/当前密钥：sk-••••3f7a/)).toBeTruthy()
  })

  it('空密钥保存时不回传任何明文字段', async () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    const body = vi.mocked(putSettings).mock.calls[0]?.[0]
    expect(body?.model_service?.api_key).toBeUndefined()
    expect(JSON.stringify(body)).not.toContain('api_key')
  })

  it('仅输入新值才回传明文，保存后输入清空且回显新的脱敏值', async () => {
    const next: SettingsResponse = {
      ...settingsFixture,
      model_service: { ...settingsFixture.model_service, api_key_masked: 'sk-••••9a2b' },
    }
    vi.mocked(putSettings).mockResolvedValue(next)
    render(<ModelServicePanel />)

    fireEvent.change(apiKeyInput(), { target: { value: 'new-secret-value' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    expect(vi.mocked(putSettings).mock.calls[0]?.[0].model_service?.api_key).toBe(
      'new-secret-value',
    )

    await waitFor(() => expect(screen.getByText(/当前密钥：sk-••••9a2b/)).toBeTruthy())
    expect(apiKeyInput().value).toBe('')
    expect(document.body.textContent).not.toContain('new-secret-value')
  })

  it('保存调用 PUT /settings 并按回读结果刷新表单', async () => {
    const next: SettingsResponse = {
      ...settingsFixture,
      model_service: { ...settingsFixture.model_service, model_id: 'model-x' },
    }
    vi.mocked(putSettings).mockResolvedValue(next)
    render(<ModelServicePanel />)

    fireEvent.change(screen.getByLabelText('模型 ID'), { target: { value: 'model-x' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    expect(vi.mocked(putSettings).mock.calls[0]?.[0].model_service?.model_id).toBe('model-x')
    await waitFor(() =>
      expect((screen.getByLabelText('模型 ID') as HTMLInputElement).value).toBe('model-x'),
    )
    expect(screen.getByText('已保存')).toBeTruthy()
    expect(useSettingsStore.getState().settings).toEqual(next)
  })

  it('测试连接先保存再读 GET /health 的 LLM 配置检查位', async () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '测试连接' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(getHealth).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/LLM 配置检查通过/)).toBeTruthy()
    expect(screen.getByText(/https:\/\/api\.example\.com \/ demo-model/)).toBeTruthy()
  })

  it('供应商分段选择预填 Base URL', () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: 'DeepSeek' }))

    expect((screen.getByLabelText('Base URL') as HTMLInputElement).value).toBe(
      'https://api.deepseek.com',
    )
  })
})
