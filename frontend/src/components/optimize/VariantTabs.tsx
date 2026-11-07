import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { RankingViewPayload, VariantPayload } from '../../api/types'
import styles from './optimize.module.css'
import { makeS } from '../../utils/css'
import { PromptCard } from './PromptCard'

const s = makeS(styles)

interface VariantTabsProps {
  /** 三套方案（契约 variants）：A/B/C 并列对比，顺序与内容全按后端下发。 */
  variants: readonly VariantPayload[]
  /** 推荐视图（契约 ranking）；透传给各卡渲染推荐态与评分明细。 */
  ranking: RankingViewPayload | null
  /** 每卡操作条（反馈按钮组），由页面按档位注入。 */
  renderActions?: (variant: VariantPayload) => ReactNode
}

/** 方案对比区（F-703）：A/B/C 并列三卡；空列表渲染空态（不静默）。 */
export function VariantTabs({ variants, ranking, renderActions }: VariantTabsProps) {
  const { t } = useTranslation()
  if (variants.length === 0) {
    return <p className={s('context-panel__empty')}>{t('optimize.no_variants')}</p>
  }
  return (
    <div className={s('variant-tabs')} role="list" aria-label={t('optimize.variant_compare')}>
      {variants.map((variant) => (
        <div role="listitem" key={variant.level}>
          <PromptCard variant={variant} ranking={ranking} actions={renderActions?.(variant)} />
        </div>
      ))}
    </div>
  )
}
