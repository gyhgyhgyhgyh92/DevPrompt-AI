/**
 * 轻量提示（toast）的状态与计时（2026-11-17 抽取）。
 *
 * 为什么抽：项目侧栏与历史页此前各自实现了一份「文案 state + 2s 计时器 + 清理」，
 * 两份实现会各自漂移（如一侧漏了卸载清理，卸载后仍会 setState）。
 * 统一到本 hook 后，计时与清理只有一份。
 */
import { useCallback, useEffect, useRef, useState } from 'react'

/** 提示显示时长（2s 后自动消退）。 */
export const TOAST_DURATION_MS = 2000

export interface ToastApi {
  /** 当前提示文案；null = 不显示。 */
  message: string | null
  /** 弹出一条提示（重复调用会重置计时）。 */
  show: (text: string) => void
  /** 立即收起。 */
  dismiss: () => void
}

export function useToast(durationMs: number = TOAST_DURATION_MS): ToastApi {
  const [message, setMessage] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimer = useCallback((): void => {
    if (timerRef.current === null) return
    clearTimeout(timerRef.current)
    timerRef.current = null
  }, [])

  // 卸载时清掉计时器，避免对已卸载组件 setState
  useEffect(() => clearTimer, [clearTimer])

  const show = useCallback(
    (text: string): void => {
      clearTimer()
      setMessage(text)
      timerRef.current = setTimeout(() => setMessage(null), durationMs)
    },
    [clearTimer, durationMs],
  )

  const dismiss = useCallback((): void => {
    clearTimer()
    setMessage(null)
  }, [clearTimer])

  return { message, show, dismiss }
}
