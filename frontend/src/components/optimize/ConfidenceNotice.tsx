import type { RankingViewPayload } from '../../api/types'
import './optimize.css'

interface ConfidenceNoticeProps {
  /** 推荐视图（契约 ranking）；null 表示后端未产生推荐视图。 */
  ranking: RankingViewPayload | null
}

/**
 * 置信度说明（F-703）：未标记推荐时展示后端 reason 文案，不静默不裁剪（MUST-27）。
 * 已标记时本区不渲染（由 RecommendBadge 承接）；文案全部来自后端字段，前端零解释（MUST-08）。
 */
export function ConfidenceNotice({ ranking }: ConfidenceNoticeProps) {
  if (ranking === null) {
    return <p className="confidence-notice">后端未产生推荐视图，请人工选择</p>
  }
  if (ranking.marked) {
    return null
  }
  return <p className="confidence-notice">{ranking.reason}</p>
}
