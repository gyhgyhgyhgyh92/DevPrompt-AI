import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { RankingViewPayload } from '../../api/types'
import { RecommendBadge } from './RecommendBadge'

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

describe('RecommendBadge 推荐徽章', () => {
  it('marked 为真时渲染【推荐】与置信度数值', () => {
    render(<RecommendBadge ranking={ranking} />)

    expect(screen.getByText(/【推荐】B/)).toBeTruthy()
    expect(screen.getByText(/0.9/)).toBeTruthy()
  })

  it('marked 为假时不渲染（由 ConfidenceNotice 承接说明）', () => {
    render(<RecommendBadge ranking={{ ...ranking, marked: false }} />)

    expect(screen.queryByText(/【推荐】/)).toBeNull()
  })

  it('ranking 为 null 时不渲染', () => {
    render(<RecommendBadge ranking={null} />)

    expect(screen.queryByText(/【推荐】/)).toBeNull()
  })
})
