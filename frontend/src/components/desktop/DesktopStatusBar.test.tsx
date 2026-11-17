import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useOptimizeStore } from '../../stores/useOptimizeStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { DesktopStatusBar } from './DesktopStatusBar'

beforeEach(() => {
  useOptimizeStore.getState().reset()
  useHistoryStore.getState().reset()
  useSettingsStore.setState({ settings: null })
})

afterEach(() => {
  cleanup()
})

describe('DesktopStatusBar', () => {
  it('无会话时给出占位文案与 API 状态', () => {
    render(<DesktopStatusBar apiStatus="ok" />)

    expect(screen.getByRole('contentinfo', { name: '状态栏' })).toBeTruthy()
    expect(screen.getByText('无会话')).toBeTruthy()
    expect(screen.getByText('API 正常')).toBeTruthy()
  })

  it('有会话时展示会话短码与状态机态（镜像后端，不做判定）', () => {
    useOptimizeStore.setState({ sessionId: 'abcdef123456', state: 'DONE', status: 'done' })
    render(<DesktopStatusBar apiStatus="checking" />)

    expect(screen.getByText(/会话 #123456/)).toBeTruthy()
    expect(screen.getByText('DONE')).toBeTruthy()
    expect(screen.getByText('done')).toBeTruthy()
    expect(screen.getByText('API 检测中')).toBeTruthy()
  })

  it('展示 SSE 连接态', () => {
    useOptimizeStore.setState({ sseStatus: 'open' })
    render(<DesktopStatusBar apiStatus="ok" />)

    expect(screen.getByText('已连接')).toBeTruthy()
  })
})
