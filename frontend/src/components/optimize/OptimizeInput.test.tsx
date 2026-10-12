import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OptimizeInput } from './OptimizeInput'

afterEach(cleanup)

describe('OptimizeInput 优化输入', () => {
  it('草稿为空时提交按钮禁用（防重复/防误触）', () => {
    render(<OptimizeInput isSubmitting={false} onSubmit={vi.fn()} />)

    expect((screen.getByRole('button', { name: '开始优化' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
  })

  it('填写后提交并上抛原句与项目路径（草稿不出组件）', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<OptimizeInput isSubmitting={false} onSubmit={onSubmit} />)

    await user.type(screen.getByRole('textbox', { name: '项目路径' }), 'D:/ws/repo')
    await user.type(screen.getByRole('textbox', { name: '优化原句' }), '加个导出按钮')
    await user.click(screen.getByRole('button', { name: '开始优化' }))

    expect(onSubmit).toHaveBeenCalledWith('加个导出按钮', 'D:/ws/repo')
  })

  it('提交中按钮禁用且文案切换（MUST-15 禁重试语义）', () => {
    render(<OptimizeInput isSubmitting onSubmit={vi.fn()} />)

    expect((screen.getByRole('button', { name: '提交中…' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
  })
})
