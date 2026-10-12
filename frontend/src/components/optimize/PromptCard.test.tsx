import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RankingViewPayload, VariantPayload } from '../../api/types'
import { PromptCard } from './PromptCard'

const variant: VariantPayload = {
  title: '标准方案',
  body: 'echo 方案原文',
  level: 'B',
  changes: ['改动一', '改动二'],
}

const ranking: RankingViewPayload = {
  variant: 'B',
  gap: 0.25,
  confidence: 0.9,
  marked: true,
  reason: '分差明显',
  fit: 0.8,
  pref: 0.7,
  total: 0.75,
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('PromptCard 单套方案展示', () => {
  it('body 等宽原样渲染后端字符串（零加工），changes 列表逐条渲染', () => {
    render(<PromptCard variant={variant} ranking={null} />)

    expect(screen.getByText('echo 方案原文')).toBeTruthy()
    expect(screen.getByText('改动一')).toBeTruthy()
    expect(screen.getByText('改动二')).toBeTruthy()
    expect(screen.getByText('B')).toBeTruthy()
  })

  it('ranking 命中该档且 marked 时加推荐边框并显示徽章与评分明细', () => {
    render(<PromptCard variant={variant} ranking={ranking} />)

    const card = screen.getByRole('article', { name: '方案 B' })
    expect(card.className).toContain('prompt-card--recommended')
    expect(screen.getByText(/【推荐】B/)).toBeTruthy()
    expect(screen.getByText('评分明细')).toBeTruthy()
  })

  it('marked 为假时不加边框不显徽章（说明由 ConfidenceNotice 承接）', () => {
    render(<PromptCard variant={variant} ranking={{ ...ranking, marked: false }} />)

    const card = screen.getByRole('article', { name: '方案 B' })
    expect(card.className).not.toContain('prompt-card--recommended')
    expect(screen.queryByText(/【推荐】/)).toBeNull()
  })

  it('ranking 指向其他档位时本卡无边框无徽章无评分明细', () => {
    render(<PromptCard variant={{ ...variant, level: 'A', title: '保守方案' }} ranking={ranking} />)

    const card = screen.getByRole('article', { name: '方案 A' })
    expect(card.className).not.toContain('prompt-card--recommended')
    expect(screen.queryByText(/【推荐】/)).toBeNull()
    expect(screen.queryByText('评分明细')).toBeNull()
  })

  it('渲染操作条 slot（反馈按钮由页面注入）', () => {
    render(<PromptCard variant={variant} ranking={null} actions={<button>采纳 B</button>} />)

    expect(screen.getByRole('button', { name: '采纳 B' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '复制' })).toBeTruthy()
  })
})
