import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DomainSelect } from './DomainSelect'

// 全局 setup 只初始化 i18n、未开 RTL 自动清理：本文件多次渲染需自行清理
afterEach(cleanup)

describe('DomainSelect', () => {
  it('触发器显示当前模式，展开后列出全部选项', async () => {
    const user = userEvent.setup()
    render(<DomainSelect value="visual" onChange={() => undefined} />)

    const trigger = screen.getByRole('button', { name: /视觉|visual/i })
    expect(trigger).toBeTruthy()

    await user.click(trigger)
    const options = screen.getAllByRole('option')
    // 自动识别 + 15 个领域包
    expect(options).toHaveLength(16)
  })

  it('选择选项回调对应模式并收起菜单', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<DomainSelect value="" onChange={onChange} />)

    await user.click(screen.getByRole('button'))
    await user.click(screen.getByRole('option', { name: /代码|code/i }))

    expect(onChange).toHaveBeenCalledWith('code')
    expect(screen.queryAllByRole('option')).toHaveLength(0)
  })

  it('Esc 收起菜单', async () => {
    const user = userEvent.setup()
    render(<DomainSelect value="" onChange={() => undefined} />)

    await user.click(screen.getByRole('button'))
    expect(screen.getAllByRole('option').length).toBeGreaterThan(0)

    await user.keyboard('{Escape}')
    expect(screen.queryAllByRole('option')).toHaveLength(0)
  })

  it('键盘方向键 + Enter 可完成选择', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<DomainSelect value="" onChange={onChange} />)

    const trigger = screen.getByRole('button')
    trigger.focus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getAllByRole('option').length).toBeGreaterThan(0)

    await user.keyboard('{ArrowDown}{Enter}')
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('悬停选项弹出该模式的气泡说明', async () => {
    const user = userEvent.setup()
    render(<DomainSelect value="" onChange={() => undefined} />)

    await user.click(screen.getByRole('button'))
    const option = screen.getByRole('option', { name: /代码|code/i })
    await user.hover(option)

    // 页面同时存在触发器与各选项的气泡，断言「有气泡处于打开态」
    const tips = Array.from(document.querySelectorAll('[role="tooltip"]'))
    const opened = tips.filter((tip) => tip.getAttribute('data-open') === 'true')
    expect(opened.length).toBeGreaterThan(0)
  })
})
