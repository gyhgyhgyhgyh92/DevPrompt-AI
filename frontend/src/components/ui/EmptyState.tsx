/**
 * 统一空态（2026-11-17）。
 *
 * 对标 Trae `.emptyState`：48×48 圆角图标底座 + 600 标题 + 说明 + 可选动作。
 * 项目此前的空态全是纯文字（`context-panel__empty` / `project-sidebar__empty` /
 * `history.empty`），缺一个视觉锚点，列表为空时界面显得"没做完"。
 *
 * 两种变体：
 * - `icon`：图标底座 + 标题 + 说明（桌面工作台用，与 Trae 对齐）；
 * - `text`：维持既有纯文字形态（Web 形态零变化）。
 */
import type { ReactNode } from 'react'
import { makeS } from '../../utils/css'
import styles from './EmptyState.module.css'

const s = makeS(styles)

export interface EmptyStateProps {
  /** 标题（一行说清「这里该有什么」）。 */
  title: string
  /** 说明文案（可选）。 */
  description?: string
  /** 图标（icon 变体用）。 */
  icon?: ReactNode
  /** 形态：icon = 图标底座；text = 纯文字。 */
  variant?: 'icon' | 'text'
  /** 可选动作（如「重试」按钮）。 */
  action?: ReactNode
}

export function EmptyState({
  title,
  description,
  icon,
  variant = 'text',
  action,
}: EmptyStateProps): ReactNode {
  if (variant === 'text') {
    return (
      <div className={s('empty-state empty-state--text')}>
        <p className={s('empty-state__title')}>{title}</p>
        {description !== undefined ? <p className={s('empty-state__desc')}>{description}</p> : null}
        {action}
      </div>
    )
  }

  return (
    <div className={s('empty-state empty-state--icon')}>
      {icon !== undefined ? <div className={s('empty-state__icon')}>{icon}</div> : null}
      <p className={s('empty-state__title')}>{title}</p>
      {description !== undefined ? <p className={s('empty-state__desc')}>{description}</p> : null}
      {action}
    </div>
  )
}
