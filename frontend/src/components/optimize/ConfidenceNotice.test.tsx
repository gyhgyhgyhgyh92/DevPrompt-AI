import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { RankingViewPayload } from '../../api/types'
import { ConfidenceNotice } from './ConfidenceNotice'

const ranking: RankingViewPayload = {
  variant: 'B',
  gap: 0.25,
  confidence: 0.7,
  marked: false,
  reason: '三套适配度接近，建议人工选择',
  fit: 0.8,
  total: 0.75,
}

afterEach(cleanup)

describe('ConfidenceNotice 置信度说明', () => {
  it('未标记推荐时展示后端 reason 文案（不静默不裁剪）', () => {
    render(<ConfidenceNotice ranking={ranking} />)

    expect(screen.getByText('三套适配度接近，建议人工选择')).toBeTruthy()
  })

  it('ranking 为 null 时展示未产生推荐的说明', () => {
    render(<ConfidenceNotice ranking={null} />)

    expect(screen.getByText('后端未产生推荐视图，请人工选择')).toBeTruthy()
  })

  it('单套跳过打分时说明是正常行为（2026-11-06）', () => {
    render(<ConfidenceNotice ranking={null} skipReason="single-variant" />)
    expect(screen.getByText(/只产出 1 套方案/)).toBeTruthy()
  })

  it('打分失败时提示可重试', () => {
    render(<ConfidenceNotice ranking={null} skipReason="score-failed" />)
    expect(screen.getByText(/打分服务本轮不可用/)).toBeTruthy()
  })

  it('已标记推荐时不渲染（由 RecommendBadge 承接）', () => {
    render(<ConfidenceNotice ranking={{ ...ranking, marked: true }} />)

    expect(screen.queryByText('三套适配度接近，建议人工选择')).toBeNull()
  })
})
