import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  checkForUpdates,
  downloadUpdate,
  getUpdateState,
  isUpdateSupported,
} from '../../api/desktopUpdate'
import { AboutPanel } from './AboutPanel'

vi.mock('../../api/desktopUpdate', () => ({
  isUpdateSupported: vi.fn(() => true),
  getUpdateState: vi.fn(async () => ({
    phase: 'idle',
    currentVersion: '0.2.0',
    supported: true,
  })),
  subscribeUpdateState: vi.fn(() => () => undefined),
  checkForUpdates: vi.fn(async () => ({
    phase: 'up-to-date',
    currentVersion: '0.2.0',
    supported: true,
  })),
  downloadUpdate: vi.fn(async () => ({
    phase: 'downloading',
    currentVersion: '0.2.0',
    supported: true,
  })),
  installUpdate: vi.fn(async () => ({
    phase: 'installing',
    currentVersion: '0.2.0',
    supported: true,
  })),
  dismissUpdate: vi.fn(async () => ({
    phase: 'idle',
    currentVersion: '0.2.0',
    supported: true,
  })),
}))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('AboutPanel 关于与更新', () => {
  it('展示当前版本，手动检查后显示已是最新', async () => {
    render(<AboutPanel />)

    await waitFor(() => expect(screen.getByText('v0.2.0')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '检查更新' }))

    await waitFor(() => expect(checkForUpdates).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByText('已是最新版本')).toBeTruthy())
  })

  it('Web 形态显示不支持提示且不渲染检查按钮', async () => {
    vi.mocked(isUpdateSupported).mockReturnValueOnce(false)
    render(<AboutPanel />)

    expect(await screen.findByText('Web 形态不支持自动更新；请使用桌面端。')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '检查更新' })).toBeNull()
  })

  it('发现新版本时展示版本/大小并提供下载', async () => {
    vi.mocked(getUpdateState).mockResolvedValueOnce({
      phase: 'available',
      currentVersion: '0.2.0',
      supported: true,
      availableVersion: '0.3.0',
      sizeBytes: 153597724,
    })
    render(<AboutPanel />)

    expect(await screen.findByText('发现新版本 v0.3.0 · 更新包约 146 MB')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '下载更新' }))

    await waitFor(() => expect(downloadUpdate).toHaveBeenCalledTimes(1))
  })
})
