import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getModelCatalog, putSettings, refreshModelCatalog } from '../../api/endpoints'
import type { ModelCatalogResponse } from '../../api/endpoints'
import type { SettingsResponse } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { ModelServicePanel } from './ModelServicePanel'

vi.mock('../../api/endpoints', () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  getHealth: vi.fn(),
  getHistory: vi.fn(),
  refreshModelCatalog: vi.fn(),
  getModelCatalog: vi.fn(),
}))

/** 目录条目 fixture：`reasoning_efforts` 可省，由 catalogOf 补空数组。 */
type CatalogItem = Omit<
  ModelCatalogResponse['models'][number],
  'reasoning_efforts' | 'default_effort' | 'context_window_tiers' | 'max_context_length'
> & {
  reasoning_efforts?: string[]
  default_effort?: string
  context_window_tiers?: number[]
  max_context_length?: number | null
}

function catalogOf(models: CatalogItem[], warning: string | null = null): ModelCatalogResponse {
  return {
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com',
    fetched_at: '2026-10-18T00:00:00.000Z',
    warning,
    models: models.map((m) => ({
      ...m,
      context_window_tiers: m.context_window_tiers ?? [],
      reasoning_efforts: m.reasoning_efforts ?? [],
      default_effort: m.default_effort ?? '',
    })),
  }
}

const settingsFixture: SettingsResponse = {
  models: [
    {
      id: 'm-1',
      provider_id: 'p-deepseek',
      provider: 'deepseek',
      model_id: 'deepseek-flash',
      is_active: true,
    },
  ],
  provider_configs: [
    {
      id: 'p-deepseek',
      provider: 'deepseek',
      base_url: 'https://api.deepseek.com',
      api_key_masked: 'sk-••••3f7a',
    },
  ],
  providers: [
    {
      id: 'deepseek',
      label: 'DeepSeek',
      base_url: 'https://api.deepseek.com',
      needs_key: true,
      default_api_mode: 'chat_completions',
      supported_api_modes: ['chat_completions'],
      max_context_length: 1_048_576,
      context_window_tiers: [131_072, 307_200, 614_400, 1_048_576],
      models: [],
      supports_reasoning: true,
      quirks: '',
    },
  ],
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.deepseek.com',
    model_id: 'deepseek-flash',
    provider: 'deepseek',
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
  },
  locked: { candidate_limit: 30 },
}

const CATALOG: ModelCatalogResponse = catalogOf([
  { model_id: 'deepseek-flash', label: 'Flash', source: 'remote', is_stale: false },
  { model_id: 'deepseek-v4-pro', label: 'Pro', source: 'remote', is_stale: false },
])

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.setState({ settings: settingsFixture })
  vi.mocked(getModelCatalog).mockResolvedValue(CATALOG)
  vi.mocked(putSettings).mockResolvedValue(settingsFixture)
  vi.mocked(refreshModelCatalog).mockResolvedValue(CATALOG)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ModelServicePanel 供应商中心化配置（F-604）', () => {
  it('渲染供应商卡：厂商名 / Base URL / 密钥脱敏回显', async () => {
    render(<ModelServicePanel />)

    expect(document.querySelector('[class*="settings-model-row__title"]')?.textContent).toBe(
      'DeepSeek',
    )
    expect(screen.getByLabelText('Base URL')).toHaveProperty('value', 'https://api.deepseek.com')
    const key = screen.getByLabelText('API Key') as HTMLInputElement
    expect(key.type).toBe('password')
    expect(key.placeholder).toBe('sk-••••3f7a')
    expect(screen.getByText(/当前密钥：sk-••••3f7a/)).toBeTruthy()
    await waitFor(() => expect(getModelCatalog).toHaveBeenCalledWith('p-deepseek'))
  })

  it('已配置的模型默认勾选，目录列表按 model_id 展示', async () => {
    render(<ModelServicePanel />)

    await waitFor(() => expect(screen.getByLabelText(/deepseek-v4-pro/)).toBeTruthy())
    expect((screen.getByLabelText(/deepseek-flash/) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText(/deepseek-v4-pro/) as HTMLInputElement).checked).toBe(false)
  })

  it('多选模型后一键保存：提交权威 providers + 仅勾选的 models', async () => {
    render(<ModelServicePanel />)
    await waitFor(() => expect(screen.getByLabelText(/deepseek-v4-pro/)).toBeTruthy())

    fireEvent.click(screen.getByLabelText(/deepseek-v4-pro/))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    const body = vi.mocked(putSettings).mock.calls[0]?.[0]
    expect(body?.provider_configs).toEqual([
      { id: 'p-deepseek', provider: 'deepseek', base_url: 'https://api.deepseek.com' },
    ])
    expect(body?.models?.map((m) => m.model_id)).toEqual(['deepseek-flash', 'deepseek-v4-pro'])
    // 已存在的条目沿用 id（避免后端另建一条）
    expect(body?.models?.[0]?.id).toBe('m-1')
    // 密钥不回传明文（前端只有脱敏值，MUST-19）
    expect(JSON.stringify(body)).not.toContain('"api_key"')
  })

  it('取消勾选后保存：未勾选的条目随整表替换被删除', async () => {
    render(<ModelServicePanel />)
    await waitFor(() => expect(screen.getByLabelText(/deepseek-flash/)).toBeTruthy())

    fireEvent.click(screen.getByLabelText(/deepseek-flash/))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalled())
    expect(vi.mocked(putSettings).mock.calls[0]?.[0]?.models).toEqual([])
  })

  it('刷新模型列表：先保存再按 provider_id 现场拉取', async () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '刷新模型列表' }))

    await waitFor(() => expect(refreshModelCatalog).toHaveBeenCalledWith('p-deepseek'))
    // 后端按 provider_id 从设置文件取密钥，新供应商必须先落盘
    expect(vi.mocked(putSettings).mock.calls[0]?.[0]?.provider_configs?.[0]?.id).toBe('p-deepseek')
  })

  it('测试连接在供应商级：复用刷新端点探测端点 + 密钥', async () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '测试连接' }))

    await waitFor(() => expect(screen.getByText('连接成功')).toBeTruthy())
    expect(refreshModelCatalog).toHaveBeenCalledWith('p-deepseek')
  })

  it('测试失败时供应商卡显示原因', async () => {
    vi.mocked(refreshModelCatalog).mockResolvedValue(catalogOf([], '鉴权失败：请检查 API Key'))
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '测试连接' }))

    expect(await screen.findByText('鉴权失败：请检查 API Key')).toBeTruthy()
  })

  it('测试连接同样先保存：刚新增未落盘的供应商也能探测', async () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '新增供应商' }))
    fireEvent.change(screen.getAllByLabelText('供应商')[1] as HTMLSelectElement, {
      target: { value: 'deepseek' },
    })
    fireEvent.change(screen.getAllByLabelText('Base URL')[1] as HTMLInputElement, {
      target: { value: 'https://relay.example.com/v1' },
    })
    fireEvent.change(screen.getAllByLabelText('API Key')[1] as HTMLInputElement, {
      target: { value: 'sk-new-secret' },
    })
    fireEvent.click(screen.getAllByRole('button', { name: '测试连接' })[1]!)

    await waitFor(() => expect(refreshModelCatalog).toHaveBeenCalled())
    // 后端按 provider_id 从设置文件取密钥，故必须先落盘（供应商带 id）再探测
    const configs = vi.mocked(putSettings).mock.calls[0]?.[0]?.provider_configs ?? []
    expect(configs[1]?.base_url).toBe('https://relay.example.com/v1')
    expect(refreshModelCatalog).toHaveBeenCalledWith(configs[1]?.id)
    expect(await screen.findAllByText('连接成功')).toBeTruthy()
  })

  it('新增供应商：预生成 id 并在保存时随请求下发', async () => {
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '新增供应商' }))
    fireEvent.change(screen.getAllByLabelText('供应商')[1] as HTMLSelectElement, {
      target: { value: 'deepseek' },
    })
    fireEvent.change(screen.getAllByLabelText('Base URL')[1] as HTMLInputElement, {
      target: { value: 'https://relay.example.com/v1' },
    })
    fireEvent.change(screen.getAllByLabelText('API Key')[1] as HTMLInputElement, {
      target: { value: 'sk-new-secret' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalled())
    const configs = vi.mocked(putSettings).mock.calls[0]?.[0]?.provider_configs ?? []
    expect(configs).toHaveLength(2)
    expect(configs[1]?.base_url).toBe('https://relay.example.com/v1')
    expect(configs[1]?.api_key).toBe('sk-new-secret')
    // 新供应商也带 id，条目才能在同一次请求里引用它
    expect(String(configs[1]?.id)).toMatch(/^p-/)
  })

  it('删除供应商：级联确认后从列表移除（保存时不再下发）', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '删除供应商' }))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalled())
    expect(vi.mocked(putSettings).mock.calls[0]?.[0]?.provider_configs).toEqual([])
    expect(vi.mocked(putSettings).mock.calls[0]?.[0]?.models).toEqual([])
    confirmSpy.mockRestore()
  })

  it('取消级联确认时保留供应商', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<ModelServicePanel />)

    fireEvent.click(screen.getByRole('button', { name: '删除供应商' }))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalled())
    expect(vi.mocked(putSettings).mock.calls[0]?.[0]?.provider_configs).toHaveLength(1)
    confirmSpy.mockRestore()
  })

  it('思考强度 / 上下文窗口 / 全局调用参数均不在设置面板（已迁至启动页）', () => {
    render(<ModelServicePanel />)

    expect(screen.queryByLabelText('上下文窗口')).toBeNull()
    expect(screen.queryByLabelText('思考强度')).toBeNull()
    expect(screen.queryByLabelText('超时（秒）')).toBeNull()
    expect(screen.queryByLabelText('温度')).toBeNull()
    expect(screen.queryByLabelText('max_tokens')).toBeNull()
  })

  it('空供应商列表给出引导文案', () => {
    useSettingsStore.setState({ settings: { ...settingsFixture, provider_configs: [] } })
    render(<ModelServicePanel />)
    expect(screen.getByText(/尚未配置任何供应商/)).toBeTruthy()
  })

  it('切换供应商即清空原有勾选与目录（防止把别家模型写进新供应商）', async () => {
    const moonshot = {
      ...settingsFixture.providers![0]!,
      id: 'moonshot',
      label: 'Moonshot',
      base_url: 'https://api.moonshot.cn/v1',
    }
    useSettingsStore.setState({
      settings: { ...settingsFixture, providers: [...(settingsFixture.providers ?? []), moonshot] },
    })
    render(<ModelServicePanel />)
    expect(await screen.findByRole('checkbox', { name: /deepseek-flash/ })).toBeTruthy()
    expect(screen.getByText('1 个模型')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('供应商'), { target: { value: 'moonshot' } })

    expect(screen.getByText('0 个模型')).toBeTruthy()
    expect(screen.getByText(/原有模型勾选与目录已清空/)).toBeTruthy()
    expect((screen.getByLabelText('Base URL') as HTMLInputElement).value).toBe(
      'https://api.moonshot.cn/v1',
    )
    expect(screen.queryByRole('checkbox', { name: /deepseek-flash/ })).toBeNull()
  })

  it('已配置但不在目录里的模型标出「不在当前列表」，不冒充该供应商的模型', async () => {
    vi.mocked(getModelCatalog).mockResolvedValue(
      catalogOf([
        {
          model_id: 'deepseek-flash',
          label: 'deepseek-flash（不在当前列表）',
          source: 'static',
          is_stale: true,
        },
      ]),
    )
    render(<ModelServicePanel />)

    expect(await screen.findByText('不在当前列表')).toBeTruthy()
  })
})
