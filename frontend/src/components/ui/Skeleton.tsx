/**
 * 统一骨架屏（2026-11-17）。
 *
 * 对标 Trae 的两种加载动画：脉冲（pulse 1.4s ease-in-out）与渐变扫光
 * （shimmer 1.5s infinite，overlay-l1 → l2 → l1）。项目此前的加载态只有
 * 文案占位与呼吸圆点，列表加载时没有"形状占位"，视觉上会跳。
 */
import type { ReactNode } from 'react'
import { makeS } from '../../utils/css'
import styles from './Skeleton.module.css'

const s = makeS(styles)

export interface SkeletonProps {
  /** 宽（默认 100%）。 */
  width?: string
  /** 高（默认 1em 随字号）。 */
  height?: string
  /** 圆角（默认 4px，对齐 Trae radius-4）。 */
  radius?: string
  /** 动画：pulse = 呼吸；shimmer = 扫光。 */
  variant?: 'pulse' | 'shimmer'
}

export function Skeleton({
  width = '100%',
  height = '1em',
  radius = 'var(--radius-chip)',
  variant = 'pulse',
}: SkeletonProps): ReactNode {
  return (
    <span
      className={s('skeleton', `skeleton--${variant}`)}
      style={{ inlineSize: width, blockSize: height, borderRadius: radius }}
      aria-hidden="true"
    />
  )
}
