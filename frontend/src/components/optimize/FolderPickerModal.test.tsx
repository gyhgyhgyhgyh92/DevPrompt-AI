import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse } from '../../api/types'
import { FolderPickerModal } from './FolderPickerModal'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

interface ListingSpec {
  path: string
  parent: string | null
  entries: { name: string; path: string }[]
  truncated?: boolean
}

/** 按 ?path= 参数分流的 browse stub：'' 键为驱动器列表；未配置路径回 2001 业务错误。 */
function stubBrowse(listings: Record<string, ListingSpec>) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const match = /[?&]path=([^&]*)/.exec(url)
    const key = match !== null ? decodeURIComponent(match[1] as string) : ''
    const spec = listings[key]
    const payload =
      spec === undefined
        ? { code: 2001, message: '目录不存在或不可访问', request_id: 'r', data: null }
        : envelope({ ...spec, truncated: spec.truncated ?? false })
    return {
      status: 200,
      headers: { get: () => null },
      json: async () => payload,
    }
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

const drives: ListingSpec = {
  path: '',
  parent: null,
  entries: [
    { name: 'C:\\', path: 'C:\\' },
    { name: 'D:\\', path: 'D:\\' },
  ],
}
const dRoot: ListingSpec = {
  path: 'D:\\',
  parent: '',
  entries: [{ name: 'Works', path: 'D:\\Works' }],
}
const dWorks: ListingSpec = { path: 'D:\\Works', parent: 'D:\\', entries: [] }

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('FolderPickerModal 页内浏览器（F-601）', () => {
  it('open 时加载驱动器列表；返回与确认在列表模式禁用', async () => {
    stubBrowse({ '': drives })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    expect(await screen.findByRole('button', { name: 'C:\\' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'D:\\' })).toBeTruthy()
    expect(screen.getByText('此电脑')).toBeTruthy()
    expect((screen.getByRole('button', { name: '返回上级' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect(
      (screen.getByRole('button', { name: '选择当前文件夹' }) as HTMLButtonElement).disabled,
    ).toBe(true)
  })

  it('逐级进入与返回上级（驱动器根回退至驱动器列表）', async () => {
    const user = userEvent.setup()
    stubBrowse({ '': drives, 'D:\\': dRoot, 'D:\\Works': dWorks })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: 'D:\\' }))
    expect(await screen.findByRole('button', { name: 'Works' })).toBeTruthy()

    await user.click(screen.getByRole('button', { name: 'Works' }))
    expect(await screen.findByText('此位置没有子文件夹')).toBeTruthy()
    // 空目录视图：当前路径非空，确认可用
    await waitFor(() =>
      expect(
        (screen.getByRole('button', { name: '选择当前文件夹' }) as HTMLButtonElement).disabled,
      ).toBe(false),
    )

    await user.click(screen.getByRole('button', { name: '返回上级' }))
    expect(await screen.findByRole('button', { name: 'Works' })).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '返回上级' }))
    // 驱动器根（parent=""）返回驱动器列表
    expect(await screen.findByRole('button', { name: 'C:\\' })).toBeTruthy()
    expect(screen.getByText('此电脑')).toBeTruthy()
  })

  it('点击「选择当前文件夹」回调 onSelect(当前路径)', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    stubBrowse({ '': drives, 'D:\\': dRoot })
    render(<FolderPickerModal open initialPath="" onSelect={onSelect} onClose={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: 'D:\\' }))
    const confirm = await screen.findByRole('button', { name: '选择当前文件夹' })
    await waitFor(() => expect((confirm as HTMLButtonElement).disabled).toBe(false))
    await user.click(confirm)

    expect(onSelect).toHaveBeenCalledWith('D:\\')
  })

  it('initialPath 非空时直接加载该目录（预浏览已选项目）', async () => {
    stubBrowse({ 'D:\\Works': dWorks })
    render(
      <FolderPickerModal open initialPath={'D:\\Works'} onSelect={vi.fn()} onClose={vi.fn()} />,
    )

    expect(await screen.findByText('此位置没有子文件夹')).toBeTruthy()
    expect(screen.getByText('D:\\Works')).toBeTruthy()
  })

  it('Esc 触发 onClose', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    stubBrowse({ '': drives })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={onClose} />)

    await screen.findByRole('button', { name: 'C:\\' })
    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('加载失败显示错误文案且保留可关闭', async () => {
    stubBrowse({})
    render(
      <FolderPickerModal open initialPath={'D:\\Missing'} onSelect={vi.fn()} onClose={vi.fn()} />,
    )

    expect(await screen.findByText('无法读取该文件夹，请重试')).toBeTruthy()
    expect(screen.getByRole('button', { name: '取消' })).toBeTruthy()
  })

  it('truncated 时显示截断提示', async () => {
    stubBrowse({ '': { ...drives, truncated: true } })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    expect(await screen.findByText('目录过大，仅显示部分子文件夹')).toBeTruthy()
  })

  it('open=false 不渲染任何内容', () => {
    render(<FolderPickerModal open={false} initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
