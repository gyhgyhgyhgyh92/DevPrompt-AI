import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { RankingViewPayload } from '../../api/types'
import { ScoreDetail } from './ScoreDetail'

const ranking: RankingViewPayload = {
  variant: 'B',
  gap: 0.25,
  confidence: 0.9,
  marked: true,
  reason: '分差明显',
  fit: 0.8,
  total: 0.75,
}

afterEach(cleanup)

describe('ScoreDetail 评分明细', () => {
  it('展开后显示 fit/total 两个后端数值', async () => {
    const user = userEvent.setup()
    render(<ScoreDetail ranking={ranking} />)

    await user.click(screen.getByText('评分明细'))

    expect(screen.getByText('适配度 0.8')).toBeTruthy()
    expect(screen.getByText('总分 0.75')).toBeTruthy()
  })

  it('展示总分口径说明（静态文案，前端零计算）', async () => {
    const user = userEvent.setup()
    render(<ScoreDetail ranking={ranking} />)

    await user.click(screen.getByText('评分明细'))

    expect(screen.getByText(/总分 = 适配度/)).toBeTruthy()
  })
})
