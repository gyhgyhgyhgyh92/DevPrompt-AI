import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse } from '../../api/types'
import { FolderPickerModal, formatDateTime } from './FolderPickerModal'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

interface EntrySpec {
  name: string
  path: string
  modified_at?: string | null
}

interface ListingSpec {
  path: string
  parent: string | null
  entries: EntrySpec[]
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
        : envelope({
            path: spec.path,
            parent: spec.parent,
            entries: spec.entries.map((e) => ({
              name: e.name,
              path: e.path,
              modified_at: e.modified_at ?? null,
            })),
            truncated: spec.truncated ?? false,
          })
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
  entries: [
    { name: 'Works', path: 'D:\\Works', modified_at: '2026-10-13T14:30:00' },
    { name: 'Archive', path: 'D:\\Archive' },
  ],
}
const dWorks: ListingSpec = { path: 'D:\\Works', parent: 'D:\\', entries: [] }

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('FolderPickerModal 页内文件夹选择器（F-601）', () => {
  it('open 时加载驱动器列表；工具行与确认按钮初始状态正确', async () => {
    stubBrowse({ '': drives })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    expect(await screen.findByRole('button', { name: 'C:\\' })).toBeTruthy()
    expect(screen.getByText('此电脑')).toBeTruthy()
    expect(screen.getByText('名称')).toBeTruthy()
    expect(screen.getByText('修改日期')).toBeTruthy()
    expect(screen.getByText('2 个文件夹')).toBeTruthy()
    expect((screen.getByRole('button', { name: '后退' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '前进' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '返回上级' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect(
      (screen.getByRole('button', { name: '选择当前文件夹' }) as HTMLButtonElement).disabled,
    ).toBe(true)
  })

  it('修改日期列按格式化显示（无日期留空）；单击仅选中，双击进入', async () => {
    const user = userEvent.setup()
    const mock = stubBrowse({
      '': drives,
      'D:\\': dRoot,
      'D:\\Archive': { path: 'D:\\Archive', parent: 'D:\\', entries: [] },
    })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await user.dblClick(await screen.findByRole('button', { name: 'D:\\' }))
    await screen.findByRole('button', { name: 'Works' })
    expect(screen.getByText('2026/10/13 14:30')).toBeTruthy()
    expect(screen.getByText('2 个文件夹')).toBeTruthy()

    const archive = screen.getByRole('button', { name: 'Archive' })
    await user.click(archive)
    expect(archive.className).toContain('folder-picker__item--selected')
    expect(mock.mock.calls).toHaveLength(2) // 单击未触发第三次加载

    await user.dblClick(archive)
    await waitFor(() => expect(screen.getByText('此文件夹下没有子文件夹')).toBeTruthy())
  })

  it('返回上级逐级回退（驱动器根回驱动器列表）', async () => {
    const user = userEvent.setup()
    stubBrowse({ '': drives, 'D:\\': dRoot, 'D:\\Works': dWorks })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await user.dblClick(await screen.findByRole('button', { name: 'D:\\' }))
    await user.dblClick(await screen.findByRole('button', { name: 'Works' }))
    expect(await screen.findByText('此文件夹下没有子文件夹')).toBeTruthy()
    await waitFor(() =>
      expect(
        (screen.getByRole('button', { name: '选择当前文件夹' }) as HTMLButtonElement).disabled,
      ).toBe(false),
    )

    await user.click(screen.getByRole('button', { name: '返回上级' }))
    expect(await screen.findByRole('button', { name: 'Works' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '返回上级' }))
    expect(await screen.findByRole('button', { name: 'C:\\' })).toBeTruthy()
    expect(screen.getByText('此电脑')).toBeTruthy()
  })

  it('后退/前进沿历史栈导航', async () => {
    const user = userEvent.setup()
    stubBrowse({ '': drives, 'D:\\': dRoot, 'D:\\Works': dWorks })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await user.dblClick(await screen.findByRole('button', { name: 'D:\\' }))
    await user.dblClick(await screen.findByRole('button', { name: 'Works' }))
    expect(await screen.findByText('此文件夹下没有子文件夹')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '后退' }))
    expect(await screen.findByRole('button', { name: 'Works' })).toBeTruthy()
    expect((screen.getByRole('button', { name: '前进' }) as HTMLButtonElement).disabled).toBe(false)

    await user.click(screen.getByRole('button', { name: '前进' }))
    expect(await screen.findByText('此文件夹下没有子文件夹')).toBeTruthy()
  })

  it('面包屑点击跳转（点击「此电脑」回驱动器列表）', async () => {
    const user = userEvent.setup()
    stubBrowse({ '': drives, 'D:\\': dRoot, 'D:\\Works': dWorks })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await user.dblClick(await screen.findByRole('button', { name: 'D:\\' }))
    await user.dblClick(await screen.findByRole('button', { name: 'Works' }))
    expect(await screen.findByText('此文件夹下没有子文件夹')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '此电脑' }))
    expect(await screen.findByRole('button', { name: 'C:\\' })).toBeTruthy()
  })

  it('聚焦行按 Enter 进入（键盘操作）', async () => {
    const user = userEvent.setup()
    stubBrowse({ '': drives, 'D:\\': dRoot })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    const dDrive = await screen.findByRole('button', { name: 'D:\\' })
    dDrive.focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('button', { name: 'Works' })).toBeTruthy()
  })

  it('触屏（coarse pointer）单击即进入', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
    stubBrowse({ '': drives, 'D:\\': dRoot })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: 'D:\\' }))
    expect(await screen.findByRole('button', { name: 'Works' })).toBeTruthy()
  })

  it('点击「选择当前文件夹」回调 onSelect(当前路径)', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    stubBrowse({ '': drives, 'D:\\': dRoot })
    render(<FolderPickerModal open initialPath="" onSelect={onSelect} onClose={vi.fn()} />)

    await user.dblClick(await screen.findByRole('button', { name: 'D:\\' }))
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

    expect(await screen.findByText('此文件夹下没有子文件夹')).toBeTruthy()
    // 面包屑分段渲染（此电脑 › D: › Works），末段为当前位置
    expect(screen.getByText('此电脑')).toBeTruthy()
    expect(screen.getByText('D:')).toBeTruthy()
    expect(screen.getByText('Works')).toBeTruthy()
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

describe('FolderPickerModal 格式工具', () => {
  it('formatDateTime 直接切分 ISO 字符串（不做时区转换）', () => {
    expect(formatDateTime('2026-10-13T14:30:00')).toBe('2026/10/13 14:30')
    expect(formatDateTime(null)).toBe('')
  })
})
