import { act, cleanup, render, screen } from '@testing-library/react'
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
    replyText: '',
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
    deliveryGate: null,
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
    render(
      <ChatStream
        {...baseProps({
          state: 'GENERATING',
          status: 'ask',
          cleared: ['scope'],
          variants: [
            { title: '保守版', body: 'body-A', level: 'A', changes: [] },
            { title: '标准版', body: 'body-B', level: 'B', changes: [] },
          ],
        })}
      />,
    )

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
    ])
    expect(screen.getByText('一次调用产出 1~3 套方案')).toBeTruthy()
    expect(screen.getByText('进行中')).toBeTruthy()
  })

  it('无信息缺口时不渲染「等待确认 / 整理答复」，研判步骤给出无需补充的结论', () => {
    render(<ChatStream {...baseProps({ state: 'GENERATING', status: null, isThinking: true })} />)

    const labels = Array.from(document.querySelectorAll('.chat-reply__phase-label')).map(
      (el) => el.textContent,
    )
    expect(labels).not.toContain('等待确认')
    expect(labels).not.toContain('整理答复')
    expect(labels).not.toContain('已中止')
    expect(screen.getByText('七项取证完成，未发现需要确认的缺口')).toBeTruthy()
  })

  it('单套方案跳过打分时不渲染「评估推荐」', () => {
    render(<ChatStream {...baseProps({ state: 'DONE', isThinking: true })} />)

    const labels = Array.from(document.querySelectorAll('.chat-reply__phase-label')).map(
      (el) => el.textContent,
    )
    expect(labels).toContain('生成方案')
    expect(labels).not.toContain('评估推荐')
  })

  it('中止时才出现「已中止」这一步', () => {
    render(<ChatStream {...baseProps({ state: 'ABORTED', status: 'aborted', isThinking: true })} />)

    const labels = Array.from(document.querySelectorAll('.chat-reply__phase-label')).map(
      (el) => el.textContent,
    )
    expect(labels).toContain('已中止')
  })

  it('每个阶段下方展示思考块与动作行，可展开命令与输出', async () => {
    const thinking: ThinkingItem[] = [
      { id: 't1', kind: 'text', text: '符号表就绪，共 12 个符号', phase: 'RETRIEVING' },
      {
        id: 'a1',
        kind: 'action',
        title: '检索符号',
        detail: 'rg -n Foo --glob src/a.ts',
        scope: '命中 2 行',
        output: 'src/a.ts:1:Foo',
        phase: 'RETRIEVING',
      },
      { id: 't2', kind: 'text', text: '七项取证完成', phase: 'PROBING' },
    ]
    render(<ChatStream {...baseProps({ thinking, state: 'DONE', isThinking: true })} />)

    // 思考文字在灰底块内，动作渲染为「命令已执行」
    expect(screen.getByText('符号表就绪，共 12 个符号')).toBeTruthy()
    expect(screen.getByText('七项取证完成')).toBeTruthy()
    expect(screen.getByText('命令已执行')).toBeTruthy()
    expect(screen.getByText('命中 2 行')).toBeTruthy()

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /命令已执行/ }))

    expect(screen.getByText('rg -n Foo --glob src/a.ts')).toBeTruthy()
    expect(screen.getByText('src/a.ts:1:Foo')).toBeTruthy()
  })

  it('读取文件的动作显示「已读取」且展开只显示内容', async () => {
    const thinking: ThinkingItem[] = [
      {
        id: 'a1',
        kind: 'action',
        title: '读取文件',
        detail: 'src/ui/Button.tsx',
        scope: 'L1-20',
        output: 'line1\nline2',
        phase: 'PROBING',
      },
    ]
    render(<ChatStream {...baseProps({ thinking, state: 'DONE', isThinking: true })} />)

    expect(screen.getByText('已读取 src/ui/Button.tsx')).toBeTruthy()
    await userEvent.setup().click(screen.getByRole('button', { name: /已读取/ }))
    expect(document.querySelector('.trace-step__code--output')?.textContent).toBe('line1\nline2')
  })

  it('输出为空时不渲染输出块', async () => {
    const thinking: ThinkingItem[] = [
      {
        id: 'a1',
        kind: 'action',
        title: '检索符号',
        detail: 'rg -n Foo',
        scope: '无匹配',
        output: '',
        phase: 'RETRIEVING',
      },
    ]
    render(<ChatStream {...baseProps({ thinking, state: 'DONE', isThinking: true })} />)

    await userEvent.setup().click(screen.getByRole('button', { name: /命令已执行/ }))
    expect(document.querySelectorAll('.trace-step__code--output')).toHaveLength(0)
  })

  it('思考静默 1.5 秒后提示「正在规划下一步」', () => {
    vi.useFakeTimers()
    render(<ChatStream {...baseProps({ isThinking: true, status: null, state: 'RETRIEVING' })} />)

    expect(screen.queryByText('正在规划下一步')).toBeNull()
    act(() => {
      vi.advanceTimersByTime(1600)
    })
    expect(screen.getByText('正在规划下一步')).toBeTruthy()

    vi.useRealTimers()
  })

  it('无阶段标签的旧事件归到当前阶段，不会丢失', () => {
    const thinking: ThinkingItem[] = [{ id: 't1', kind: 'text', text: '旧格式过程', phase: '' }]
    render(<ChatStream {...baseProps({ thinking, state: 'DONE', isThinking: true })} />)

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

  it('结束后过程整组收成摘要行，点击展开回看（2026-11-04）', async () => {
    const user = userEvent.setup()
    const thinking: ThinkingItem[] = [
      { id: 't1', kind: 'text', text: '符号表就绪', phase: 'RETRIEVING' },
      {
        id: 'a1',
        kind: 'action',
        title: '检索符号',
        detail: 'rg -n Foo',
        scope: '命中 2 行',
        output: 'src/a.ts:1:Foo',
        status: 'ok',
        phase: 'RETRIEVING',
      },
    ]
    render(<ChatStream {...baseProps({ thinking, state: 'DONE', elapsedSeconds: 12 })} />)

    // 收起：阶段列表与过程都不渲染，只留一行摘要
    expect(document.querySelector('.chat-reply__phases')).toBeNull()
    expect(screen.queryByText('符号表就绪')).toBeNull()
    expect(screen.getByText(/思考 12s · 1 个动作 · 1 个步骤/)).toBeTruthy()

    await user.click(screen.getByRole('button', { name: /思考 12s/ }))

    expect(document.querySelector('.chat-reply__phases')).not.toBeNull()
    expect(screen.getByText('符号表就绪')).toBeTruthy()
  })

  it('进行中不折叠过程，也没有摘要行', () => {
    const thinking: ThinkingItem[] = [
      { id: 't1', kind: 'text', text: '符号表就绪', phase: 'RETRIEVING' },
    ]
    render(
      <ChatStream {...baseProps({ thinking, state: 'PROBING', status: null, isThinking: true })} />,
    )

    expect(document.querySelector('.chat-reply__phases')).not.toBeNull()
    expect(document.querySelector('.chat-reply__process-toggle')).toBeNull()
  })

  it('失败动作按错误色渲染并带出退出码（2026-11-04）', () => {
    const thinking: ThinkingItem[] = [
      {
        id: 'a1',
        kind: 'action',
        title: '检索符号',
        detail: 'rg -n Foo --glob src',
        scope: 'Exit code 1',
        output: 'rg: no such file',
        status: 'failed',
        phase: 'RETRIEVING',
      },
    ]
    render(
      <ChatStream {...baseProps({ thinking, state: 'PROBING', status: null, isThinking: true })} />,
    )

    expect(screen.getByText('命令失败 · Exit code 1')).toBeTruthy()
    expect(document.querySelector('.trace-step--failed')).not.toBeNull()
  })
})
