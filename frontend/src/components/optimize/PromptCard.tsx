import type { ReactNode } from 'react'
import type { RankingViewPayload, VariantPayload } from '../../api/types'
import { CopyButton } from './CopyButton'
import './optimize.css'
import { RecommendBadge } from './RecommendBadge'
import { ScoreDetail } from './ScoreDetail'

interface PromptCardProps {
  /** 单套方案（契约 VariantPayload）：body 为后端生成原文，前端零加工（MUST-08）。 */
  variant: VariantPayload
  /** 推荐视图（契约 ranking）；null 表示后端未产生推荐。 */
  ranking: RankingViewPayload | null
  /** 卡内操作条（反馈按钮组等由页面编排注入，组合优于配置）。 */
  actions?: ReactNode
}

/**
 * 单套方案展示（F-703）：推荐卡品牌边框高亮、可展开评分明细。
 * 推荐态判定仅用后端字段真值与档位相等匹配（渲染门，不做任何数值比较/分差计算，MUST-08）。
 */
export function PromptCard({ variant, ranking, actions }: PromptCardProps) {
  const isRankingVariant = ranking !== null && ranking.variant === variant.level
  const isRecommended = ranking !== null && ranking.marked && isRankingVariant

  return (
    <article
      className={isRecommended ? 'prompt-card prompt-card--recommended' : 'prompt-card'}
      aria-label={`方案 ${variant.level}`}
    >
      <header className="prompt-card__header">
        <h3>{variant.title}</h3>
        <span className="prompt-card__level">{variant.level}</span>
        <RecommendBadge ranking={isRankingVariant ? ranking : null} />
      </header>
      <pre className="prompt-card__body">
        <code>{variant.body}</code>
      </pre>
      {(variant.changes ?? []).length > 0 ? (
        <ul className="prompt-card__changes">
          {(variant.changes ?? []).map((change) => (
            <li key={change}>{change}</li>
          ))}
        </ul>
      ) : null}
      {isRankingVariant && ranking !== null ? <ScoreDetail ranking={ranking} /> : null}
      <footer className="prompt-card__footer">
        <CopyButton text={variant.body} />
        {actions}
      </footer>
    </article>
  )
}
