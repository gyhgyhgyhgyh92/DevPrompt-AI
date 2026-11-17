import { useEffect, useState } from 'react'

/** 极简 class 拼接（不引入 clsx：只过滤假值，不做冲突合并，样式以条件表达式控制）。 */
export function cx(...parts: readonly (string | false | null | undefined)[]): string {
  return parts.filter((part): part is string => typeof part === 'string' && part !== '').join(' ')
}

type Rgba = readonly [number, number, number, number]

function parseColor(raw: string): Rgba | null {
  const value = raw.trim()
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value)
  if (hex !== null) {
    const body = hex[1] ?? ''
    const full =
      body.length === 3
        ? body
            .split('')
            .map((char) => char + char)
            .join('')
        : body
    if (full.length !== 6) return null
    return [
      Number.parseInt(full.slice(0, 2), 16),
      Number.parseInt(full.slice(2, 4), 16),
      Number.parseInt(full.slice(4, 6), 16),
      1,
    ]
  }
  const rgb = /^rgba?\(([^)]+)\)$/i.exec(value)
  if (rgb !== null) {
    const parts = (rgb[1] ?? '').split(/[\s,/]+/).filter((part) => part !== '')
    if (parts.length >= 3) {
      const channel = (index: number): number => {
        const piece = parts[index] ?? '0'
        return piece.endsWith('%')
          ? Math.round((Number.parseFloat(piece) / 100) * 255)
          : Math.round(Number.parseFloat(piece))
      }
      const alpha = parts.length >= 4 ? Number.parseFloat(parts[3] ?? '1') : 1
      return [channel(0), channel(1), channel(2), Number.isFinite(alpha) ? alpha : 1]
    }
  }
  return null
}

/** 半透明色叠到实底上（深色主题的 soft 色多为 rgba，直接算对比度会失真）。 */
export function blendOver(foreground: string, background: string): string {
  const front = parseColor(foreground)
  const back = parseColor(background)
  if (front === null || back === null) return foreground
  const alpha = front[3]
  const mix = (index: 0 | 1 | 2): number =>
    Math.round(front[index] * alpha + back[index] * (1 - alpha))
  return `rgb(${mix(0)}, ${mix(1)}, ${mix(2)})`
}

function relativeLuminance([r, g, b]: Rgba): number {
  const channel = (value: number): number => {
    const scaled = value / 255
    return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

/** WCAG 2.1 对比度；任一颜色无法解析时返回 null（表格显示「—」而不是编一个数）。 */
export function contrastRatio(foreground: string, background: string): number | null {
  const front = parseColor(foreground)
  const back = parseColor(background)
  if (front === null || back === null) return null
  const a = relativeLuminance(front)
  const b = relativeLuminance(back)
  const [light, dark] = a >= b ? [a, b] : [b, a]
  return (light + 0.05) / (dark + 0.05)
}

/** 读容器上某个 token 的**计算值**（custom property 会解析 var() 链），用于实测对比度。 */
export function readToken(node: Element, name: string): string {
  return getComputedStyle(node).getPropertyValue(name).trim()
}

/** 尊重系统的减少动效设置（样张里的打字机 / 流光据此降级）。 */
export function usePrefersReducedMotion(): boolean {
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
