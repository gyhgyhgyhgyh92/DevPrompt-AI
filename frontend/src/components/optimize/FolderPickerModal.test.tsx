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
  /** 搜索结果专用：相对基准目录的父路径（直接子级为 ''）；普通列举省略 → null。 */
  rel_parent?: string | null
}

interface ListingSpec {
  path: string
  parent: string | null
  entries: EntrySpec[]
  truncated?: boolean
}

/** 按 (?path=, ?q=) 分流的 browse stub：无 q → key=`path`（普通列举）；
 *  有 q → key=`path|q`（当前目录子树递归搜索）；'' 键为驱动器列表；未配置回 2001 业务错误。 */
function stubBrowse(listings: Record<string, ListingSpec>) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const pathMatch = /[?&]path=([^&]*)/.exec(url)
    const path = pathMatch !== null ? decodeURIComponent(pathMatch[1] as string) : ''
    const qMatch = /[?&]q=([^&]*)/.exec(url)
    const query = qMatch !== null ? decodeURIComponent(qMatch[1] as string) : ''
    const key = query === '' ? path : `${path}|${query}`
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
              rel_parent: e.rel_parent ?? null,
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

/** 搜索 D:\ 子树命中「works」：一条直接子级（rel_parent=''）+ 一条更深层（rel_parent='Backup'）。 */
const dRootSearchWorks: ListingSpec = {
  path: 'D:\\',
  parent: '',
  entries: [
    { name: 'Works', path: 'D:\\Works', rel_parent: '' },
    { name: 'WorksOld', path: 'D:\\Backup\\WorksOld', rel_parent: 'Backup' },
  ],
}

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

describe('FolderPickerModal 搜索（图二，2026-10-13）', () => {
  it('驱动器列表态搜索输入禁用', async () => {
    stubBrowse({ '': drives })
    render(<FolderPickerModal open initialPath="" onSelect={vi.fn()} onClose={vi.fn()} />)

    await screen.findByRole('button', { name: 'C:\\' })
    expect(
      (screen.getByRole('textbox', { name: '搜索当前文件夹' }) as HTMLInputElement).disabled,
    ).toBe(true)
  })

  it('输入后防抖触发带 q 的递归请求并渲染结果（含相对路径提示）', async () => {
    const user = userEvent.setup()
    const mock = stubBrowse({ 'D:\\': dRoot, 'D:\\|works': dRootSearchWorks })
    render(<FolderPickerModal open initialPath={'D:\\'} onSelect={vi.fn()} onClose={vi.fn()} />)

    await screen.findByRole('button', { name: 'Works' })
    await user.type(screen.getByRole('textbox', { name: '搜索当前文件夹' }), 'works')

    await waitFor(() =>
      expect(mock.mock.calls.some(([input]) => String(input).includes('q=works'))).toBe(true),
    )
    await screen.findByRole('button', { name: 'WorksOld' })
    expect(screen.getByText('2 个搜索结果')).toBeTruthy()
    // 仅更深层结果（rel_parent='Backup'）显示相对路径提示；直接子级（''）不显示
    const rels = document.querySelectorAll('.folder-picker__item-rel')
    expect(rels).toHaveLength(1)
    expect(rels[0]?.textContent).toBe('Backup')
  })

  it('无命中显示「未找到匹配的文件夹」', async () => {
    const user = userEvent.setup()
    stubBrowse({ 'D:\\': dRoot, 'D:\\|zzz': { path: 'D:\\', parent: '', entries: [] } })
    render(<FolderPickerModal open initialPath={'D:\\'} onSelect={vi.fn()} onClose={vi.fn()} />)

    await screen.findByRole('button', { name: 'Works' })
    await user.type(screen.getByRole('textbox', { name: '搜索当前文件夹' }), 'zzz')

    expect(await screen.findByText('未找到匹配的文件夹')).toBeTruthy()
  })

  it('清除搜索恢复普通列表（恢复请求不再带 q，且仅新增一次）', async () => {
    const user = userEvent.setup()
    const mock = stubBrowse({ 'D:\\': dRoot, 'D:\\|works': dRootSearchWorks })
    render(<FolderPickerModal open initialPath={'D:\\'} onSelect={vi.fn()} onClose={vi.fn()} />)

    await screen.findByRole('button', { name: 'Works' })
    await user.type(screen.getByRole('textbox', { name: '搜索当前文件夹' }), 'works')
    await screen.findByRole('button', { name: 'WorksOld' })

    const callsBeforeClear = mock.mock.calls.length
    await user.click(screen.getByRole('button', { name: '清除搜索' }))

    await screen.findByRole('button', { name: 'Archive' })
    expect(screen.queryByRole('button', { name: 'WorksOld' })).toBeNull()
    expect(String(mock.mock.calls[callsBeforeClear]?.[0])).not.toContain('q=')
    expect(mock.mock.calls).toHaveLength(callsBeforeClear + 1)
  })

  it('双击搜索结果进入该目录并退出搜索（搜索框清空）', async () => {
    const user = userEvent.setup()
    stubBrowse({ 'D:\\': dRoot, 'D:\\|works': dRootSearchWorks, 'D:\\Works': dWorks })
    render(<FolderPickerModal open initialPath={'D:\\'} onSelect={vi.fn()} onClose={vi.fn()} />)

    await screen.findByRole('button', { name: 'Works' })
    await user.type(screen.getByRole('textbox', { name: '搜索当前文件夹' }), 'works')
    await screen.findByRole('button', { name: 'WorksOld' })

    await user.dblClick(screen.getByRole('button', { name: 'Works' }))

    expect(await screen.findByText('此文件夹下没有子文件夹')).toBeTruthy()
    expect(
      (screen.getByRole('textbox', { name: '搜索当前文件夹' }) as HTMLInputElement).value,
    ).toBe('')
  })

  it('搜索框 Esc 清空查询（stopPropagation，不关闭模态）', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    stubBrowse({ 'D:\\': dRoot, 'D:\\|works': dRootSearchWorks })
    render(<FolderPickerModal open initialPath={'D:\\'} onSelect={vi.fn()} onClose={onClose} />)

    await screen.findByRole('button', { name: 'Works' })
    const input = screen.getByRole('textbox', { name: '搜索当前文件夹' })
    await user.type(input, 'works')
    await screen.findByRole('button', { name: 'WorksOld' })

    await user.type(input, '{Escape}')

    await waitFor(() =>
      expect(
        (screen.getByRole('textbox', { name: '搜索当前文件夹' }) as HTMLInputElement).value,
      ).toBe(''),
    )
    expect(onClose).not.toHaveBeenCalled()
  })

  it('搜索态 truncated 显示「结果过多，仅显示前 500 项」', async () => {
    const user = userEvent.setup()
    stubBrowse({ 'D:\\': dRoot, 'D:\\|works': { ...dRootSearchWorks, truncated: true } })
    render(<FolderPickerModal open initialPath={'D:\\'} onSelect={vi.fn()} onClose={vi.fn()} />)

    await screen.findByRole('button', { name: 'Works' })
    await user.type(screen.getByRole('textbox', { name: '搜索当前文件夹' }), 'works')

    expect(await screen.findByText('结果过多，仅显示前 500 项')).toBeTruthy()
  })
})

describe('FolderPickerModal 格式工具', () => {
  it('formatDateTime 直接切分 ISO 字符串（不做时区转换）', () => {
    expect(formatDateTime('2026-10-13T14:30:00')).toBe('2026/10/13 14:30')
    expect(formatDateTime(null)).toBe('')
  })
})
