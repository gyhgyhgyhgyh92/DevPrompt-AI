import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SettingsResponse } from '../../api/types'
import { ModelPicker } from './ModelPicker'

type Entry = SettingsResponse['models'][number]
type Provider = NonNullable<SettingsResponse['providers']>[number]

function entry(over: Partial<Entry> & { id: string; model_id: string }): Entry {
  return { provider_id: 'p-deepseek', provider: 'deepseek', is_active: false, ...over }
}

/** DeepSeek 官方登记（api-docs.deepseek.com/guides/thinking_mode）：none/low/high/max，默认 high */
const DEEPSEEK: Provider = {
  id: 'deepseek',
  label: 'DeepSeek',
  base_url: 'https://api.deepseek.com',
  needs_key: true,
  default_api_mode: 'chat_completions',
  supported_api_modes: ['chat_completions'],
  max_context_length: 1_048_576,
  context_window_tiers: [131_072, 307_200, 614_400, 1_048_576],
  models: [
    {
      model_id: 'deepseek-flash',
      label: 'DeepSeek-V4.1-Flash',
      max_context_length: 1_048_576,
      context_window_tiers: [131_072, 307_200, 614_400, 1_048_576],
      reasoning_efforts: ['none', 'low', 'high', 'max'],
      default_effort: 'high',
    },
  ],
  supports_reasoning: true,
  quirks: '',
}

/** Kimi 走另一厂商：K2.7 为 256K（262,144），档位与强度都与 DeepSeek 不同（各模型独立、不可共用） */
const MOONSHOT: Provider = {
  id: 'moonshot',
  label: 'Moonshot',
  base_url: 'https://api.moonshot.cn',
  needs_key: true,
  default_api_mode: 'chat_completions',
  supported_api_modes: ['chat_completions'],
  max_context_length: 262_144,
  context_window_tiers: [131_072, 262_144],
  models: [
    {
      model_id: 'kimi-k2.7-code',
      label: 'Kimi K2.7 Code',
      max_context_length: 262_144,
      context_window_tiers: [131_072, 262_144],
      reasoning_efforts: ['Low', 'High', 'X-High'],
      default_effort: 'High',
    },
  ],
  supports_reasoning: true,
  quirks: '',
}

const FLASH = entry({ id: 'm-1', model_id: 'deepseek-flash', is_active: true })
const KIMI = entry({ id: 'm-2', model_id: 'kimi-k2.7-code', provider: 'moonshot' })

function renderPicker(over: Partial<Parameters<typeof ModelPicker>[0]> = {}) {
  const props = {
    entries: [FLASH],
    providers: [DEEPSEEK, MOONSHOT],
    activeId: 'm-1',
    onSelect: vi.fn(),
    onTune: vi.fn(),
    ...over,
  }
  render(<ModelPicker {...props} />)
  return props
}

async function openAndHover(modelId: string) {
  fireEvent.click(screen.getByRole('button', { name: '选择模型' }))
  await waitFor(() =>
    expect(screen.getByRole('button', { name: new RegExp(modelId) })).toBeTruthy(),
  )
  hover(modelId)
}

/** 只 hover（菜单已展开时用——再点触发器会把它收起来）。 */
function hover(modelId: string) {
  fireEvent.mouseEnter(
    screen.getByRole('button', { name: new RegExp(modelId) }).parentElement as HTMLElement,
  )
}

function leave(modelId: string) {
  fireEvent.mouseLeave(
    screen.getByRole('button', { name: new RegExp(modelId) }).parentElement as HTMLElement,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ModelPicker 只列已配置模型', () => {
  it('收起时只显示当前生效模型', () => {
    renderPicker()
    expect(screen.getByRole('button', { name: '选择模型' }).textContent).toBe('deepseek-flash')
  })

  it('展开后只列已配置条目，不列厂商目录里未配置的模型', async () => {
    renderPicker({ entries: [FLASH, KIMI] })
    fireEvent.click(screen.getByRole('button', { name: '选择模型' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /kimi-k2.7-code/ })).toBeTruthy())

    expect(
      screen.getAllByRole('button', { name: /^(deepseek-flash|kimi-k2.7-code)/ }),
    ).toHaveLength(2)
    expect(screen.queryByText('未配置')).toBeNull()
  })

  it('选择条目经 onSelect 上抛', async () => {
    const onSelect = vi.fn()
    renderPicker({ entries: [FLASH, KIMI], onSelect })
    fireEvent.click(screen.getByRole('button', { name: '选择模型' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /kimi-k2.7-code/ })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: /kimi-k2.7-code/ }))
    expect(onSelect).toHaveBeenCalledWith('m-2')
  })

  it('未配置任何模型时触发器禁用并显示占位', () => {
    renderPicker({ entries: [], activeId: '' })
    const trigger = screen.getByRole('button', { name: '选择模型' })
    expect((trigger as HTMLButtonElement).disabled).toBe(true)
    expect(trigger.textContent).toBe('未配置模型')
  })

  it('Esc 收起下拉', async () => {
    renderPicker()
    fireEvent.click(screen.getByRole('button', { name: '选择模型' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /deepseek-flash/ })).toBeTruthy())
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('button', { name: /deepseek-flash/ })).toBeNull()
  })
})

describe('ModelPicker hover 参数面板', () => {
  it('hover 才弹面板，移开即隐藏', async () => {
    renderPicker()
    expect(screen.queryByText('上下文长度')).toBeNull()
    await openAndHover('deepseek-flash')
    expect(screen.getByText('上下文长度')).toBeTruthy()
    leave('deepseek-flash')
    expect(screen.queryByText('上下文长度')).toBeNull()
  })

  it('面板是模型项的 DOM 子节点（指针能移进面板而不消失）', async () => {
    renderPicker()
    await openAndHover('deepseek-flash')
    const panel = document.querySelector('[class*="model-picker__panel"]') as HTMLElement
    const item = screen.getByRole('button', { name: /deepseek-flash/ }).parentElement as HTMLElement
    expect(item.contains(panel)).toBe(true)
  })

  it('档位与强度按模型独立：DeepSeek 多档 low/high/max，Kimi 两档 Low/High/X-High', async () => {
    renderPicker({ entries: [FLASH, KIMI] })
    await openAndHover('deepseek-flash')
    expect(
      screen.getAllByRole('button', { name: /^(128K|300K|600K|1M)/ }).map((b) => b.textContent),
    ).toEqual(['128K', '300K', '600K', '1M✓'])
    expect(screen.getByRole('button', { name: 'low' })).toBeTruthy()
    // none 是关闭语义，不作为强度按钮展示
    expect(screen.queryByRole('button', { name: 'none' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'X-High' })).toBeNull()

    leave('deepseek-flash')
    hover('kimi-k2.7-code')
    expect(
      screen.getAllByRole('button', { name: /^(128K|256K)/ }).map((b) => b.textContent),
    ).toEqual(['128K', '256K✓'])
    expect(screen.getByRole('button', { name: 'X-High' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'low' })).toBeNull()
  })

  it('选档位经 onTune 上抛，且不冒泡成「切换模型」', async () => {
    const onSelect = vi.fn()
    const onTune = vi.fn()
    renderPicker({ onSelect, onTune })
    await openAndHover('deepseek-flash')

    fireEvent.click(screen.getByRole('button', { name: '300K' }))
    expect(onTune).toHaveBeenCalledWith('m-1', { max_context_length: 307_200 })
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('联动：思考模式关闭时强度全部置灰；开启后取官方默认档 high', async () => {
    const onTune = vi.fn()
    renderPicker({ onTune })
    await openAndHover('deepseek-flash')

    const modeSwitch = screen.getByRole('switch', { name: '思考模式' })
    expect(modeSwitch.getAttribute('aria-checked')).toBe('false')
    for (const level of ['low', 'high', 'max']) {
      expect((screen.getByRole('button', { name: level }) as HTMLButtonElement).disabled).toBe(true)
    }

    fireEvent.click(modeSwitch)
    // DeepSeek 官方文档注明默认 effort 为 high（不是列表第一档 low）
    expect(onTune).toHaveBeenCalledWith('m-1', { reasoning_effort: 'high' })
  })

  it('已开启时强度可选中；关闭则不下发 reasoning（空串）', async () => {
    const onTune = vi.fn()
    renderPicker({ entries: [{ ...FLASH, reasoning_effort: 'high' }], onTune })
    await openAndHover('deepseek-flash')

    expect(screen.getByRole('switch', { name: '思考模式' }).getAttribute('aria-checked')).toBe(
      'true',
    )
    const high = screen.getByRole('button', { name: 'high' }) as HTMLButtonElement
    expect(high.disabled).toBe(false)
    expect(high.getAttribute('aria-pressed')).toBe('true')

    fireEvent.click(screen.getByRole('switch', { name: '思考模式' }))
    expect(onTune).toHaveBeenCalledWith('m-1', { reasoning_effort: '' })
  })

  it('厂商未登记档位与强度时整块不渲染（不编占位值）', async () => {
    renderPicker({
      entries: [entry({ id: 'm-9', model_id: 'mystery', provider: 'not-a-vendor' })],
      activeId: 'm-9',
      providers: [],
    })
    await openAndHover('mystery')
    expect(screen.queryByText('上下文长度')).toBeNull()
    expect(screen.queryByText('思考强度')).toBeNull()
  })
})
