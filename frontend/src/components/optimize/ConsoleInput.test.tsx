import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse, SettingsResponse } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { ConsoleInput } from './ConsoleInput'
import { isNativeBridgeReady, pickFolderViaNative } from '../../api/nativeFolder'

const PROMPT_HINT = '帮你优化每一段提示词，从理清需求到上线-端到端交付生产级结果'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

vi.mock('../../api/nativeFolder', () => ({
  NOT_INSTALLED_HINT: '未安装扩展',
  isNativeBridgeReady: vi.fn(() => true),
  nativeBridgeMissingHint: () => '未检测到扩展，请刷新页面',
  nativePickErrorText: (e: unknown) => (e instanceof Error ? e.message : String(e)),
  pickFolderViaNative: vi.fn(async () => ({ path: '' })),
}))

const MODEL_ENTRIES: SettingsResponse['models'] = [
  {
    id: 'm-1',
    provider_id: 'p-deepseek',
    provider: 'DeepSeek',
    model_id: 'deepseek-flash',
    is_active: true,
  },
  {
    id: 'm-2',
    provider_id: 'p-openai',
    provider: 'OpenAI 兼容',
    model_id: 'gpt-x',
    is_active: false,
  },
]

const settingsFixture: SettingsResponse = {
  models: MODEL_ENTRIES,
  provider_configs: [
    {
      id: 'p-deepseek',
      provider: 'DeepSeek',
      base_url: 'https://api.deepseek.com',
      api_key_masked: 'sk-••••3f7a',
    },
    {
      id: 'p-openai',
      provider: 'OpenAI 兼容',
      base_url: 'https://api.openai.com/v1',
      api_key_masked: 'sk-••••9a2b',
    },
  ],
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.deepseek.com',
    model_id: 'deepseek-flash',
    provider: 'DeepSeek',
    temperature: null,
    max_tokens: null,
    timeout: 60,
  },
  process: { followup_cost_budget: 1, followup_soft_round_guard: 10, telemetry: true },
  observability: {
    trace_enabled: true,
    trace_retention_days: 30,
    metrics_enabled: true,
    replay_enabled: true,
  },
  locked: { candidate_limit: 25 },
}

/** URL 分流 stub：/project/browse 与 /project/scan 各取自己的 JSON（其余回 null）。 */
function stubFetchByUrl(payloadByPath: { browse: unknown; scan?: unknown }) {
  const mock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    const payload = url.includes('/project/browse')
      ? payloadByPath.browse
      : url.includes('/project/scan')
        ? (payloadByPath.scan ?? envelope({ total_symbols: 1, total_files: 1, kind_counts: {} }))
        : envelope(null)
    return {
      status: 200,
      headers: { get: () => null },
      json: async () => payload,
    }
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

/** 模型选择器触发器（2026-10-18 起是自定义下拉，不再是原生 combobox）。 */
function modelTrigger(): HTMLButtonElement {
  return screen.getByRole('button', { name: '选择模型' }) as HTMLButtonElement
}

beforeEach(() => {
  useSettingsStore.setState({ settings: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useSettingsStore.setState({ settings: null })
})

describe('ConsoleInput 启动页主视觉卡片', () => {
  it('渲染居中卡片结构（console-input 容器 + 卡片）', () => {
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    expect(document.querySelector('[class*="console-input"]')).not.toBeNull()
    expect(document.querySelector('[class*="console-input__card"]')).not.toBeNull()
  })

  it('输入区展示固定文案占位（逐字）', () => {
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    expect(screen.getByRole('textbox', { name: '优化原句' })).toHaveProperty(
      'placeholder',
      PROMPT_HINT,
    )
  })

  it('六项移除元素在 DOM 中零存在（附件/审批/文件类型组/麦克风/音频/本地）', () => {
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    expect(screen.queryByText('＋')).toBeNull()
    expect(screen.queryByText('手动审批')).toBeNull()
    expect(screen.queryByText('本地')).toBeNull()
    expect(screen.queryByLabelText('添加附件')).toBeNull()
    expect(screen.queryByLabelText('麦克风')).toBeNull()
    expect(screen.queryByLabelText('音频')).toBeNull()
    expect(screen.queryByRole('button', { name: /附件|审批|麦克风|音频|文件类型/ })).toBeNull()
    // 独立「本地」选择器零存在（文件夹按钮命名为「选择文件夹（本地）」，非独立本地项）
    expect(screen.queryByRole('button', { name: '本地' })).toBeNull()
  })

  it('输入换行时按行数增高，最多 6 行（jsdom 无 scrollHeight，走 fallback 行数）', () => {
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)
    const box = screen.getByRole('textbox', { name: '优化原句' })

    expect(box.getAttribute('rows')).toBe('1')

    fireEvent.change(box, { target: { value: '第一行\n第二行\n第三行' } })
    expect(box.getAttribute('rows')).toBe('3')

    const many = Array.from({ length: 9 }, (_, index) => `第 ${index} 行`).join('\n')
    fireEvent.change(box, { target: { value: many } })
    expect(box.getAttribute('rows')).toBe('6')
  })

  it('无输入时发送按钮禁用（防重复/防误触，MUST-15）', () => {
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('模型下拉默认选中当前生效条目，展开后列出全部已配置条目（模型 ID）', async () => {
    useSettingsStore.setState({ settings: settingsFixture })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    // 2026-10-18 起是自定义下拉（原生 select 无法承载 hover 参数面板）
    expect(modelTrigger().textContent).toBe('deepseek-flash')
    fireEvent.click(modelTrigger())
    await waitFor(() => expect(screen.getByRole('button', { name: 'gpt-x' })).toBeTruthy())
  })

  it('切换模型经 PUT /settings 提交 active_model_id 并更新展示', async () => {
    const switched = {
      ...settingsFixture,
      models: [
        { ...MODEL_ENTRIES[0]!, is_active: false },
        { ...MODEL_ENTRIES[1]!, is_active: true },
      ],
    }
    const fetchMock = stubFetchByUrl({ browse: envelope(null) })
    fetchMock.mockImplementation(async () => ({
      status: 200,
      headers: { get: () => null },
      json: async () => envelope(switched),
    }))
    useSettingsStore.setState({ settings: settingsFixture })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    fireEvent.click(modelTrigger())
    await waitFor(() => expect(screen.getByRole('button', { name: 'gpt-x' })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'gpt-x' }))

    const putCall = fetchMock.mock.calls.find(
      (call) => String(call[0]).includes('/settings') && call[1]?.method === 'PUT',
    )
    expect(putCall).toBeTruthy()
    expect(String(putCall?.[1]?.body)).toContain('"active_model_id":"m-2"')
    await waitFor(() => expect(modelTrigger().textContent).toBe('gpt-x'))
  })

  it('hover 参数面板改档位经整表 PUT 提交，且不回传密钥明文（MUST-19）', async () => {
    const withProviders = {
      ...settingsFixture,
      providers: [
        {
          id: 'deepseek',
          label: 'DeepSeek',
          base_url: 'https://api.deepseek.com',
          needs_key: true,
          default_api_mode: 'chat_completions',
          supported_api_modes: ['chat_completions'],
          max_context_length: 1_048_576,
          context_window_tiers: [307_200, 614_400, 1_048_576],
          models: [
            {
              model_id: 'deepseek-flash',
              label: 'Flash',
              max_context_length: 1_048_576,
              context_window_tiers: [307_200, 614_400, 1_048_576],
              reasoning_efforts: ['low', 'high', 'max'],
              default_effort: 'high',
            },
          ],
          supports_reasoning: true,
          quirks: '',
        },
      ],
    }
    const fetchMock = stubFetchByUrl({ browse: envelope(null) })
    fetchMock.mockImplementation(async () => ({
      status: 200,
      headers: { get: () => null },
      json: async () => envelope(withProviders),
    }))
    useSettingsStore.setState({ settings: withProviders })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    fireEvent.click(modelTrigger())
    fireEvent.mouseEnter(screen.getByRole('button', { name: /deepseek-flash/ }).parentElement!)
    fireEvent.click(await screen.findByRole('button', { name: '300K' }))

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(
        (call) => String(call[0]).includes('/settings') && call[1]?.method === 'PUT',
      )
      expect(putCall).toBeTruthy()
      const body = String(putCall?.[1]?.body)
      expect(body).toContain('"max_context_length":307200')
      // 凭据在 providers 段，条目只带 provider_id 引用（MUST-19）
      expect(body).toContain('"provider_id":"p-deepseek"')
      // 整表替换语义：另一条目必须一起提交，否则会被后端视为删除
      expect(body).toContain('"model_id":"gpt-x"')
      expect(body).not.toContain('"api_key"')
    })
  })

  it('注册表为空时下拉展示「未配置模型」且禁用', () => {
    useSettingsStore.setState({ settings: { ...settingsFixture, models: [] } })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    expect(modelTrigger().disabled).toBe(true)
    expect(modelTrigger().textContent).toBe('未配置模型')
  })

  it('提交中发送按钮禁用', () => {
    render(<ConsoleInput isSubmitting onSubmit={vi.fn()} />)

    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('ConsoleInput 原生文件夹选择器（2026-10-19 扩展桥）', () => {
  it('点击后经扩展桥取回路径，basename 入库并触发 scan 复校验', async () => {
    const fetchMock = stubFetchByUrl({ browse: envelope(null) })
    fetchMock.mockImplementation(async () => ({
      status: 200,
      headers: { get: () => null },
      json: async () => envelope({ total_symbols: 7, total_files: 3, kind_counts: {} }),
    }))
    vi.mocked(pickFolderViaNative).mockResolvedValueOnce({ path: 'D:/ws/my-repo' })
    useSettingsStore.setState({ settings: settingsFixture })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    await userEvent.setup().click(screen.getByRole('button', { name: '选择文件夹（本地）' }))

    await waitFor(() => expect(screen.getByText('my-repo')).toBeTruthy())
    expect(pickFolderViaNative).toHaveBeenCalledTimes(1)
    // 选中后立即复校验项目路径
    await waitFor(() =>
      expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/project/scan'))).toBe(
        true,
      ),
    )
  })

  it('用户取消：保持原状、不报错、发送仍禁用', async () => {
    vi.mocked(pickFolderViaNative).mockResolvedValueOnce({ path: '' })
    useSettingsStore.setState({ settings: settingsFixture })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    await userEvent.setup().click(screen.getByRole('button', { name: '选择文件夹（本地）' }))

    await waitFor(() => expect(pickFolderViaNative).toHaveBeenCalled())
    expect(screen.queryByText('my-repo')).toBeNull()
    expect(screen.queryByRole('button', { name: '发送' })).toBeTruthy()
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('未装扩展：给出可执行指引（不静默无反应）', async () => {
    vi.mocked(pickFolderViaNative).mockRejectedValueOnce(new Error('native host not found'))
    useSettingsStore.setState({ settings: settingsFixture })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    await userEvent.setup().click(screen.getByRole('button', { name: '选择文件夹（本地）' }))

    expect(await screen.findByText('native host not found')).toBeTruthy()
  })

  it('扩展未注入本页：立即提示且不发起请求（不空转到超时）', async () => {
    vi.mocked(isNativeBridgeReady).mockReturnValueOnce(false)
    useSettingsStore.setState({ settings: settingsFixture })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    await userEvent.setup().click(screen.getByRole('button', { name: '选择文件夹（本地）' }))

    expect(await screen.findByText('未检测到扩展，请刷新页面')).toBeTruthy()
    expect(pickFolderViaNative).not.toHaveBeenCalled()
    // 按钮立即恢复可点（未进入「正在打开」悬挂态）
    expect(screen.getByRole('button', { name: '选择文件夹（本地）' })).toBeTruthy()
  })
})
