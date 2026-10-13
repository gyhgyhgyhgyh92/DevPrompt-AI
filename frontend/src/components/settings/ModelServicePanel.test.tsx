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
  models: [
    {
      id: 'm-1',
      label: 'DeepSeek · deepseek-flash',
      provider: 'DeepSeek',
      base_url: 'https://api.example.com',
      model_id: 'deepseek-flash',
      api_key_masked: 'sk-••••3f7a',
      is_active: true,
    },
    {
      id: 'm-2',
      label: 'OpenAI 兼容 · gpt-x',
      provider: 'OpenAI 兼容',
      base_url: 'https://api.openai.com/v1',
      model_id: 'gpt-x',
      api_key_masked: 'sk-••••9a2b',
      is_active: false,
    },
  ],
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.example.com',
    decider: 'auto',
    model_id: 'deepseek-flash',
    provider: 'DeepSeek',
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

/** 第 n 条模型行的 API Key 输入（label 含条目 key，用序号定位）。 */
function apiKeyInput(index = 0): HTMLInputElement {
  return screen.getAllByLabelText('API Key')[index] as HTMLInputElement
}

function modelIdInput(index = 0): HTMLInputElement {
  return screen.getAllByLabelText('模型 ID')[index] as HTMLInputElement
}

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.setState({ settings: settingsFixture })
  vi.mocked(putSettings).mockResolvedValue(settingsFixture)
  vi.mocked(getHealth).mockResolvedValue({
    checks: [{ name: 'llm_config', ok: true, detail: 'https://api.example.com / deepseek-flash' }],
    is_healthy: true,
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ModelServicePanel 模型列表管理（F-604 多模型）', () => {
  it('渲染注册表条目：脱敏密钥、当前徽标与行内操作', () => {
    render(<ModelServicePanel />)

    expect(screen.getByText('DeepSeek · deepseek-flash')).toBeTruthy()
    expect(screen.getByText('OpenAI 兼容 · gpt-x')).toBeTruthy()
    expect(screen.getByText('当前')).toBeTruthy() // 仅激活条目带徽标
    expect(apiKeyInput(0).type).toBe('password')
    expect(apiKeyInput(0).placeholder).toBe('sk-••••3f7a')
    expect(apiKeyInput(0).value).toBe('')
    expect(screen.getByText(/当前密钥：sk-••••3f7a/)).toBeTruthy()
    // 已激活条目的「设为当前」禁用；未激活条目可用
    const setActive = screen.getAllByRole('button', { name: '设为当前' })
    expect((setActive[0] as HTMLButtonElement).disabled).toBe(true)
    expect((setActive[1] as HTMLButtonElement).disabled).toBe(false)
  })

  it('「设为当前」切换激活位并随保存提交 active_model_id', async () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getAllByRole('button', { name: '设为当前' })[1] as HTMLButtonElement)
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    const body = vi.mocked(putSettings).mock.calls[0]?.[0]
    expect(body?.active_model_id).toBe('m-2')
    expect(body?.models?.map((m) => m.id)).toEqual(['m-1', 'm-2'])
  })

  it('空密钥保存时不回传任何 api_key 明文（MUST-19）', async () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    const body = vi.mocked(putSettings).mock.calls[0]?.[0]
    expect(body?.models?.every((m) => m.api_key === undefined)).toBe(true)
    expect(JSON.stringify(body)).not.toContain('api_key')
  })

  it('仅输入新值才回传明文；保存后按回读结果刷新（输入清空、回显新脱敏值）', async () => {
    const next: SettingsResponse = {
      ...settingsFixture,
      models: [{ ...settingsFixture.models[0]!, api_key_masked: 'sk-••••9a2b' }],
    }
    vi.mocked(putSettings).mockResolvedValue(next)
    render(<ModelServicePanel />)

    fireEvent.change(apiKeyInput(0), { target: { value: 'new-secret-value' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    expect(vi.mocked(putSettings).mock.calls[0]?.[0].models?.[0]?.api_key).toBe('new-secret-value')

    await waitFor(() => expect(screen.getByText(/当前密钥：sk-••••9a2b/)).toBeTruthy())
    expect(apiKeyInput(0).value).toBe('')
    expect(document.body.textContent).not.toContain('new-secret-value')
  })

  it('新增模型追加草稿行（未保存时「设为当前」禁用）；删除行移除条目', () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '新增模型' }))
    expect(screen.getAllByLabelText('模型 ID')).toHaveLength(3)
    expect(
      (screen.getAllByRole('button', { name: '设为当前' })[2] as HTMLButtonElement).disabled,
    ).toBe(true)

    fireEvent.click(screen.getAllByRole('button', { name: '删除' })[2] as HTMLButtonElement)
    expect(screen.getAllByLabelText('模型 ID')).toHaveLength(2)
  })

  it('模型 ID 为空校验失败并提示，不发起请求', async () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '新增模型' }))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByText('每个模型条目都必须填写模型 ID')).toBeTruthy()
    expect(putSettings).not.toHaveBeenCalled()
  })

  it('保存同时提交全局调用参数（decider/超时/温度/max_tokens）', async () => {
    render(<ModelServicePanel />)

    fireEvent.change(screen.getByLabelText('超时（秒）'), { target: { value: '90' } })
    fireEvent.change(screen.getByLabelText('max_tokens'), { target: { value: '2048' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    const body = vi.mocked(putSettings).mock.calls[0]?.[0]
    expect(body?.model_service?.decider).toBe('auto')
    expect(body?.model_service?.timeout).toBe(90)
    expect(body?.model_service?.max_tokens).toBe(2048)
  })

  it('非数字调用参数报错且不发起请求', async () => {
    render(<ModelServicePanel />)

    fireEvent.change(screen.getByLabelText('超时（秒）'), { target: { value: 'abc' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByText('调用参数必须是数字')).toBeTruthy()
    expect(putSettings).not.toHaveBeenCalled()
  })

  it('测试连接先保存再读 GET /health 的 LLM 配置检查位', async () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '测试连接' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(getHealth).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/LLM 配置检查通过/)).toBeTruthy()
    expect(screen.getByText(/https:\/\/api\.example\.com \/ deepseek-flash/)).toBeTruthy()
  })

  it('供应商切换预填 Base URL 并随条目上送', async () => {
    render(<ModelServicePanel />)

    fireEvent.change(screen.getAllByLabelText('供应商')[0] as HTMLSelectElement, {
      target: { value: 'DeepSeek' },
    })
    expect((screen.getAllByLabelText('Base URL')[0] as HTMLInputElement).value).toBe(
      'https://api.deepseek.com',
    )

    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    const body = vi.mocked(putSettings).mock.calls[0]?.[0]
    expect(body?.models?.[0]?.provider).toBe('DeepSeek')
    expect(body?.models?.[0]?.base_url).toBe('https://api.deepseek.com')
  })

  it('空注册表展示引导文案并可直接新增', () => {
    useSettingsStore.setState({ settings: { ...settingsFixture, models: [] } })
    render(<ModelServicePanel />)

    expect(screen.getByText(/尚未配置任何模型/)).toBeTruthy()
    expect(screen.queryByText('当前')).toBeNull()
  })

  it('保存调用 PUT /settings 并按回读结果刷新条目', async () => {
    const next: SettingsResponse = {
      ...settingsFixture,
      models: [{ ...settingsFixture.models[0]!, label: '改名后的模型' }],
    }
    vi.mocked(putSettings).mockResolvedValue(next)
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByText('改名后的模型')).toBeTruthy())
    expect(screen.getByText('已保存')).toBeTruthy()
    expect(useSettingsStore.getState().settings).toEqual(next)
  })

  it('编辑模型 ID 随 models 段上送（每行独立）', async () => {
    render(<ModelServicePanel />)

    fireEvent.change(modelIdInput(1), { target: { value: 'gpt-y' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    const body = vi.mocked(putSettings).mock.calls[0]?.[0]
    expect(body?.models?.[1]?.model_id).toBe('gpt-y')
    expect(body?.models?.[0]?.model_id).toBe('deepseek-flash')
  })
})
