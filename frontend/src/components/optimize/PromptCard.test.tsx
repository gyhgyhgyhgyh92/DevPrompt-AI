import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { VariantPayload } from '../../api/types'
import { PromptCard } from './PromptCard'

const variant: VariantPayload = {
  title: '标准方案',
  body: 'echo 方案原文',
  changes: ['改动一', '改动二'],
  claims: [],
  fallback: false,
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('PromptCard 单方案展示', () => {
  it('body 等宽原样渲染后端字符串（零加工），changes 列表逐条渲染', () => {
    render(<PromptCard variant={variant} />)

    expect(screen.getByText('echo 方案原文')).toBeTruthy()
    expect(screen.getByText('改动一')).toBeTruthy()
    expect(screen.getByText('改动二')).toBeTruthy()
    expect(screen.getByRole('article', { name: '标准方案' })).toBeTruthy()
  })

  it('fallback 为真时显示降级提示', () => {
    render(<PromptCard variant={{ ...variant, fallback: true }} />)

    expect(screen.getByText(/已降级为保守输出/)).toBeTruthy()
  })

  it('fallback 为假时不显示降级提示', () => {
    render(<PromptCard variant={variant} />)

    expect(screen.queryByText(/已降级为保守输出/)).toBeNull()
  })

  it('渲染操作条 slot（反馈按钮由页面注入）与复制按钮', () => {
    render(<PromptCard variant={variant} actions={<button>采纳</button>} />)

    expect(screen.getByRole('button', { name: '采纳' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '复制' })).toBeTruthy()
  })
})
