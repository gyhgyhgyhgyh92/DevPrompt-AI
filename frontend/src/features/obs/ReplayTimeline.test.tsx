import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TraceTimelinePoint } from './types'
import { ReplayTimeline } from './ReplayTimeline'

function points(count: number): TraceTimelinePoint[] {
  return Array.from({ length: count }, (_, index) => ({
    seq: index + 1,
    type: index % 2 === 0 ? 'thought' : 'action',
    ts: '',
    run_id: 'r',
    label: `事件 ${index + 1}`,
    phase: '',
    duration_ms: null,
  }))
}

afterEach(() => {
  cleanup()
})

describe('ReplayTimeline', () => {
  it('键盘左右与 Home/End 驱动游标', () => {
    const onSeek = vi.fn()
    render(
      <ReplayTimeline
        points={points(5)}
        cursor={0}
        range={null}
        onSeek={onSeek}
        onRangeChange={vi.fn()}
      />,
    )
    const slider = screen.getByRole('slider', { name: '事件时间轴' })

    fireEvent.keyDown(slider, { key: 'ArrowRight' })
    expect(onSeek).toHaveBeenLastCalledWith(1)
    fireEvent.keyDown(slider, { key: 'End' })
    expect(onSeek).toHaveBeenLastCalledWith(4)
    fireEvent.keyDown(slider, { key: 'Home' })
    expect(onSeek).toHaveBeenLastCalledWith(0)
  })

  it('单击按横坐标就近定位', () => {
    const onSeek = vi.fn()
    render(
      <ReplayTimeline
        points={points(5)}
        cursor={0}
        range={null}
        onSeek={onSeek}
        onRangeChange={vi.fn()}
      />,
    )
    const hit = screen.getByTestId('obs-timeline-hit') as unknown as SVGRectElement
    expect(hit).toBeTruthy()
    hit.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 1000, height: 64, right: 1000, bottom: 64, x: 0, y: 0 }) as DOMRect

    fireEvent.pointerDown(hit, { clientX: 500, button: 0, pointerId: 1 })
    fireEvent.pointerUp(hit, { clientX: 500, button: 0, pointerId: 1 })

    expect(onSeek).toHaveBeenCalledWith(2)
  })

  it('拖选区间回传首尾 seq', () => {
    const onRangeChange = vi.fn()
    render(
      <ReplayTimeline
        points={points(5)}
        cursor={0}
        range={null}
        onSeek={vi.fn()}
        onRangeChange={onRangeChange}
      />,
    )
    const hit = screen.getByTestId('obs-timeline-hit') as unknown as SVGRectElement
    hit.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 1000, height: 64, right: 1000, bottom: 64, x: 0, y: 0 }) as DOMRect

    fireEvent.pointerDown(hit, { clientX: 100, button: 0, pointerId: 1 })
    fireEvent.pointerMove(hit, { clientX: 900, button: 0, pointerId: 1 })
    fireEvent.pointerUp(hit, { clientX: 900, button: 0, pointerId: 1 })

    expect(onRangeChange).toHaveBeenCalledWith([1, 5])
  })

  it('右键单击清除已选区间', () => {
    const onRangeChange = vi.fn()
    render(
      <ReplayTimeline
        points={points(5)}
        cursor={0}
        range={[1, 3]}
        onSeek={vi.fn()}
        onRangeChange={onRangeChange}
      />,
    )
    const hit = screen.getByTestId('obs-timeline-hit') as unknown as SVGRectElement
    hit.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 1000, height: 64, right: 1000, bottom: 64, x: 0, y: 0 }) as DOMRect

    fireEvent.pointerDown(hit, { clientX: 300, button: 2, pointerId: 1 })
    fireEvent.pointerUp(hit, { clientX: 300, button: 2, pointerId: 1 })

    expect(onRangeChange).toHaveBeenCalledWith(null)
  })
})
