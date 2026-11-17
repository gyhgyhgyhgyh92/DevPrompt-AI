import { useEffect, type RefObject } from 'react'

/** 面板内可聚焦元素选择器（原生语义元素 + 带 tabindex 的自定义件）。 */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

/**
 * 模态焦点陷阱（2026-11-17）：Tab / Shift+Tab 在面板内循环，不逃逸到背景。
 *
 * 此前只做「打开移焦 / 关闭归还」，未约束循环——键盘用户可 Tab 到背景内容，
 * 模态的语义因此失效。本次补齐闭环。
 *
 * @param panelRef 模态根节点
 * @param isActive 模态是否打开（关闭时不拦截按键）
 */
export function useFocusTrap(panelRef: RefObject<HTMLElement | null>, isActive: boolean): void {
  useEffect(() => {
    if (!isActive) return
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== 'Tab') return
      const panel = panelRef.current
      if (!panel) return
      const focusables = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      )
      if (focusables.length === 0) return
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      if (!first || !last) return
      const active = document.activeElement
      if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      } else if (event.shiftKey && active === first) {
        event.preventDefault()
        last.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [panelRef, isActive])
}
