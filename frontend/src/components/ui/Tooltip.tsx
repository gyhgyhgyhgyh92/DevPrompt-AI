/**
 * 通用悬停气泡（2026-11-14）。
 *
 * 复用自 `features/obs/ObservabilityPanel.tsx` 的局部 `ModuleTab` 实现：
 * portal + fixed 定位（不被 overflow 裁切）、视口夹紧（窄屏不左右溢出）、
 * `role="tooltip"` + `aria-describedby`、hover/focus 显隐、resize/scroll 自动隐藏。
 * 样式 token 与原 `.obs-tip` 同源（见 tooltip.module.css 注释）。
 */

import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { makeS } from '../../utils/css'
import styles from './tooltip.module.css'

const s = makeS(styles)

/** 气泡最大宽度；窄屏由视口宽度二次夹紧。 */
const TIP_WIDTH = 300
/** 与视口边缘的最小间距。 */
const TIP_MARGIN = 12

export interface TooltipProps {
  /** 气泡内容（自由节点）。与 title/rows 二选一使用。 */
  content?: ReactNode
  /** 气泡标题（便捷字段）。 */
  title?: string
  /** 气泡条目（便捷字段：标签 + 正文）。 */
  rows?: readonly { label: string; text: string }[]
  /** 触发器：包裹式渲染，鼠标进入包裹层或其中获得焦点即显示。 */
  children: ReactNode
  /** 相对触发器的位置：bottom = 下方，right = 右侧。 */
  placement?: 'bottom' | 'right'
  /** 气泡元素 id（缺省自动生成）；给定后触发器的 aria-describedby 指向它。 */
  id?: string
  /** 包裹层附加类名（调用方需要让锚点铺满容器时用）。 */
  anchorClassName?: string
  /**
   * 受控显隐：给定后由外部决定开合（内部 hover 不再自行切换）。
   * 用于「触发区与锚点不同」的场景——如列表项整行悬停触发说明。
   */
  open?: boolean
  /** 受控模式的开关回调。 */
  onOpenChange?: (open: boolean) => void
}

export function Tooltip({
  content,
  title,
  rows,
  children,
  placement = 'bottom',
  id,
  anchorClassName,
  open: controlledOpen,
  onOpenChange,
}: TooltipProps) {
  const anchorRef = useRef<HTMLSpanElement | null>(null)
  const [innerOpen, setInnerOpen] = useState(false)
  const [pos, setPos] = useState({ top: -9999, left: -9999, maxWidth: TIP_WIDTH })
  const generatedId = useId()
  const tipId = id ?? generatedId
  const open = controlledOpen ?? innerOpen

  const place = useCallback((): void => {
    const rect = anchorRef.current?.getBoundingClientRect()
    if (rect === undefined) return
    const maxWidth = Math.min(TIP_WIDTH, window.innerWidth - TIP_MARGIN * 2)
    if (placement === 'right') {
      const left = rect.right + 8
      // 右侧空间不足时回落到触发器下方
      if (left + maxWidth > window.innerWidth - TIP_MARGIN) {
        setPos({
          top: rect.bottom + 8,
          left: Math.min(
            Math.max(rect.left, TIP_MARGIN),
            window.innerWidth - maxWidth - TIP_MARGIN,
          ),
          maxWidth,
        })
        return
      }
      setPos({ top: rect.top, left, maxWidth })
      return
    }
    const centered = rect.left + rect.width / 2 - maxWidth / 2
    setPos({
      top: rect.bottom + 8,
      left: Math.min(Math.max(centered, TIP_MARGIN), window.innerWidth - maxWidth - TIP_MARGIN),
      maxWidth,
    })
  }, [placement])

  const show = useCallback((): void => {
    place()
    if (controlledOpen === undefined) setInnerOpen(true)
    onOpenChange?.(true)
  }, [place, controlledOpen, onOpenChange])

  const hide = useCallback((): void => {
    if (controlledOpen === undefined) setInnerOpen(false)
    onOpenChange?.(false)
  }, [controlledOpen, onOpenChange])

  useEffect(() => {
    if (!open) return undefined
    const onResize = (): void => hide()
    window.addEventListener('resize', onResize)
    window.addEventListener('scroll', onResize, true)
    return () => {
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onResize, true)
    }
  }, [open, hide])

  // 内容随外部状态变化（如切换模式）时重新定位，避免气泡停在旧位置
  useEffect(() => {
    if (open) place()
  }, [open, content, place])

  // 触发器若为单个元素，自动挂 aria-describedby（气泡本体在 portal 里，id 需显式关联）
  const trigger = isValidElement(children)
    ? cloneElement(children as ReactElement<{ 'aria-describedby'?: string }>, {
        'aria-describedby': tipId,
      })
    : children

  return (
    <span
      ref={anchorRef}
      className={
        anchorClassName === undefined
          ? s('tooltip-anchor')
          : `${s('tooltip-anchor')} ${anchorClassName}`
      }
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {trigger}
      {createPortal(
        <span
          id={tipId}
          role="tooltip"
          data-open={open ? 'true' : 'false'}
          className={s('tooltip')}
          style={{ top: `${pos.top}px`, left: `${pos.left}px`, maxWidth: `${pos.maxWidth}px` }}
        >
          {content ?? (
            <>
              {title !== undefined ? <span className={s('tooltip__title')}>{title}</span> : null}
              {(rows ?? []).map((row) => (
                <span key={row.label} className={s('tooltip__row')}>
                  <span className={s('tooltip__label')}>{row.label}</span>
                  {row.text}
                </span>
              ))}
            </>
          )}
        </span>,
        document.body,
      )}
    </span>
  )
}
