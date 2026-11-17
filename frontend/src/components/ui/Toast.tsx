/**
 * 统一轻量提示（toast）组件（2026-11-17）。
 *
 * 视觉沿用原 `.project-sidebar__toast`（反白胶囊 + 8px 圆角 + 12px 字号），
 * 但改为 portal 到 body 定位在视口底部居中——原先侧栏内的那份被约束在 248px 侧栏内，
 * 与历史页那份（贴在内容区底部）位置不一致，同一产品两种提示位置是视觉不一致的来源。
 */
import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'
import { makeS } from '../../utils/css'
import styles from './Toast.module.css'

const s = makeS(styles)

export interface ToastProps {
  /** 提示文案；null = 不渲染。 */
  message: string | null
}

export function Toast({ message }: ToastProps): ReactNode {
  if (message === null) return null
  return createPortal(
    <div className={s('toast')} role="status" aria-live="polite">
      {message}
    </div>,
    document.body,
  )
}
