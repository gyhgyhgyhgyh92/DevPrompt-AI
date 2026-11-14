import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  WheelEvent as ReactWheelEvent,
} from 'react'
import { useTranslation } from 'react-i18next'
import { makeS } from '../../utils/css'
import type { TraceTimelinePoint } from './types'
import { formatMs, formatTimestamp } from './format'
import styles from './observability.module.css'

const s = makeS(styles)

const WIDTH = 1000
const HEIGHT = 64
const PAD = 8
const MIN_WINDOW = 4

export interface ReplayTimelineProps {
  points: TraceTimelinePoint[]
  /** 播放游标（points 下标）。 */
  cursor: number
  /** 已选区间（seq 闭区间）。 */
  range: readonly [number, number] | null
  onSeek: (index: number) => void
  onRangeChange: (range: [number, number] | null) => void
}

/**
 * 时间轴总览（对标 Trajectory 的 timing overview）：
 * 单击定位、拖动选区间、滚轮缩放、右键清除、右键拖拽平移；播放头随 cursor 移动。
 */
export function ReplayTimeline(props: ReplayTimelineProps) {
  const { t } = useTranslation()
  const [viewport, setViewport] = useState<[number, number]>([
    0,
    Math.max(0, props.points.length - 1),
  ])
  const [hover, setHover] = useState<number | null>(null)
  const [preview, setPreview] = useState<[number, number] | null>(null)
  const dragRef = useRef<{ anchor: number; moved: boolean } | null>(null)
  const panRef = useRef<{ x: number; viewport: [number, number] } | null>(null)

  const count = props.points.length
  useEffect(() => {
    setViewport([0, Math.max(0, count - 1)])
    setPreview(null)
    setHover(null)
  }, [count])

  const indexBySeq = useMemo(() => {
    const map = new Map<number, number>()
    props.points.forEach((point, index) => map.set(point.seq, index))
    return map
  }, [props.points])

  const clampWindow = (start: number, end: number): [number, number] => {
    if (count <= 1) return [0, 0]
    // viewport 为闭区间 [start, end]（对应 points 下标）
    const span = Math.max(MIN_WINDOW - 1, Math.min(count - 1, end - start))
    const nextStart = Math.max(0, Math.min(count - 1 - span, start))
    return [nextStart, nextStart + span]
  }

  const ratioOf = (event: { clientX: number; currentTarget: Element }): number => {
    const rect = event.currentTarget.getBoundingClientRect()
    if (rect.width <= 0) return 0
    return Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
  }

  const indexAt = (clientX: number, target: Element): number => {
    const ratio = ratioOf({ clientX, currentTarget: target })
    const [start, end] = viewport
    return Math.max(0, Math.min(count - 1, Math.round(start + ratio * (end - start))))
  }

  const xOfIndex = (index: number): number | null => {
    const [start, end] = viewport
    if (index < start || index > end) return null
    if (end <= start) return WIDTH / 2
    return PAD + ((index - start) / (end - start)) * (WIDTH - PAD * 2)
  }

  const seqRange = preview ?? props.range
  const rangeX =
    seqRange === null
      ? null
      : (() => {
          const startIndex = indexBySeq.get(seqRange[0])
          const endIndex = indexBySeq.get(seqRange[1])
          if (startIndex === undefined || endIndex === undefined) return null
          const from = xOfIndex(Math.min(startIndex, endIndex))
          const to = xOfIndex(Math.max(startIndex, endIndex))
          if (from === null || to === null) return null
          return [from, to] as const
        })()

  const handlePointerDown = (event: ReactPointerEvent<SVGRectElement>): void => {
    event.currentTarget.setPointerCapture?.(event.pointerId)
    const index = indexAt(event.clientX, event.currentTarget)
    if (event.button === 2) {
      panRef.current = { x: event.clientX, viewport }
      return
    }
    if (event.button !== 0) return
    dragRef.current = { anchor: index, moved: false }
    setPreview([index, index])
  }

  const handlePointerMove = (event: ReactPointerEvent<SVGRectElement>): void => {
    const index = indexAt(event.clientX, event.currentTarget)
    setHover(index)
    if (panRef.current !== null) {
      const rect = event.currentTarget.getBoundingClientRect()
      if (rect.width <= 0) return
      const [start, end] = panRef.current.viewport
      const span = end - start
      const delta = ((event.clientX - panRef.current.x) / rect.width) * span
      setViewport(clampWindow(start - delta, end - delta))
      return
    }
    if (dragRef.current !== null) {
      const anchor = dragRef.current.anchor
      if (Math.abs(index - anchor) > 0) dragRef.current.moved = true
      setPreview([anchor, index])
    }
  }

  const handlePointerUp = (event: ReactPointerEvent<SVGRectElement>): void => {
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    if (panRef.current !== null) {
      const moved = Math.abs(event.clientX - panRef.current.x) > 2
      panRef.current = null
      if (!moved && event.button === 2) props.onRangeChange(null)
      return
    }
    const drag = dragRef.current
    dragRef.current = null
    setPreview(null)
    if (drag === null) return
    const index = indexAt(event.clientX, event.currentTarget)
    if (!drag.moved || Math.abs(index - drag.anchor) <= 1) {
      props.onSeek(index)
      return
    }
    const startIndex = Math.min(drag.anchor, index)
    const endIndex = Math.max(drag.anchor, index)
    const startSeq = props.points[startIndex]?.seq
    const endSeq = props.points[endIndex]?.seq
    if (startSeq !== undefined && endSeq !== undefined) {
      props.onRangeChange([startSeq, endSeq])
    }
  }

  const handleWheel = (event: ReactWheelEvent<SVGRectElement>): void => {
    event.preventDefault()
    if (count <= MIN_WINDOW) return
    const ratio = ratioOf(event)
    const [start, end] = viewport
    const span = end - start
    const focus = start + ratio * span
    const factor = event.deltaY > 0 ? 1.2 : 1 / 1.2
    const nextSpan = Math.max(MIN_WINDOW - 1, Math.min(count - 1, span * factor))
    const nextStart = focus - ratio * nextSpan
    setViewport(clampWindow(nextStart, nextStart + nextSpan))
  }

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>): void => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      props.onSeek(Math.max(0, props.cursor - 1))
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      props.onSeek(Math.min(count - 1, props.cursor + 1))
    } else if (event.key === 'Home') {
      event.preventDefault()
      props.onSeek(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      props.onSeek(Math.max(0, count - 1))
    }
  }

  const visible = props.points
    .map((point, index) => ({ point, index }))
    .filter(({ index }) => index >= viewport[0] && index <= viewport[1])
  const blockWidth = Math.max(
    2,
    Math.min(14, (WIDTH - PAD * 2) / Math.max(1, viewport[1] - viewport[0] + 1) - 1),
  )
  const cursorX = xOfIndex(props.cursor)
  const hoverPoint = hover === null ? null : (props.points[hover] ?? null)
  const hoverX = hover === null ? null : xOfIndex(hover)

  return (
    <div
      className={s('obs-timeline')}
      role="slider"
      tabIndex={0}
      aria-label={t('observability.timeline.aria')}
      aria-valuemin={0}
      aria-valuemax={Math.max(0, count - 1)}
      aria-valuenow={props.cursor}
      onKeyDown={handleKeyDown}
    >
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className={s('obs-timeline__svg')}>
        <rect
          x={PAD}
          y={4}
          width={WIDTH - PAD * 2}
          height={HEIGHT - 8}
          className={s('obs-timeline__track')}
        />
        {visible.map(({ point, index }) => {
          const x = xOfIndex(index)
          if (x === null) return null
          return (
            <rect
              key={point.seq}
              x={x - blockWidth / 2}
              y={14}
              width={blockWidth}
              height={HEIGHT - 28}
              rx={1.5}
              className={s('obs-timeline__block')}
              data-type={point.type}
            />
          )
        })}
        {rangeX !== null ? (
          <rect
            x={rangeX[0]}
            y={4}
            width={Math.max(1, rangeX[1] - rangeX[0])}
            height={HEIGHT - 8}
            className={s('obs-timeline__range')}
          />
        ) : null}
        {cursorX !== null ? (
          <>
            <line
              x1={cursorX}
              y1={2}
              x2={cursorX}
              y2={HEIGHT - 2}
              className={s('obs-timeline__playhead')}
            />
            <circle cx={cursorX} cy={6} r={3} className={s('obs-timeline__playhead-dot')} />
          </>
        ) : null}
        <rect
          x={0}
          y={0}
          width={WIDTH}
          height={HEIGHT}
          fill="transparent"
          className={s('obs-timeline__hit')}
          data-testid="obs-timeline-hit"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={() => setHover(null)}
          onWheel={handleWheel}
          onContextMenu={(event) => event.preventDefault()}
        />
      </svg>
      {hoverPoint !== null && hoverX !== null ? (
        <div
          className={s('obs-timeline__tooltip')}
          style={{ left: `${(hoverX / WIDTH) * 100}%` }}
          role="tooltip"
        >
          <strong>
            #{hoverPoint.seq} · {hoverPoint.type}
          </strong>
          <span>{hoverPoint.label}</span>
          <span>
            {formatTimestamp(hoverPoint.ts)} · {formatMs(hoverPoint.duration_ms)}
          </span>
        </div>
      ) : null}
      <p className={s('obs-note')}>{t('observability.timeline.hint')}</p>
    </div>
  )
}
