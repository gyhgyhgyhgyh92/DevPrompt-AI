import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RankingViewPayload, VariantPayload } from '../../api/types'
import { ChatStream } from './ChatStream'

afterEach(cleanup)

type ChatStreamProps = Parameters<typeof ChatStream>[0]

const variantsThree: VariantPayload[] = [
  { title: '保守方案', body: 'body-A', level: 'A', changes: ['改一'] },
  { title: '标准方案', body: 'body-B', level: 'B', changes: ['改二'] },
  { title: '激进方案', body: 'body-C', level: 'C', changes: ['改三'] },
]

const rankingMarked: RankingViewPayload = {
  variant: 'B',
  gap: 0.25,
  confidence: 0.9,
  marked: true,
  reason: '分差明显',
  fit: 0.8,
  pref: 0.7,
  total: 0.75,
}

function baseProps(overrides: Partial<ChatStreamProps> = {}): ChatStreamProps {
  return {
    state: 'DONE',
    status: 'done',
    sentence: '加个导出按钮',
    message: '',
    questions: [],
    cleared: [],
    variants: variantsThree,
    ranking: rankingMarked,
    target: null,
    facts: [],
    elapsedSeconds: 3,
    errorMessage: null,
    isBusy: false,
    canRetry: true,
    onSubmitAnswers: vi.fn(),
    onEscape: vi.fn(),
    onGuardrail: vi.fn(),
    onAdopt: vi.fn(),
    onEditAdopt: vi.fn(),
    onSkip: vi.fn(),
    onThumb: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  }
}

function renderChat(overrides: Partial<ChatStreamProps> = {}) {
  const props = baseProps(overrides)
  render(<ChatStream {...props} />)
  return props
}

describe('ChatStream 用户气泡与回复块结构', () => {
  it('渲染右对齐用户气泡（原句内容 + chat-user-bubble 类）', () => {
    renderChat()

    const bubble = screen.getByText('加个导出按钮')
    expect(bubble.className).toContain('chat-user-bubble')
    expect(bubble.closest('.chat-stream__row--user')).not.toBeNull()
  })

  it('无原句时不渲染用户气泡（恢复的旧会话）', () => {
    renderChat({ sentence: '' })

    expect(document.querySelector('.chat-user-bubble')).toBeNull()
    expect(screen.getByRole('article', { name: 'AI 回复' })).toBeTruthy()
  })

  it('回复块含品牌标识、状态折叠行与分隔线', () => {
    renderChat()

    expect(screen.getByText('DevPrompt AI')).toBeTruthy()
    expect(screen.getByRole('button', { name: /状态/ })).toBeTruthy()
    expect(screen.getByText('DONE')).toBeTruthy()
    expect(document.querySelector('.chat-reply__divider')).not.toBeNull()
  })
})

describe('ChatStream 状态 / 耗时折叠行', () => {
  it('点击折叠行展开阶段列表（aria-expanded 切换）', async () => {
    const user = userEvent.setup()
    renderChat()

    const toggle = screen.getByRole('button', { name: /状态/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByRole('list', { name: '流程阶段' })).toBeNull()

    await user.click(toggle)

    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByRole('list', { name: '流程阶段' })).toBeTruthy()
  })

  it('有计时时显示耗时秒数，无计时时仅显状态', () => {
    renderChat({ elapsedSeconds: 12 })
    expect(screen.getByText('耗时 12s')).toBeTruthy()

    cleanup()

    renderChat({ elapsedSeconds: null })
    expect(screen.queryByText(/耗时/)).toBeNull()
    expect(screen.getByText('DONE')).toBeTruthy()
  })
})

/** 操作栏图标组容器（卡内亦有「复制」按钮，故按容器定位以消歧）。 */
function actionBar(): HTMLElement {
  const node = document.querySelector('.chat-reply__actions')
  if (node === null) throw new Error('缺少操作栏')
  return node as HTMLElement
}

describe('ChatStream 操作栏', () => {
  it('渲染 复制/重试/赞/踩 图标按钮与「由 AI 生成」', () => {
    renderChat()

    const bar = within(actionBar())
    expect(bar.getByRole('button', { name: '复制' })).toBeTruthy()
    expect(bar.getByRole('button', { name: '重试' })).toBeTruthy()
    expect(bar.getByRole('button', { name: '赞' })).toBeTruthy()
    expect(bar.getByRole('button', { name: '踩' })).toBeTruthy()
    expect(screen.getByText('由 AI 生成')).toBeTruthy()
  })

  it('复制把当前会话全部方案正文写入剪贴板', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderChat()

    await user.click(within(actionBar()).getByRole('button', { name: '复制' }))

    expect(writeText).toHaveBeenCalledWith('body-A\n\nbody-B\n\nbody-C')
  })

  it('重试触发重跑；无原句/项目时禁用', async () => {
    const user = userEvent.setup()
    const props = renderChat()

    await user.click(within(actionBar()).getByRole('button', { name: '重试' }))
    expect(props.onRetry).toHaveBeenCalledTimes(1)

    cleanup()

    renderChat({ canRetry: false })
    const retry = within(actionBar()).getByRole('button', { name: '重试' }) as HTMLButtonElement
    expect(retry.disabled).toBe(true)
  })

  it('赞/踩映射操作栏反馈', async () => {
    const user = userEvent.setup()
    const props = renderChat()

    await user.click(within(actionBar()).getByRole('button', { name: '赞' }))
    await user.click(within(actionBar()).getByRole('button', { name: '踩' }))

    expect(props.onThumb).toHaveBeenNthCalledWith(1, true)
    expect(props.onThumb).toHaveBeenNthCalledWith(2, false)
  })
})

describe('ChatStream 建议胶囊与方案嵌入', () => {
  it('DONE 态渲染 采纳 A/B/C + 编辑后采纳 + 跳过 胶囊并各自触发回调', async () => {
    const user = userEvent.setup()
    const props = renderChat()

    await user.click(screen.getByRole('button', { name: /采纳 B/ }))
    await user.click(screen.getByRole('button', { name: /编辑后采纳/ }))
    await user.click(screen.getByRole('button', { name: /跳过/ }))

    expect(props.onAdopt).toHaveBeenCalledWith('B')
    expect(props.onEditAdopt).toHaveBeenCalledTimes(1)
    expect(props.onSkip).toHaveBeenCalledTimes(1)
  })

  it('方案组嵌入正文：三卡 + 命中档位推荐徽章', () => {
    renderChat()

    expect(screen.getByRole('article', { name: '方案 A' })).toBeTruthy()
    expect(screen.getByRole('article', { name: '方案 B' })).toBeTruthy()
    expect(screen.getByRole('article', { name: '方案 C' })).toBeTruthy()
    expect(screen.getByText(/【推荐】B/)).toBeTruthy()
  })

  it('未标记推荐时由 ConfidenceNotice 呈现后端 reason（不静默）', () => {
    renderChat({
      ranking: { ...rankingMarked, marked: false, reason: '三套适配度接近，建议人工选择' },
    })

    expect(screen.getByText('三套适配度接近，建议人工选择')).toBeTruthy()
    expect(screen.queryByText(/【推荐】/)).toBeNull()
  })

  it('MUST-28 单套无 ranking：仅 A 卡，无推荐徽章/评分明细，提示人工选择', () => {
    renderChat({
      variants: [{ title: '保守方案', body: 'body-A', level: 'A', changes: [] }],
      ranking: null,
    })

    expect(screen.getByRole('article', { name: '方案 A' })).toBeTruthy()
    expect(screen.queryByRole('article', { name: '方案 B' })).toBeNull()
    expect(screen.queryByText(/【推荐】/)).toBeNull()
    expect(screen.queryByText('评分明细')).toBeNull()
    expect(screen.getByText('后端未产生推荐视图，请人工选择')).toBeTruthy()
  })
})

describe('ChatStream 追问与上下文', () => {
  it('追问态以回复块形式呈现澄清卡与逃生按钮', () => {
    renderChat({
      state: 'ASKING',
      status: 'ask',
      variants: [],
      ranking: null,
      questions: [{ key: 'target', reason: '缺目标定位', best_guess: 'build()', ask: '改哪里？' }],
      cleared: ['lang'],
    })

    expect(screen.getByText('缺目标定位')).toBeTruthy()
    expect(screen.getByRole('button', { name: '提交答复' })).toBeTruthy()
    expect(screen.getByRole('button', { name: /直接生成（A 保守版/ })).toBeTruthy()
  })

  it('上下文信息内嵌小节渲染目标定位与取证事实', () => {
    renderChat({
      target: { name: 'build', path: 'src/app.py', line: 12 },
      facts: [{ key: 'fact_a', passed: true, evidence: '定位到 build' }],
    })

    const panel = screen.getByRole('region', { name: '上下文信息' })
    expect(within(panel).getByText('build@src/app.py:12')).toBeTruthy()
    expect(within(panel).getByText('fact_a')).toBeTruthy()
    expect(within(panel).getByText('定位到 build')).toBeTruthy()
  })
})
