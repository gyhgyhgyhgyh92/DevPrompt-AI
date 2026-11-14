import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { VariantPayload } from '../../api/types'
import { CopyButton } from './CopyButton'
import styles from './optimize.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

interface PromptCardProps {
  /** 本轮唯一方案（契约 VariantPayload）：body 为后端生成原文，前端零加工（MUST-08）。 */
  variant: VariantPayload
  /** 卡内操作条（由页面编排注入，组合优于配置）。 */
  actions?: ReactNode
}

/**
 * 单方案卡片（2026-11-11 单套输出）：title + body + changes。
 * `fallback` 为真表示本轮主流程异常、已降级为保守输出，必须给可见提示。
 */
export function PromptCard({ variant, actions }: PromptCardProps) {
  const { t } = useTranslation()
  const changes = variant.changes ?? []

  return (
    <article className={s('prompt-card')} aria-label={variant.title}>
      <header className={s('prompt-card__header')}>
        <h3>{variant.title}</h3>
      </header>
      {variant.fallback ? (
        <p className={s('prompt-card__fallback')} role="status">
          {t('optimize.fallback_notice')}
        </p>
      ) : null}
      <pre className={s('prompt-card__body')}>
        <code>{variant.body}</code>
      </pre>
      {changes.length > 0 ? (
        <ul className={s('prompt-card__changes')}>
          {changes.map((change) => (
            <li key={change}>{change}</li>
          ))}
        </ul>
      ) : null}
      <footer className={s('prompt-card__footer')}>
        <CopyButton text={variant.body} />
        {actions}
      </footer>
    </article>
  )
}
