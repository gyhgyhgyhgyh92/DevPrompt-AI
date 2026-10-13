import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse, SettingsResponse } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { ConsoleInput } from './ConsoleInput'

const PROMPT_HINT = '帮你优化每一段提示词，从理清需求到上线-端到端交付生产级结果'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

const MODEL_ENTRIES: SettingsResponse['models'] = [
  {
    id: 'm-1',
    label: 'DeepSeek · deepseek-flash',
    provider: 'DeepSeek',
    base_url: 'https://api.deepseek.com',
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
]

const settingsFixture: SettingsResponse = {
  models: MODEL_ENTRIES,
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.deepseek.com',
    decider: 'auto',
    model_id: 'deepseek-flash',
    provider: 'DeepSeek',
    temperature: null,
    max_tokens: null,
    timeout: 60,
  },
  process: { followup_cost_budget: 1, followup_soft_round_guard: 10, telemetry: true },
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

/** browse 载荷快捷构造：默认落在目标项目目录（path='D:/ws/repo'）。 */
function browsePayload(path: string, parent: string | null = null) {
  return envelope({ path, parent, entries: [], truncated: false })
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

    expect(document.querySelector('.console-input')).not.toBeNull()
    expect(document.querySelector('.console-input__card')).not.toBeNull()
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

  it('不再存在「项目路径」手动输入文本框（移除手输，仅页内浏览器）', () => {
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    expect(screen.queryByRole('textbox', { name: '项目路径' })).toBeNull()
    expect(document.querySelector('.console-input__path-input')).toBeNull()
  })

  it('无输入时发送按钮禁用（防重复/防误触，MUST-15）', () => {
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('点击「选择文件夹（本地）」打开页内浏览器，选择后显示 basename 并透传路径', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    const fetchMock = stubFetchByUrl({ browse: browsePayload('D:/ws/repo', 'D:/ws') })
    render(<ConsoleInput isSubmitting={false} onSubmit={onSubmit} />)

    await user.type(screen.getByRole('textbox', { name: '优化原句' }), '加个导出按钮')
    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))

    // 页内模态（DOM 内渲染，非系统桌面窗口）
    expect(await screen.findByRole('dialog', { name: '选择项目文件夹（本地）' })).toBeTruthy()
    await user.click(await screen.findByRole('button', { name: '选择当前文件夹' }))

    expect(await screen.findByText('repo')).toBeTruthy()
    expect(screen.queryByRole('dialog', { name: '选择项目文件夹（本地）' })).toBeNull()
    const browseCall = fetchMock.mock.calls.find((call) =>
      String(call[0]).includes('/project/browse'),
    )
    expect(browseCall).toBeTruthy()
    // 选择后沿用 scan 复校验（失败提示路径依赖，不再有手输）
    const scanCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/project/scan'))
    expect(scanCall).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '发送' }))
    expect(onSubmit).toHaveBeenCalledWith('加个导出按钮', 'D:/ws/repo')
  })

  it('取消关闭页内浏览器保持原状且不报错，发送仍禁用', async () => {
    const user = userEvent.setup()
    stubFetchByUrl({ browse: browsePayload('D:/ws/repo') })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))
    expect(await screen.findByRole('dialog', { name: '选择项目文件夹（本地）' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '取消' }))

    expect(screen.queryByRole('dialog', { name: '选择项目文件夹（本地）' })).toBeNull()
    expect(screen.getByRole('button', { name: '选择文件夹（本地）' }).textContent).toContain(
      '选择文件夹（本地）',
    )
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('浏览器加载失败（业务错误）在模态内显示错误，可取消后保持原状', async () => {
    const user = userEvent.setup()
    stubFetchByUrl({
      browse: { code: 2001, message: '目录不存在或不可访问', request_id: 'r', data: null },
    })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))

    expect(await screen.findByText('无法读取该文件夹，请重试')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.queryByText('无法读取该文件夹，请重试')).toBeNull()
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('模型下拉默认展示当前生效模型完整名称，选项为全部注册表条目', () => {
    useSettingsStore.setState({ settings: settingsFixture })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    const select = screen.getByRole('combobox', { name: '选择模型' }) as HTMLSelectElement
    expect(select.value).toBe('m-1')
    const options = Array.from(select.options).map((o) => o.textContent)
    expect(options).toEqual(['DeepSeek · deepseek-flash', 'OpenAI 兼容 · gpt-x'])
    expect(select.selectedOptions[0]?.textContent).toBe('DeepSeek · deepseek-flash')
  })

  it('切换模型经 PUT /settings 提交 active_model_id 并更新展示', async () => {
    const user = userEvent.setup()
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

    await user.selectOptions(screen.getByRole('combobox', { name: '选择模型' }), 'm-2')

    const putCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/settings'))
    expect(putCall).toBeTruthy()
    expect(putCall?.[1]?.method).toBe('PUT')
    expect(String(putCall?.[1]?.body)).toContain('"active_model_id":"m-2"')
    await waitFor(() =>
      expect((screen.getByRole('combobox', { name: '选择模型' }) as HTMLSelectElement).value).toBe(
        'm-2',
      ),
    )
  })

  it('注册表为空时下拉展示「未配置模型」且禁用', () => {
    useSettingsStore.setState({ settings: { ...settingsFixture, models: [] } })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    const select = screen.getByRole('combobox', { name: '选择模型' }) as HTMLSelectElement
    expect(select.disabled).toBe(true)
    expect(select.options[0]?.textContent).toBe('未配置模型')
  })

  it('提交中发送按钮禁用', () => {
    render(<ConsoleInput isSubmitting onSubmit={vi.fn()} />)

    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
