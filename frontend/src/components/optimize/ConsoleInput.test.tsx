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

const settingsFixture: SettingsResponse = {
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.deepseek.com',
    decider: 'auto',
    model_id: 'deepseek-chat',
    provider: 'DeepSeek',
    temperature: null,
    max_tokens: null,
    timeout: 60,
  },
  process: { followup_cost_budget: 1, followup_soft_round_guard: 10, telemetry: true },
  locked: { candidate_limit: 25 },
}

/** URL 分流 stub：/project/pick 与 /project/scan 各取自己的 JSON（其余回 null）。 */
function stubFetchByUrl(payloadByPath: { pick: unknown; scan?: unknown }) {
  const mock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    const payload = url.includes('/project/pick')
      ? payloadByPath.pick
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

  it('不再存在「项目路径」手动输入文本框（移除手输，仅原生对话框）', () => {
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    expect(screen.queryByRole('textbox', { name: '项目路径' })).toBeNull()
    expect(document.querySelector('.console-input__path-input')).toBeNull()
  })

  it('无输入时发送按钮禁用（防重复/防误触，MUST-15）', () => {
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('点击「选择文件夹（本地）」经 POST /project/pick 选择并显示 basename，提交透传路径', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    const fetchMock = stubFetchByUrl({ pick: envelope({ path: 'D:/ws/repo' }) })
    render(<ConsoleInput isSubmitting={false} onSubmit={onSubmit} />)

    await user.type(screen.getByRole('textbox', { name: '优化原句' }), '加个导出按钮')
    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))

    expect(await screen.findByText('repo')).toBeTruthy()
    const pickCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/project/pick'))
    expect(pickCall).toBeTruthy()
    expect(pickCall?.[1]?.method).toBe('POST')
    // 选择后沿用 scan 复校验（失败提示路径依赖，不再有手输）
    const scanCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/project/scan'))
    expect(scanCall).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '发送' }))
    expect(onSubmit).toHaveBeenCalledWith('加个导出按钮', 'D:/ws/repo')
  })

  it('取消选择（空串）保持原状且不报错，发送仍禁用', async () => {
    const user = userEvent.setup()
    stubFetchByUrl({ pick: envelope({ path: '' }) })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))

    await waitFor(() =>
      expect(
        (screen.getByRole('button', { name: '选择文件夹（本地）' }) as HTMLButtonElement).disabled,
      ).toBe(false),
    )
    expect(screen.queryByText('无法打开系统文件夹选择器')).toBeNull()
    expect(screen.getByRole('button', { name: '选择文件夹（本地）' }).textContent).toContain(
      '选择文件夹（本地）',
    )
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('选择失败（业务错误）显示「无法打开系统文件夹选择器」', async () => {
    const user = userEvent.setup()
    stubFetchByUrl({
      pick: { code: 2001, message: '所选路径不是有效目录', request_id: 'r', data: null },
    })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '选择文件夹（本地）' }))

    expect(await screen.findByText('无法打开系统文件夹选择器')).toBeTruthy()
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('模型名只读展示当前设置；未配置时显「未配置模型」', () => {
    useSettingsStore.setState({ settings: settingsFixture })
    const { unmount } = render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)
    expect(screen.getByText('deepseek-chat')).toBeTruthy()
    // 只读纯文本：不是按钮/输入，不可交互
    expect(screen.queryByRole('button', { name: 'deepseek-chat' })).toBeNull()
    unmount()

    useSettingsStore.setState({ settings: null })
    render(<ConsoleInput isSubmitting={false} onSubmit={vi.fn()} />)
    expect(screen.getByText('未配置模型')).toBeTruthy()
  })

  it('提交中发送按钮禁用', () => {
    render(<ConsoleInput isSubmitting onSubmit={vi.fn()} />)

    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
