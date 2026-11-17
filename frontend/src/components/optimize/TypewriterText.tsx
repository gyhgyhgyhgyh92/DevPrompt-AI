import { useEffect, useState } from 'react'

/** 系统「减少动效」：命中时不做逐字，直接整段呈现（也避免长时间阅读被打断）。 */
function useReducedMotion(): boolean {
  const [isReduced, setReduced] = useState(
    () =>
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const handleChange = (): void => setReduced(media.matches)
    media.addEventListener?.('change', handleChange)
    return () => media.removeEventListener?.('change', handleChange)
  }, [])

  return isReduced
}

/** 每帧推进的字数：3 字/帧 ≈ 180 字/秒，既看得出「在写」又不会让人等。 */
const CHARS_PER_FRAME = 3

interface TypewriterTextProps {
  text: string
  /** 仅「当前仍在增长的最后一条思考」为 true；历史条目与结束后的内容直接整段显示。 */
  isAnimating: boolean
  className?: string
}

/**
 * 逐字呈现（V1 打字机）。
 *
 * 关键约束：**只在增量增长时逐字**。组件初值是完整文本，因此
 * ① 回看历史 / 切换轮次不会把旧内容重放一遍；
 * ② jsdom（无 rAF 或测试环境）与首屏都能立刻读到全文，不依赖动画完成。
 */
export function TypewriterText({ text, isAnimating, className }: TypewriterTextProps) {
  const [shown, setShown] = useState(text)
  const isReduced = useReducedMotion()

  useEffect(() => {
    if (!isAnimating || isReduced || typeof requestAnimationFrame !== 'function') {
      setShown(text)
      return undefined
    }
    if (!text.startsWith(shown)) {
      setShown(text)
      return undefined
    }
    if (shown.length >= text.length) return undefined
    const frame = requestAnimationFrame(() => {
      setShown(text.slice(0, Math.min(text.length, shown.length + CHARS_PER_FRAME)))
    })
    return () => cancelAnimationFrame(frame)
  }, [text, shown, isAnimating, isReduced])

  const isTyping = isAnimating && !isReduced && shown.length < text.length

  return (
    <p className={className}>
      {shown}
      {isTyping ? <span className="chat-reply__caret" aria-hidden="true" /> : null}
    </p>
  )
}
