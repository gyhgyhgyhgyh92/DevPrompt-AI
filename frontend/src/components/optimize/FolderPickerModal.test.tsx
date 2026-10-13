import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse } from '../../api/types'
import { FolderPickerModal, formatDateTime, formatSize } from './FolderPickerModal'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

interface EntrySpec {
  name: string
  path: string
  kind?: 'dir' | 'file'
  size?: number | null
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
              kind: e.kind ?? 'dir',
              size: e.size ?? null,
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
    { name: 'Works', path: 'D:\\Works' },
    {
      name: 'readme.md',
      path: 'D:\\readme.md',
      kind: 'file',
      size: 1536,
      modified_at: '2026-10-13T14:30:00',
    },
  ],
}
const dWorks: ListingSpec = { path: 'D:\\Works', parent: 'D:\\', entries: [] }

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('FolderPickerModal 页内文件资源管理器（F-601）', () => {
  it('open 时加载驱动器列表；工具行与确认按钮初始状态正确', async () => {
    stubBrowse({ '': drives })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    expect(await screen.findByRole('button', { name: 'C:\\' })).toBeTruthy()
    expect(screen.getByText('此电脑')).toBeTruthy()
    expect(screen.getByText('名称')).toBeTruthy()
    expect(screen.getByText('修改日期')).toBeTruthy()
    expect(screen.getByText('类型')).toBeTruthy()
    expect(screen.getByText('大小')).toBeTruthy()
    expect(screen.getByText('2 个项目')).toBeTruthy()
    expect((screen.getByRole('button', { name: '后退' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '前进' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '返回上级' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect(
      (screen.getByRole('button', { name: '选择当前文件夹' }) as HTMLButtonElement).disabled,
    ).toBe(true)
  })

  it('鼠标语义下单击目录仅选中（不进入），双击才进入；出发返回上级', async () => {
    const user = userEvent.setup()
    const mock = stubBrowse({ '': drives, 'D:\\': dRoot, 'D:\\Works': dWorks })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    const dDrive = await screen.findByRole('button', { name: 'D:\\' })
    await user.click(dDrive)
    expect(dDrive.className).toContain('folder-picker__item--selected')
    expect(mock.mock.calls).toHaveLength(1) // 单击未触发第二次加载

    await user.dblClick(dDrive)
    expect(await screen.findByRole('button', { name: 'Works' })).toBeTruthy()

    await user.dblClick(screen.getByRole('button', { name: 'Works' }))
    expect(await screen.findByText('此文件夹为空')).toBeTruthy()
    await waitFor(() =>
      expect(
        (screen.getByRole('button', { name: '选择当前文件夹' }) as HTMLButtonElement).disabled,
      ).toBe(false),
    )

    // 返回上级：D:\Works → D:\，再一次（D:\ 的 parent=""）回驱动器列表
    await user.click(screen.getByRole('button', { name: '返回上级' }))
    expect(await screen.findByRole('button', { name: 'Works' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '返回上级' }))
    expect(await screen.findByRole('button', { name: 'C:\\' })).toBeTruthy()
    expect(screen.getByText('此电脑')).toBeTruthy()
  })

  it('文件行展示元数据（日期/类型/大小）且双击不进入（只读）', async () => {
    const user = userEvent.setup()
    const mock = stubBrowse({ '': drives, 'D:\\': dRoot })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await user.dblClick(await screen.findByRole('button', { name: 'D:\\' }))
    const fileRow = await screen.findByRole('button', { name: 'readme.md' })
    expect(screen.getByText('2026/10/13 14:30')).toBeTruthy()
    expect(screen.getByText('MD 文件')).toBeTruthy()
    expect(screen.getByText('1.5 KB')).toBeTruthy()

    const calls = mock.mock.calls.length
    await user.dblClick(fileRow)
    expect(mock.mock.calls).toHaveLength(calls) // 文件不触发导航
  })

  it('列表渲染顺序为目录在前、文件在后（后端排序透传）', async () => {
    const user = userEvent.setup()
    stubBrowse({ '': drives, 'D:\\': dRoot })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await user.dblClick(await screen.findByRole('button', { name: 'D:\\' }))
    await screen.findByRole('button', { name: 'readme.md' })
    const names = Array.from(document.querySelectorAll('.folder-picker__item-name')).map(
      (n) => n.textContent,
    )
    expect(names).toEqual(['Works', 'readme.md'])
  })

  it('后退/前进沿历史栈导航', async () => {
    const user = userEvent.setup()
    stubBrowse({ '': drives, 'D:\\': dRoot, 'D:\\Works': dWorks })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await user.dblClick(await screen.findByRole('button', { name: 'D:\\' }))
    await user.dblClick(await screen.findByRole('button', { name: 'Works' }))
    expect(await screen.findByText('此文件夹为空')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '后退' }))
    expect(await screen.findByRole('button', { name: 'Works' })).toBeTruthy()
    expect((screen.getByRole('button', { name: '前进' }) as HTMLButtonElement).disabled).toBe(false)

    await user.click(screen.getByRole('button', { name: '前进' }))
    expect(await screen.findByText('此文件夹为空')).toBeTruthy()
  })

  it('面包屑点击跳转（点击「此电脑」回驱动器列表）', async () => {
    const user = userEvent.setup()
    stubBrowse({ '': drives, 'D:\\': dRoot, 'D:\\Works': dWorks })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await user.dblClick(await screen.findByRole('button', { name: 'D:\\' }))
    await user.dblClick(await screen.findByRole('button', { name: 'Works' }))
    expect(await screen.findByText('此文件夹为空')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '此电脑' }))
    expect(await screen.findByRole('button', { name: 'C:\\' })).toBeTruthy()
  })

  it('聚焦目录行按 Enter 进入（键盘操作）', async () => {
    const user = userEvent.setup()
    stubBrowse({ '': drives, 'D:\\': dRoot })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    const dDrive = await screen.findByRole('button', { name: 'D:\\' })
    dDrive.focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('button', { name: 'Works' })).toBeTruthy()
  })

  it('触屏（coarse pointer）单击目录即进入', async () => {
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

    expect(await screen.findByText('此文件夹为空')).toBeTruthy()
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

    expect(await screen.findByText('目录过大，仅显示部分项目')).toBeTruthy()
  })

  it('open=false 不渲染任何内容', () => {
    render(<FolderPickerModal open={false} initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('FolderPickerModal 格式工具', () => {
  it('formatSize 按 1024 进制格式化', () => {
    expect(formatSize(512)).toBe('512 B')
    expect(formatSize(1536)).toBe('1.5 KB')
    expect(formatSize(1048576)).toBe('1.0 MB')
    expect(formatSize(20 * 1024 * 1024)).toBe('20.0 MB')
  })

  it('formatDateTime 直接切分 ISO 字符串（不做时区转换）', () => {
    expect(formatDateTime('2026-10-13T14:30:00')).toBe('2026/10/13 14:30')
    expect(formatDateTime(null)).toBe('')
  })
})
