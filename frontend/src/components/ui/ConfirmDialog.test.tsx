import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from './ConfirmDialog'

afterEach(cleanup)

function renderDialog(overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onConfirm = vi.fn()
  const onClose = vi.fn()
  render(
    <ConfirmDialog
      title="删除项目"
      description="将删除 3 条会话记录，不会删除本地文件。"
      confirmLabel="删除"
      isBusy={false}
      onConfirm={onConfirm}
      onClose={onClose}
      {...overrides}
    />,
  )
  return { onConfirm, onClose }
}

describe('ConfirmDialog 通用确认弹窗', () => {
  it('渲染标题、正文与两个按钮', () => {
    renderDialog()

    expect(screen.getByRole('dialog', { name: '删除项目' })).toBeTruthy()
    expect(screen.getByText('将删除 3 条会话记录，不会删除本地文件。')).toBeTruthy()
    expect(screen.getByRole('button', { name: '删除' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '取消' })).toBeTruthy()
  })

  it('点确认触发 onConfirm', async () => {
    const { onConfirm, onClose } = renderDialog()

    await userEvent.setup().click(screen.getByRole('button', { name: '删除' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('点取消触发 onClose', async () => {
    const { onConfirm, onClose } = renderDialog()

    await userEvent.setup().click(screen.getByRole('button', { name: '取消' }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('Esc 关闭', () => {
    const { onClose } = renderDialog()

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('提交中禁用按钮并忽略 Esc（MUST-15 防重复提交）', async () => {
    const { onClose, onConfirm } = renderDialog({ isBusy: true })

    expect(screen.getByRole('button', { name: '取消' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', { name: '处理中…' }).hasAttribute('disabled')).toBe(true)

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(onClose).not.toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
  })
})
