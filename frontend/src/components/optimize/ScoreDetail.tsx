import type { RankingViewPayload } from '../../api/types'
import './optimize.css'

interface ScoreDetailProps {
  /** 推荐视图（契约 ranking）：fit/pref/total 数值全部取自后端字段，前端零计算（MUST-08）。 */
  ranking: RankingViewPayload
}

/** 评分明细：折叠展开三个信号分项与总分口径说明（说明为静态文案，不含任何数值判定）。 */
export function ScoreDetail({ ranking }: ScoreDetailProps) {
  return (
    <details className="score-detail">
      <summary className="score-detail__summary">评分明细</summary>
      <ul className="score-detail__list">
        <li>适配度 {ranking.fit}</li>
        <li>偏好匹配 {ranking.pref}</li>
        <li>总分 {ranking.total}</li>
      </ul>
      <p className="score-detail__note">总分 = 适配度加权 + 偏好匹配加权（权重由后端裁定）</p>
    </details>
  )
}
