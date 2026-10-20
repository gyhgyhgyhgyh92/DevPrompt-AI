import type { RankingViewPayload } from '../../api/types'
import './optimize.css'

interface ScoreDetailProps {
  /** 推荐视图（契约 ranking）：fit/total 数值取自后端字段，前端零计算（MUST-08）。 */
  ranking: RankingViewPayload
}

/** 评分明细（2026-10-21：偏好记忆移除后总分 = 适配度）。 */
export function ScoreDetail({ ranking }: ScoreDetailProps) {
  return (
    <details className="score-detail">
      <summary className="score-detail__summary">评分明细</summary>
      <ul className="score-detail__list">
        <li>适配度 {ranking.fit}</li>
        <li>总分 {ranking.total}</li>
      </ul>
      <p className="score-detail__note">总分 = 适配度（偏好记忆已移除）</p>
    </details>
  )
}
