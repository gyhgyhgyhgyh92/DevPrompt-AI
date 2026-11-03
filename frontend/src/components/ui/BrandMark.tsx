export interface BrandMarkProps {
  /** 边长（px）；16 / 18 / 24 三种最常用。 */
  size?: number
}

/**
 * DevPrompt AI 品牌标识（2026-11-01 重绘）：品牌绿圆角方块 + 对话框轮廓 + 火花。
 *
 * 图形语义 = 「提示词被优化」：气泡承载输入，火花代表优化火花。
 * 纯内联 SVG，颜色走 `var(--color-primary-500)` 以适配浅/深主题；
 * 装饰性图形（`aria-hidden`），语义由相邻的「DevPrompt AI」文本承担。
 */
export function BrandMark({ size = 18 }: BrandMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
      className="brand-mark"
    >
      <rect
        x="1"
        y="1"
        width="22"
        height="22"
        rx="6.5"
        style={{ fill: 'var(--color-primary-500)' }}
      />
      {/* 对话框：底边留出小尾巴，读作「正在输入的提示词」 */}
      <path
        d="M9 7.1h5.2c1.3 0 2.3 1 2.3 2.3v3.4c0 1.3-1 2.3-2.3 2.3h-2.6l-2.7 2.2v-2.2c-1.2-.1-2.2-1.1-2.2-2.3V9.4c0-1.3 1-2.3 2.3-2.3Z"
        style={{ fill: 'none', stroke: 'var(--color-brand-on)' }}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      {/* 火花：四芒星 */}
      <path
        d="M17.9 3.8l.8 1.9 1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8.8-1.9Z"
        style={{ fill: 'var(--color-brand-on)' }}
      />
    </svg>
  )
}
