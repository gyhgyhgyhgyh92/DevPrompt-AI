import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from './App'

afterEach(cleanup)

describe('工程基座冒烟', () => {
  it('App 渲染不崩溃且路由可切换', async () => {
    const user = userEvent.setup()
    render(<App />)

    expect(screen.getByRole('heading', { name: '优化流程' })).toBeTruthy()

    await user.click(screen.getByRole('link', { name: '历史' }))

    expect(screen.getByRole('heading', { name: '历史记录' })).toBeTruthy()
  })
})
