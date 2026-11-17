import { useEffect, useState } from 'react'

/**
 * 样张页的「假流式」：固定事件序列 + 定时器，形状照着真实 SSE 帧（phase / thought / action）。
 *
 * 不触网、不调 SSE 端点、不做任何评分或推荐判定（MUST-08）；三种呈现共用同一序列，
 * 保证对比公平。durationMs 在样张里是**虚构值**；真实链路的耗时由后端
 * `ActionInfo.duration_ms` 实测下发（2026-11-07 已落地），两者字段名一致便于对照。
 */

export type DemoPhase = 'RETRIEVING' | 'PROBING' | 'GENERATING' | 'RANKING' | 'DONE'

export interface DemoAction {
  kind: 'read' | 'command'
  target: string
  scope: string
  output: string
  durationMs: number
  status: 'ok' | 'failed'
}

/** 双语文案在 fixture 里成对出现，避免样张切语言时出现半中半英。 */
type Bilingual = readonly [zh: string, en: string]

export type DemoEvent =
  | { type: 'phase'; phase: DemoPhase }
  | { type: 'thought'; text: Bilingual }
  | { type: 'action'; action: DemoAction }

export interface DemoTick {
  delayMs: number
  event: DemoEvent
}

/** 13 拍、1x 约 11 秒：足够看清「阶段 → 动作 → 思考」的节奏，又不至于让人等。 */
export const DEMO_TICKS: readonly DemoTick[] = [
  { delayMs: 320, event: { type: 'phase', phase: 'RETRIEVING' } },
  {
    delayMs: 720,
    event: {
      type: 'thought',
      text: [
        '先定位 SSE 订阅与断流处理的落点，避免凭印象改。',
        'Locate the SSE subscription and disconnect handling before touching anything.',
      ],
    },
  },
  {
    delayMs: 760,
    event: {
      type: 'action',
      action: {
        kind: 'read',
        target: 'src/api/endpoints.ts',
        scope: 'L120-186',
        output: '',
        durationMs: 18,
        status: 'ok',
      },
    },
  },
  {
    delayMs: 640,
    event: {
      type: 'action',
      action: {
        kind: 'read',
        target: 'src/hooks/useSSE.ts',
        scope: 'L29-58',
        output: '',
        durationMs: 6,
        status: 'ok',
      },
    },
  },
  {
    delayMs: 980,
    event: {
      type: 'thought',
      text: [
        '终态帧已经主动 close；问题在 error 分支把「用户取消」与「连接异常」混为一谈。',
        'Terminal frames already close cleanly; the error branch conflates cancellation with transport failure.',
      ],
    },
  },
  { delayMs: 620, event: { type: 'phase', phase: 'PROBING' } },
  {
    delayMs: 900,
    event: {
      type: 'thought',
      text: [
        '还差两件事：是否允许改测试文件，以及重连次数上限取多少。',
        'Two unknowns left: may tests change, and what is the retry ceiling.',
      ],
    },
  },
  {
    delayMs: 820,
    event: {
      type: 'action',
      action: {
        kind: 'command',
        target: 'rg -n "setSseStatus" src/',
        scope: '',
        output: 'src/App.tsx:139\nsrc/hooks/useSSE.ts:37\nsrc/hooks/useSSE.ts:48',
        durationMs: 42,
        status: 'ok',
      },
    },
  },
  {
    delayMs: 1400,
    event: {
      type: 'action',
      action: {
        kind: 'command',
        target: 'pnpm vitest run src/hooks',
        scope: '',
        output: 'useSSE.test.ts (5 tests) 1.9s',
        durationMs: 2140,
        status: 'ok',
      },
    },
  },
  { delayMs: 680, event: { type: 'phase', phase: 'GENERATING' } },
  {
    delayMs: 900,
    event: {
      type: 'thought',
      text: [
        '按「最小改动 + 保留既有兜底」生成三套方案，不新增状态机态。',
        'Generate three plans: minimal diff, keep the existing fallback, no new state-machine state.',
      ],
    },
  },
  { delayMs: 640, event: { type: 'phase', phase: 'RANKING' } },
  { delayMs: 520, event: { type: 'phase', phase: 'DONE' } },
]

/** 已应用拍数对应的累计时间（秒，一位小数）：三种呈现共用同一计时口径。 */
export function elapsedAt(applied: number): string {
  const total = DEMO_TICKS.slice(0, Math.min(applied, DEMO_TICKS.length)).reduce(
    (sum, tick) => sum + tick.delayMs,
    0,
  )
  return `${(total / 1000).toFixed(1)}s`
}

export interface DemoThoughtView {
  id: number
  text: string
  /** 产生这条思考时所在的阶段（三种呈现都按阶段分组，故视图模型自带）。 */
  phase: DemoPhase
}

export interface DemoActionView extends DemoAction {
  id: number
  isRunning: boolean
  phase: DemoPhase
}

export interface DemoView {
  phase: DemoPhase
  thoughts: readonly DemoThoughtView[]
  actions: readonly DemoActionView[]
  isFinished: boolean
}

/** 把「已应用前 applied 拍」折叠成视图；纯函数，三种呈现共用。 */
export function deriveDemo(applied: number, locale: 'zh-CN' | 'en', isPlaying: boolean): DemoView {
  const isEn = locale === 'en'
  let phase: DemoPhase = 'RETRIEVING'
  const thoughts: DemoThoughtView[] = []
  const actions: DemoActionView[] = []

  for (let index = 0; index < Math.min(applied, DEMO_TICKS.length); index += 1) {
    const tick = DEMO_TICKS[index]
    if (tick === undefined) break
    const { event } = tick
    if (event.type === 'phase') phase = event.phase
    else if (event.type === 'thought') {
      thoughts.push({ id: index, text: isEn ? event.text[1] : event.text[0], phase })
    } else {
      actions.push({ ...event.action, id: index, isRunning: false, phase })
    }
  }

  // 最后一条动作在「播放中且后面还没有新事件」时视为运行中：这就是真实的时序感来源
  const lastAction = actions.at(-1)
  if (lastAction !== undefined && isPlaying && applied < DEMO_TICKS.length) {
    actions[actions.length - 1] = { ...lastAction, isRunning: true }
  }

  return {
    phase,
    thoughts,
    actions,
    isFinished: applied >= DEMO_TICKS.length,
  }
}

export interface DemoGroup {
  phase: DemoPhase
  thoughts: readonly DemoThoughtView[]
  actions: readonly DemoActionView[]
}

/** 按阶段分组（保持出现顺序）：阶段轨道与折叠摘要都要按「一步一组」渲染。 */
export function groupDemoByPhase(view: DemoView): DemoGroup[] {
  const order: DemoPhase[] = []
  const buckets = new Map<DemoPhase, { thoughts: DemoThoughtView[]; actions: DemoActionView[] }>()
  const items = [...view.thoughts, ...view.actions].sort((left, right) => left.id - right.id)
  for (const item of items) {
    const bucket = buckets.get(item.phase) ?? { thoughts: [], actions: [] }
    if (!buckets.has(item.phase)) {
      buckets.set(item.phase, bucket)
      order.push(item.phase)
    }
    if ('text' in item) bucket.thoughts.push(item)
    else bucket.actions.push(item)
  }
  return order.map((phase) => ({ phase, ...(buckets.get(phase) ?? { thoughts: [], actions: [] }) }))
}

export interface DemoPlayback {
  applied: number
  isPlaying: boolean
  play: () => void
  pause: () => void
  replay: () => void
}

/**
 * 自驱动的回放：每次只挂一个 setTimeout，effect cleanup 负责清理。
 * 因此暂停 / 换速度 / 卸载 / StrictMode 双挂载都不会留下重复计时器。
 */
export function useDemoPlayback(speed: number): DemoPlayback {
  const [applied, setApplied] = useState(0)
  const [isPlaying, setPlaying] = useState(false)

  useEffect(() => {
    if (!isPlaying) return undefined
    if (applied >= DEMO_TICKS.length) {
      setPlaying(false)
      return undefined
    }
    const tick = DEMO_TICKS[applied]
    if (tick === undefined) return undefined
    const timer = window.setTimeout(() => setApplied((count) => count + 1), tick.delayMs / speed)
    return () => window.clearTimeout(timer)
  }, [isPlaying, applied, speed])

  return {
    applied,
    isPlaying,
    play: () => {
      if (applied >= DEMO_TICKS.length) setApplied(0)
      setPlaying(true)
    },
    pause: () => setPlaying(false),
    replay: () => {
      setApplied(0)
      setPlaying(true)
    },
  }
}
