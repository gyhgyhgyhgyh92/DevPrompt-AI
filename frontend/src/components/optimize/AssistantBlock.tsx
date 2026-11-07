import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { DeliveryGatePayload, RankingViewPayload, VariantPayload } from '../../api/types'
import { ConfidenceNotice } from './ConfidenceNotice'
import { DeliveryGateCard } from './DeliveryGateCard'
import { VariantTabs } from './VariantTabs'
import styles from './ChatStream.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

interface AssistantBlockProps {
  /** 品牌行右侧的元信息（当前轮耗时 / 历史轮次徽章）。 */
  header?: ReactNode
  /** 操作条（TurnActions），紧跟品牌行。 */
  actions?: ReactNode
  /** 过程区标题栏（左边「执行过程」，右边折叠/展开控制）。 */
  processControls?: ReactNode
  /** 阶段时间轴（当前轮实时渲染；历史轮不渲染——未逐帧落库，禁止伪造）。 */
  timeline?: ReactNode
  /** 「正在规划下一步」提示（当前轮思考静默期）。 */
  planning?: ReactNode
  /** 动作序列（历史轮读落库的 steps）。 */
  steps?: readonly Record<string, unknown>[]
  /** 交付证据门结果；undefined/null 表示本轮未过门。 */
  gate?: DeliveryGatePayload | null
  variants?: readonly VariantPayload[]
  /** 历史轮无落库的推荐视图，传 null 时由 ConfidenceNotice 自行省略。 */
  ranking?: RankingViewPayload | null
  /** 未产生推荐的原因（2026-11-06）：single-variant / score-failed。 */
  rankingSkipReason?: string | null
  /** 纯回答轮正文。 */
  replyText?: string
  /** 系统提示文案 / 历史轮结论。 */
  message?: string
  /** 待确认项（历史轮来自 open_items）。 */
  openItems?: readonly string[]
  /** 正文区加载中 / 失败（懒加载历史轮用）。 */
  loading?: boolean
  error?: string
  ariaLabel?: string
  /** 追加正文（当前轮的反问区）。 */
  children?: ReactNode
}

/**
 * 助手块（2026-11-05 全量对话流）：历史轮与当前轮**同构**的唯一渲染器。
 *
 * 结构：品牌行 → 操作条 → 折叠钮 → 时间轴 → 分隔线 → 正文（结论/回答/门禁/方案/待确认）。
 * 零判定（MUST-08/33）：色阶、文案全部来自后端字段；历史轮缺什么就省什么，不伪造。
 */
export function AssistantBlock({
  header,
  actions,
  processControls,
  timeline,
  planning,
  steps,
  gate,
  variants,
  ranking = null,
  rankingSkipReason = null,
  replyText = '',
  message = '',
  openItems,
  loading = false,
  error,
  ariaLabel,
  children,
}: AssistantBlockProps) {
  const { t } = useTranslation()
  const variantList = variants ?? []
  return (
    <article className={s('chat-reply')} aria-label={ariaLabel}>
      <header className={s('chat-reply__head')}>
        <span className={s('chat-reply__mark')} aria-hidden="true" />
        <span className={s('chat-reply__brand')}>DevPrompt AI</span>
        {header}
      </header>

      {actions}

      {processControls}

      {timeline}

      {planning}

      {(steps ?? []).length > 0 ? (
        <div className={s('turn-steps')}>
          {(steps ?? []).map((step, index) => (
            <span className={s('turn-steps__item')} key={`step-${index}`}>
              {String(step.action ?? '')}
            </span>
          ))}
        </div>
      ) : null}

      <hr className={s('chat-reply__divider')} />

      <div className={s('chat-reply__body')}>
        {error !== undefined ? <p className={s('chat-reply__error')}>{error}</p> : null}
        {error === undefined && loading ? (
          <p className={s('thread__loading')}>{t('common.loading')}</p>
        ) : null}

        {message !== '' ? <p className={s('chat-reply__message')}>{message}</p> : null}
        {replyText !== '' ? (
          <div className={s('chat-reply__answer')} role="status">
            <span className={s('chat-reply__answer-label')}>{t('chat.answer')}</span>
            <p className={s('chat-reply__answer-text')}>{replyText}</p>
          </div>
        ) : null}

        <ConfidenceNotice ranking={ranking} skipReason={rankingSkipReason} />
        <DeliveryGateCard gate={gate ?? null} />
        {variantList.length > 0 ? <VariantTabs variants={variantList} ranking={ranking} /> : null}

        {(openItems ?? []).length > 0 ? (
          <p className={s('thread__open')}>
            {t('chat.open_items', { items: (openItems ?? []).join(t('common.list_sep')) })}
          </p>
        ) : null}

        {children}
      </div>
    </article>
  )
}
