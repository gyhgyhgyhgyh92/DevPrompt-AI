import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CopyButton } from './CopyButton'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('CopyButton 复制', () => {
  it('点击后把原文写入剪贴板', async () => {
    const user = userEvent.setup()
    // userEvent.setup() 自带剪贴板 stub，须在其后注入 spy 才是组件实际调用的对象
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<CopyButton text="方案原文 body" />)

    await user.click(screen.getByRole('button', { name: '复制' }))

    expect(writeText).toHaveBeenCalledWith('方案原文 body')
  })

  it('复制成功后按钮切换为已复制态', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<CopyButton text="方案原文 body" />)

    await user.click(screen.getByRole('button', { name: '复制' }))

    expect(await screen.findByRole('button', { name: '已复制' })).toBeTruthy()
  })
})
