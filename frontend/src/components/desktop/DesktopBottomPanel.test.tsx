import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getSessionEvents, openSessionStream } from '../../api/endpoints'
import { useOptimizeStore } from '../../stores/useOptimizeStore'
import { DesktopBottomPanel } from './DesktopBottomPanel'

vi.mock('../../api/endpoints', () => ({
  getSessionEvents: vi.fn(),
  openSessionStream: vi.fn(() => () => undefined),
}))

const EVENTS = [
  { seq: 7, type: 'action', run_id: 'run-1', data: { title: '读取文件' }, ts: 't1' },
  { seq: 8, type: 'error', run_id: 'run-1', data: { message: '命令失败' }, ts: 't2' },
]

beforeEach(() => {
  useOptimizeStore.getState().reset()
  useOptimizeStore.setState({ sessionId: 's-1' })
  vi.mocked(getSessionEvents).mockResolvedValue(EVENTS)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('DesktopBottomPanel', () => {
  it('默认收起，面板头常驻可点', () => {
    render(<DesktopBottomPanel />)

    expect(screen.getByRole('region', { name: '运行日志' })).toBeTruthy()
    expect(screen.getByRole('button', { name: /运行日志/ }).getAttribute('aria-expanded')).toBe(
      'false',
    )
    expect(screen.queryByText('读取文件')).toBeNull()
  })

  it('展开后渲染事件流行', async () => {
    const user = userEvent.setup()
    render(<DesktopBottomPanel />)

    await user.click(screen.getByRole('button', { name: /运行日志/ }))

    await waitFor(() => expect(screen.getByText('读取文件')).toBeTruthy())
    expect(screen.getByText('命令失败')).toBeTruthy()
    expect(screen.getByText('#7')).toBeTruthy()
  })

  it('收起后卸载订阅组件（SSE 随之关闭，不留后台空转）', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    vi.mocked(openSessionStream).mockReturnValue(close)
    render(<DesktopBottomPanel />)

    await user.click(screen.getByRole('button', { name: /运行日志/ }))
    await waitFor(() => expect(openSessionStream).toHaveBeenCalled())

    await user.click(screen.getByRole('button', { name: /运行日志/ }))

    expect(close).toHaveBeenCalled()
  })
})
