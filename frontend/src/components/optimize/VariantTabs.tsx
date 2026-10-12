import type { ReactNode } from 'react'
import type { RankingViewPayload, VariantPayload } from '../../api/types'
import './optimize.css'
import { PromptCard } from './PromptCard'

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
  if (variants.length === 0) {
    return <p className="context-panel__empty">暂无方案</p>
  }
  return (
    <div className="variant-tabs" role="list" aria-label="方案对比">
      {variants.map((variant) => (
        <div role="listitem" key={variant.level}>
          <PromptCard variant={variant} ranking={ranking} actions={renderActions?.(variant)} />
        </div>
      ))}
    </div>
  )
}
