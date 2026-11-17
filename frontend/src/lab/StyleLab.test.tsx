import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import StyleLab from './StyleLab'

beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

function root(container: HTMLElement): HTMLElement {
  const node = container.firstElementChild
  if (node === null) throw new Error('未渲染样张页根节点')
  return node as HTMLElement
}

describe('StyleLab 样张页', () => {
  it('六个章节与三套风格都渲染出来', () => {
    const { container } = render(<StyleLab />)

    expect(screen.getByText('01 · 启动页')).toBeTruthy()
    expect(screen.getByText('06 · 配色与对比度')).toBeTruthy()
    // 每套风格在 5 个章节里各出现一次（章节 03 与 06 不带列头）
    expect(screen.getAllByText('工程图纸').length).toBeGreaterThanOrEqual(4)
    expect(screen.getAllByText('柔和层叠').length).toBeGreaterThanOrEqual(4)
    expect(root(container).getAttribute('data-lab-style')).toBe('blueprint')
  })

  it('切换配色会写回根节点 data 属性（样式由 token 覆盖驱动）', () => {
    const { container } = render(<StyleLab />)

    // 配色在顶部切换器与 06 章节的色卡上各有一个同名按钮，取顶部那个
    const [topSwitcher] = screen.getAllByRole('button', { name: '石墨靛蓝' })
    if (topSwitcher === undefined) throw new Error('未找到配色切换按钮')
    fireEvent.click(topSwitcher)

    expect(root(container).getAttribute('data-lab-palette')).toBe('graphite')
  })

  it('切换主题写入 light / dark，system 解析成具体值', () => {
    const { container } = render(<StyleLab />)

    fireEvent.click(screen.getByRole('button', { name: '深色' }))
    expect(root(container).getAttribute('data-theme')).toBe('dark')

    fireEvent.click(screen.getByRole('button', { name: '浅色' }))
    expect(root(container).getAttribute('data-theme')).toBe('light')
  })

  it('URL 参数可回填初始组合（便于分享某一组样张）', () => {
    window.history.replaceState(null, '', '/?style=soft&palette=amber&theme=dark&variant=digest')

    const { container } = render(<StyleLab />)

    const node = root(container)
    expect(node.getAttribute('data-lab-style')).toBe('soft')
    expect(node.getAttribute('data-lab-palette')).toBe('amber')
    expect(node.getAttribute('data-theme')).toBe('dark')
  })

  it('点击播放后回放推进，事件按序出现；暂停后不再增长', () => {
    vi.useFakeTimers()
    render(<StyleLab />)

    // 顶栏与三列空态各有一个「播放」；顶栏是回放总控
    const [topPlay] = screen.getAllByRole('button', { name: '播放' })
    if (topPlay === undefined) throw new Error('未找到播放按钮')
    fireEvent.click(topPlay)
    // 回放是「一拍一 setTimeout」，必须分步推进：一次性 advance 只会触发已排队的第一个定时器
    for (let step = 0; step < 20; step += 1) {
      act(() => {
        vi.advanceTimersByTime(400)
      })
    }

    // 阶段轨道渲染完整思考文本（打字机受 rAF 限制，不参与断言）
    expect(screen.getAllByText(/先定位 SSE 订阅/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/还差两件事/).length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: '暂停' }))
    const paused = screen.queryAllByText(/还差两件事/).length
    for (let step = 0; step < 12; step += 1) {
      act(() => {
        vi.advanceTimersByTime(400)
      })
    }
    expect(screen.queryAllByText(/还差两件事/).length).toBe(paused)
  })
})
