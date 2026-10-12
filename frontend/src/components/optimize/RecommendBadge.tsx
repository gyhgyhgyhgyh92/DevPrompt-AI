import type { RankingViewPayload } from '../../api/types'
import './optimize.css'

interface RecommendBadgeProps {
  /** 推荐视图（契约 ranking）；标记与否完全由后端判定，前端只渲染（MUST-08）。 */
  ranking: RankingViewPayload | null
}

/** 推荐徽章：仅后端 marked 为真时渲染；未标记由 ConfidenceNotice 承接说明。 */
export function RecommendBadge({ ranking }: RecommendBadgeProps) {
  if (ranking === null || !ranking.marked) {
    return null
  }
  return (
    <span className="recommend-badge">
      【推荐】{ranking.variant}（置信度 {ranking.confidence}）
    </span>
  )
}
