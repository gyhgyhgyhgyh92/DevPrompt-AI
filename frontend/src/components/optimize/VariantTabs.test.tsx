import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { VariantPayload } from '../../api/types'
import { VariantTabs } from './VariantTabs'

const variants: VariantPayload[] = [
  { title: '保守方案', body: 'b1', level: 'A', changes: [] },
  { title: '标准方案', body: 'b2', level: 'B', changes: ['x'] },
  { title: '激进方案', body: 'b3', level: 'C', changes: [] },
]

afterEach(cleanup)

describe('VariantTabs 方案对比', () => {
  it('A/B/C 三卡并列渲染', () => {
    render(<VariantTabs variants={variants} ranking={null} />)

    expect(screen.getByRole('article', { name: '方案 A' })).toBeTruthy()
    expect(screen.getByRole('article', { name: '方案 B' })).toBeTruthy()
    expect(screen.getByRole('article', { name: '方案 C' })).toBeTruthy()
  })

  it('空列表渲染空态（不静默）', () => {
    render(<VariantTabs variants={[]} ranking={null} />)

    expect(screen.getByText('暂无方案')).toBeTruthy()
  })

  it('按档位注入操作条', () => {
    render(
      <VariantTabs
        variants={variants}
        ranking={null}
        renderActions={(variant) => <button>采纳 {variant.level}</button>}
      />,
    )

    expect(screen.getByRole('button', { name: '采纳 A' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '采纳 B' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '采纳 C' })).toBeTruthy()
  })
})
