import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProviderDirectoryEntry } from '../../schemas/settings'
import { ApiModeSelect } from './ApiModeSelect'
import { findProvider, formatWindow, ProviderSelect } from './ProviderSelect'

/**
 * 多供应商扩展 W8 组件测试。
 *
 * 关注三条诚实性约束（承接前几轮「不支持就说不支持」的同一口径）：
 * 1. provider 下拉**由后端目录驱动**，前端不内置厂商清单；
 * 2. api_mode 可选值来自目录 `supported_api_modes`，不硬编码；
 * 3. 端点未登记（base_url 为空）时必须提示用户自填，不静默留白。
 */

const PROVIDERS: ProviderDirectoryEntry[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    base_url: 'https://api.deepseek.com',
    needs_key: true,
    default_api_mode: 'chat_completions',
    supported_api_modes: ['chat_completions'],
    max_context_length: 64000,
    context_window_tiers: [64000],
    models: [],
    supports_reasoning: false,
    quirks: '',
  },
  {
    id: 'openai_compatible',
    label: 'OpenAI 兼容',
    base_url: 'https://api.openai.com/v1',
    needs_key: true,
    default_api_mode: 'chat_completions',
    supported_api_modes: ['chat_completions', 'responses'],
    max_context_length: 128000,
    context_window_tiers: [128000],
    models: [],
    supports_reasoning: true,
    quirks: '',
  },
  {
    id: 'yi',
    label: '零一万物',
    base_url: '',
    needs_key: true,
    default_api_mode: 'chat_completions',
    supported_api_modes: ['chat_completions'],
    context_window_tiers: [],
    models: [],
    supports_reasoning: false,
    quirks: '',
  },
]

afterEach(cleanup)

describe('ProviderSelect', () => {
  it('选项来自后端目录而非硬编码', () => {
    render(<ProviderSelect providers={PROVIDERS} value="" onChange={() => {}} />)
    const options = screen.getAllByRole('option').map((o) => o.textContent)
    expect(options).toContain('DeepSeek')
    expect(options.some((t) => t?.startsWith('零一万物'))).toBe(true)
  })

  it('端点未登记的 provider 有明确标识', () => {
    render(<ProviderSelect providers={PROVIDERS} value="" onChange={() => {}} />)
    const options = screen.getAllByRole('option').map((o) => o.textContent)
    expect(options.some((t) => t?.includes('端点未登记'))).toBe(true)
    // 有端点的不带该标识
    expect(options.find((t) => t === 'DeepSeek')).toBe('DeepSeek')
  })

  it('触发 onChange 带目录 id', () => {
    const onChange = vi.fn()
    render(<ProviderSelect providers={PROVIDERS} value="" onChange={onChange} />)
    fireEvent.change(screen.getByLabelText('供应商'), { target: { value: 'openai_compatible' } })
    expect(onChange).toHaveBeenCalledWith('openai_compatible')
  })

  it('目录缺失时只剩占位项，不崩', () => {
    render(<ProviderSelect providers={undefined} value="" onChange={() => {}} />)
    expect(screen.getAllByRole('option')).toHaveLength(1)
  })
})

describe('findProvider', () => {
  it('精确匹配', () => {
    expect(findProvider(PROVIDERS, 'deepseek')?.label).toBe('DeepSeek')
  })

  it('大小写与空格归一化', () => {
    expect(findProvider(PROVIDERS, 'DeepSeek')?.id).toBe('deepseek')
    expect(findProvider(PROVIDERS, ' openai_compatible ')?.id).toBe('openai_compatible')
  })

  it('未知返回 undefined 而不是猜测', () => {
    expect(findProvider(PROVIDERS, 'no-such-provider')).toBeUndefined()
  })

  it('空目录返回 undefined', () => {
    expect(findProvider([], 'deepseek')).toBeUndefined()
    expect(findProvider(undefined, 'deepseek')).toBeUndefined()
  })
})

describe('formatWindow', () => {
  it('千/百万单位', () => {
    expect(formatWindow(64000)).toBe('64K')
    expect(formatWindow(1_000_000)).toBe('1M')
    expect(formatWindow(999)).toBe('999')
  })

  it('未知返回 null', () => {
    expect(formatWindow(null)).toBeNull()
    expect(formatWindow(0)).toBeNull()
  })
})

describe('ApiModeSelect（2026-10-18 起不含思考强度/上下文窗口，二者已迁至启动页模型下拉）', () => {
  const base = {
    defaultMode: 'chat_completions',
    onModeChange: vi.fn(),
  }

  it('可选模式来自后端目录 supported_api_modes', () => {
    render(<ApiModeSelect {...base} supported={['chat_completions', 'responses']} value="" />)
    const options = screen.getAllByRole('option').map((o) => o.textContent)
    expect(options).toContain('responses')
  })

  it('只有一种形态时不渲染下拉（不渲染冗余的「默认」+同值两项）', () => {
    render(<ApiModeSelect {...base} supported={['chat_completions']} value="" />)
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.getByText(/chat_completions（该供应商仅支持这一种形态）/)).toBeTruthy()
  })

  it('目录为空时回落到默认形态，不显示空下拉', () => {
    render(<ApiModeSelect {...base} supported={[]} value="" />)
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.getByText(/chat_completions/)).toBeTruthy()
  })

  it('不再渲染思考强度与上下文窗口（已迁至启动页）', () => {
    render(<ApiModeSelect {...base} supported={['chat_completions']} value="" />)
    expect(screen.queryByLabelText('思考强度')).toBeNull()
    expect(screen.queryByLabelText('上下文窗口')).toBeNull()
  })

  it('切换形态触发 onModeChange', () => {
    const onModeChange = vi.fn()
    render(
      <ApiModeSelect
        {...base}
        onModeChange={onModeChange}
        supported={['chat_completions', 'responses']}
        value=""
      />,
    )
    fireEvent.change(screen.getByLabelText('API 形态'), { target: { value: 'responses' } })
    expect(onModeChange).toHaveBeenCalledWith('responses')
  })
})
