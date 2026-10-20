import { afterEach, describe, expect, it, vi } from 'vitest'
import { NOT_INSTALLED_HINT, pickFolderViaNative } from './nativeFolder'

/**
 * 模拟扩展回信。
 *
 * 注意：jsdom 的 `window.postMessage` 派发的事件 `source` 为 null，与浏览器不同，
 * 故这里用 `new MessageEvent(..., { source: window })` 显式派发——生产代码的
 * 「只信本页面的消息」守卫保持严格，不为测试放宽。
 */
function simulateExtension(payload: Record<string, unknown>): void {
  const onRequest = (event: Event): void => {
    const data = (event as MessageEvent).data as { source?: string; kind?: string; id?: string }
    if (data?.source !== 'devprompt-ai' || data.kind !== 'request') return
    window.dispatchEvent(
      new MessageEvent('message', {
        data: { source: 'devprompt-ai', kind: 'response', id: data.id, ...payload },
        source: window,
      }),
    )
  }
  window.addEventListener('message', onRequest)
  cleanup.push(() => window.removeEventListener('message', onRequest))
}

const cleanup: (() => void)[] = []

afterEach(() => {
  cleanup.forEach((fn) => fn())
  cleanup.length = 0
})

describe('pickFolderViaNative（扩展桥）', () => {
  it('成功：回传选中路径', async () => {
    simulateExtension({ ok: true, path: 'D:/ws/repo' })
    await expect(pickFolderViaNative()).resolves.toEqual({ path: 'D:/ws/repo' })
  })

  it('用户取消：空串而非报错', async () => {
    simulateExtension({ ok: true, path: '' })
    await expect(pickFolderViaNative()).resolves.toEqual({ path: '' })
  })

  it('宿主报错：抛出该错误文案', async () => {
    simulateExtension({ ok: false, error: '系统文件夹选择器当前仅支持 Windows' })
    await expect(pickFolderViaNative()).rejects.toThrow('仅支持 Windows')
  })

  it('扩展回 ok=false 且无 error：回落到「未装扩展」指引', async () => {
    simulateExtension({ ok: false })
    await expect(pickFolderViaNative()).rejects.toThrow(NOT_INSTALLED_HINT)
  })

  it('无扩展应答：超时后给出可执行指引（不静默）', async () => {
    vi.useFakeTimers()
    try {
      const pending = pickFolderViaNative(50)
      const assertion = expect(pending).rejects.toThrow(NOT_INSTALLED_HINT)
      await vi.advanceTimersByTimeAsync(60)
      await assertion
    } finally {
      vi.useRealTimers()
    }
  })

  it('非本扩展的同形消息不被采纳（source 标记不符）', async () => {
    const onRequest = (event: Event): void => {
      const data = (event as MessageEvent).data as { source?: string; kind?: string; id?: string }
      if (data?.source !== 'devprompt-ai' || data.kind !== 'request') return
      window.dispatchEvent(
        new MessageEvent('message', {
          data: {
            source: 'evil-extension',
            kind: 'response',
            id: data.id,
            ok: true,
            path: 'C:/bad',
          },
          source: window,
        }),
      )
    }
    window.addEventListener('message', onRequest)
    cleanup.push(() => window.removeEventListener('message', onRequest))
    vi.useFakeTimers()
    try {
      const pending = pickFolderViaNative(50)
      const assertion = expect(pending).rejects.toThrow(NOT_INSTALLED_HINT)
      await vi.advanceTimersByTimeAsync(60)
      await assertion
    } finally {
      vi.useRealTimers()
    }
  })
})
