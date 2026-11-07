import { useTranslation } from 'react-i18next'
import type { RankingViewPayload } from '../../api/types'
import styles from './optimize.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

interface ScoreDetailProps {
  /** 推荐视图（契约 ranking）：fit/total 数值取自后端字段，前端零计算（MUST-08）。 */
  ranking: RankingViewPayload
}

/** 评分明细（2026-10-21：偏好记忆移除后总分 = 适配度）。 */
export function ScoreDetail({ ranking }: ScoreDetailProps) {
  const { t } = useTranslation()
  return (
    <details className={s('score-detail')}>
      <summary className={s('score-detail__summary')}>{t('score.detail')}</summary>
      <ul className={s('score-detail__list')}>
        <li>{t('score.fit', { value: ranking.fit })}</li>
        <li>{t('score.total', { value: ranking.total })}</li>
      </ul>
      <p className={s('score-detail__note')}>{t('score.note')}</p>
    </details>
  )
}
