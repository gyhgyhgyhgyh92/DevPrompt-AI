import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ThinkingItem } from '../../schemas/stream'
import { ChatStream } from './ChatStream'

afterEach(cleanup)

type Props = Parameters<typeof ChatStream>[0]

function baseProps(overrides: Partial<Props> = {}): Props {
  return {
    state: 'DONE',
    status: 'done',
    sentence: '加个导出按钮',
    thinking: [],
    isThinking: false,
    message: '',
    questions: [],
    cleared: [],
    variants: [
      {
        title: '标准版',
        body: '请为列表页新增导出按钮：读取当前筛选结果，导出为 CSV。',
        level: 'B',
        changes: ['新增导出按钮'],
      },
    ],
    ranking: null,
    elapsedSeconds: null,
    errorMessage: null,
    isBusy: false,
    onSubmitAnswers: vi.fn(),
    onEscape: vi.fn(),
    onGuardrail: vi.fn(),
    ...overrides,
  }
}

describe('ChatStream 结构与阶段', () => {
  it('回复块含品牌标识、步骤时间轴与分隔线', () => {
    render(<ChatStream {...baseProps()} />)

    expect(screen.getByText('DevPrompt AI')).toBeTruthy()
    expect(document.querySelector('.chat-reply__phases')).not.toBeNull()
    expect(document.querySelector('.chat-reply__divider')).not.toBeNull()
  })

  it('步骤用中文展示，并给出每一步在做什么', () => {
    render(<ChatStream {...baseProps({ state: 'GENERATING', status: 'ask' })} />)

    const labels = Array.from(document.querySelectorAll('.chat-reply__phase-label')).map(
      (el) => el.textContent,
    )
    expect(labels).toEqual([
      '初始化',
      '检索代码',
      '研判信息',
      '等待确认',
      '整理答复',
      '生成方案',
      '评估推荐',
      '已完成',
      '已中止',
    ])
    expect(screen.getByText('一次调用产出 1~3 套方案')).toBeTruthy()
    expect(screen.getByText('进行中')).toBeTruthy()
  })

  it('每个阶段下方展示属于它的过程（文字段与工具卡片）', () => {
    const thinking: ThinkingItem[] = [
      { id: 't1', kind: 'text', text: '符号表就绪，共 12 个符号', phase: 'RETRIEVING' },
      {
        id: 'a1',
        kind: 'action',
        title: '检索符号',
        detail: 'rg -n Foo --glob src/a.ts',
        scope: '命中 2 行',
        phase: 'RETRIEVING',
      },
      { id: 't2', kind: 'text', text: '七项取证完成', phase: 'PROBING' },
    ]
    render(<ChatStream {...baseProps({ thinking, state: 'DONE' })} />)

    // 检索步骤下挂着文字与工具卡片
    expect(screen.getByText('符号表就绪，共 12 个符号')).toBeTruthy()
    expect(screen.getByText('检索符号')).toBeTruthy()
    expect(screen.getByText('命中 2 行')).toBeTruthy()
    // 研判步骤下挂着另一段
    expect(screen.getByText('七项取证完成')).toBeTruthy()

    const retrieving = Array.from(document.querySelectorAll('.chat-reply__phase'))[1]
    expect(retrieving?.textContent).toContain('符号表就绪')
    expect(retrieving?.textContent).toContain('检索符号')
  })

  it('无阶段标签的旧事件归到当前阶段，不会丢失', () => {
    const thinking: ThinkingItem[] = [{ id: 't1', kind: 'text', text: '旧格式过程', phase: '' }]
    render(<ChatStream {...baseProps({ thinking, state: 'DONE' })} />)

    expect(screen.getByText('旧格式过程')).toBeTruthy()
  })

  it('显示耗时', () => {
    render(<ChatStream {...baseProps({ elapsedSeconds: 42 })} />)
    expect(screen.getByText('耗时 42s')).toBeTruthy()
  })
})

describe('ChatStream 结果与反问', () => {
  it('结果态渲染方案正文，且不再有目标定位 / 取证事实 / 采纳操作栏 / 底部图标', () => {
    render(<ChatStream {...baseProps()} />)

    expect(screen.getByText(/导出为 CSV/)).toBeTruthy()
    expect(screen.queryByText('目标定位')).toBeNull()
    expect(screen.queryByText('取证事实')).toBeNull()
    expect(document.querySelector('.chat-suggestions')).toBeNull() // 采纳/编辑/跳过整行
    expect(document.querySelector('.chat-reply__actions')).toBeNull() // 底部图标行
    expect(screen.queryByText('由 AI 生成')).toBeNull()
  })

  it('思考中不渲染正文', () => {
    render(<ChatStream {...baseProps({ isThinking: true, status: null, state: 'RETRIEVING' })} />)

    expect(screen.queryByText(/导出为 CSV/)).toBeNull()
    expect(screen.queryByRole('button', { name: '提交' })).toBeNull()
  })

  it('反问态渲染问答面板并可提交', async () => {
    const onSubmitAnswers = vi.fn()
    render(
      <ChatStream
        {...baseProps({
          status: 'ask',
          state: 'ASKING',
          questions: [
            {
              key: 'scope',
              reason: '范围不明',
              best_guess: '',
              ask: '改动范围？',
              header: '范围',
              options: [{ label: '只改一处', description: '' }],
              multi_select: false,
            },
          ],
          onSubmitAnswers,
        })}
      />,
    )

    const user = userEvent.setup()
    expect(screen.getByText('需要你确认 1 个问题')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /只改一处/ }))
    await user.click(screen.getByRole('button', { name: '提交' }))

    expect(onSubmitAnswers).toHaveBeenCalledWith({ scope: '只改一处' })
  })

  it('错误文案可见', () => {
    render(<ChatStream {...baseProps({ errorMessage: '网络连接失败' })} />)
    expect(screen.getByText('网络连接失败')).toBeTruthy()
  })
})
