import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SessionMenu } from './SessionMenu'

afterEach(cleanup)

function renderMenu(overrides: Partial<Parameters<typeof SessionMenu>[0]> = {}) {
  const props = {
    isPinned: false,
    onPin: vi.fn(),
    onCopyPath: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  }
  render(<SessionMenu {...props} />)
  return props
}

describe('SessionMenu ⋮ 弹出菜单', () => {
  it('渲染 4 项菜单（置顶任务/复制项目路径/重命名/删除任务）', () => {
    renderMenu()

    expect(screen.getAllByRole('menuitem')).toHaveLength(4)
    expect(screen.getByRole('menuitem', { name: /置顶任务/ })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: /复制项目路径/ })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: /重命名/ })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: /删除任务/ })).toBeTruthy()
  })

  it('Esc 关闭菜单', async () => {
    const user = userEvent.setup()
    const props = renderMenu()

    await user.keyboard('{Escape}')

    expect(props.onClose).toHaveBeenCalledTimes(1)
  })

  it('外点关闭菜单', async () => {
    const user = userEvent.setup()
    const props = renderMenu()

    await user.click(document.body)

    expect(props.onClose).toHaveBeenCalled()
  })

  it('删除项点击即上抛 onDelete（确认弹窗由外层负责）', async () => {
    const user = userEvent.setup()
    const props = renderMenu()

    await user.click(screen.getByRole('menuitem', { name: /删除任务/ }))

    expect(props.onDelete).toHaveBeenCalledTimes(1)
  })
})
