import { useTranslation } from 'react-i18next'
import type { RankingViewPayload } from '../../api/types'
import styles from './optimize.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

interface ConfidenceNoticeProps {
  /** 推荐视图（契约 ranking）；null 表示后端未产生推荐视图。 */
  ranking: RankingViewPayload | null
  /** 未产生推荐的原因（2026-11-06）：single-variant 属正常，score-failed 可重试。 */
  skipReason?: string | null
}

/** 原因枚举 → 语言包键（后端只给字符串枚举，前端不推断原因，MUST-08）。 */
const SKIP_KEYS: Readonly<Record<string, string>> = {
  'single-variant': 'ranking.skip_single_variant',
  'score-failed': 'ranking.skip_score_failed',
}

/**
 * 置信度说明（F-703）：未标记推荐时展示后端 reason 文案，不静默不裁剪（MUST-27）。
 * 已标记时本区不渲染（由 RecommendBadge 承接）；文案全部来自后端字段，前端零解释（MUST-08）。
 */
export function ConfidenceNotice({ ranking, skipReason = null }: ConfidenceNoticeProps) {
  const { t } = useTranslation()
  if (ranking === null) {
    const key = skipReason !== null ? SKIP_KEYS[skipReason] : undefined
    return <p className={s('confidence-notice')}>{t(key ?? 'ranking.skip_unknown')}</p>
  }
  if (ranking.marked) {
    return null
  }
  return <p className={s('confidence-notice')}>{ranking.reason}</p>
}
