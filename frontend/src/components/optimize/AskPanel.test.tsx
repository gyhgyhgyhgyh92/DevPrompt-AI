import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AskPanel } from './AskPanel'

afterEach(cleanup)

function renderPanel(overrides: Partial<Parameters<typeof AskPanel>[0]> = {}) {
  const onSubmit = vi.fn()
  const onEscape = vi.fn()
  render(
    <AskPanel
      total={3}
      answered={1}
      isBusy={false}
      onSubmit={onSubmit}
      onEscape={onEscape}
      {...overrides}
    >
      <p>问题区内容</p>
    </AskPanel>,
  )
  return { onSubmit, onEscape }
}

describe('AskPanel 内联反问面板', () => {
  it('内联渲染（不 Portal 到 body），头部显示总数与已答', () => {
    const { container } = render(
      <div>
        <AskPanel total={3} answered={1} isBusy={false} onSubmit={vi.fn()} onEscape={vi.fn()}>
          <p>问题区内容</p>
        </AskPanel>
      </div>,
    )

    expect(container.querySelector('.ask-panel')).not.toBeNull()
    expect(screen.getByText('需要你确认 3 个问题')).toBeTruthy()
    expect(screen.getByText('1 / 3 已答')).toBeTruthy()
    expect(screen.getByText('问题区内容')).toBeTruthy()
  })

  it('不锁定页面滚动（不是模态）', () => {
    document.body.style.overflow = 'auto'
    renderPanel()
    expect(document.body.style.overflow).toBe('auto')
  })

  it('中部问题区是独立滚动容器，头尾在滚动区之外', () => {
    renderPanel()
    const body = document.querySelector('.ask-panel__body')
    expect(body?.querySelector('p')?.textContent).toBe('问题区内容')
    expect(document.querySelector('.ask-panel__head')).not.toBeNull()
    expect(document.querySelector('.ask-panel__foot')).not.toBeNull()
    // 头尾不在滚动区内
    expect(document.querySelector('.ask-panel__head')?.closest('.ask-panel__body')).toBeNull()
    expect(document.querySelector('.ask-panel__foot')?.closest('.ask-panel__body')).toBeNull()
  })

  it('Esc 触发直接生成', async () => {
    const { onEscape, onSubmit } = renderPanel()

    await userEvent.setup().keyboard('{Escape}')

    expect(onEscape).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('提交中忽略 Esc 并禁用按钮', async () => {
    const { onEscape } = renderPanel({ isBusy: true })

    await userEvent.setup().keyboard('{Escape}')

    expect(onEscape).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '提交' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', { name: '直接生成' }).hasAttribute('disabled')).toBe(true)
  })

  it('底部按钮分别触发提交与逃生', async () => {
    const { onSubmit, onEscape } = renderPanel()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: '提交' }))
    await user.click(screen.getByRole('button', { name: '直接生成' }))

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onEscape).toHaveBeenCalledTimes(1)
  })

  it('自定义标题用于软护栏态', () => {
    renderPanel({ title: '软护栏：请裁决' })
    expect(screen.getByText('软护栏：请裁决')).toBeTruthy()
  })

  it('折叠后只剩一行摘要（问题区与底部按钮不渲染），再次点击恢复展开', async () => {
    renderPanel()
    const user = userEvent.setup()
    const toggle = screen.getByRole('button', { name: /需要你确认 3 个问题/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('true')

    await user.click(toggle)

    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(document.querySelector('.ask-panel__body')).toBeNull()
    expect(document.querySelector('.ask-panel__foot')).toBeNull()
    expect(screen.getByText('需要你确认 3 个问题')).toBeTruthy()
    expect(screen.getByText('1 / 3 已答')).toBeTruthy()

    await user.click(toggle)

    expect(document.querySelector('.ask-panel__body')).not.toBeNull()
  })

  it('收起态不响应 Esc（看不见的「直接生成」不该被误触）', async () => {
    const { onEscape } = renderPanel()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /需要你确认 3 个问题/ }))
    await user.keyboard('{Escape}')

    expect(onEscape).not.toHaveBeenCalled()
  })
})
