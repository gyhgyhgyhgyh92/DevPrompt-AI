import { useSettingsStore } from '../stores/useSettingsStore'
import type {
  LabPaletteId,
  LabStartComposition,
  LabStreamVariant,
  LabStyleId,
  LabThemeMode,
  LabToolForm,
} from './types'

/**
 * 样张页文案（zh / en）。
 *
 * 为什么不进 `i18n/locales/*.json`：lab 是 dev-only chunk，四十余条只服务于样张的文案
 * 塞进生产语言包会让正式包变大；同时 `i18n/jsxScan.test.ts` 禁止 .tsx 里出现中文文本节点，
 * 因此所有中文集中在本文（.ts 不参与该扫描）。
 */
export interface LabCopy {
  brand: string
  name: string
  intro: string
  hint: string
  controls: {
    style: string
    palette: string
    theme: string
    variant: string
    composition: string
    play: string
    pause: string
    replay: string
    speed: string
  }
  themes: Record<LabThemeMode, string>
  styles: Record<LabStyleId, { name: string; tagline: string; use: string }>
  palettes: Record<LabPaletteId, { name: string; note: string }>
  variants: Record<LabStreamVariant, { name: string; note: string }>
  compositions: Record<LabStartComposition, string>
  sections: {
    start: string
    thread: string
    stream: string
    tools: string
    sidebar: string
    palette: string
  }
  sectionHints: {
    start: string
    thread: string
    stream: string
    tools: string
    sidebar: string
    palette: string
  }
  start: {
    headA: string
    subA: string
    headB: string
    subB: string
    chips: readonly string[]
    placeholder: string
    folder: string
    send: string
    recent: string
    recentItems: readonly string[]
  }
  thread: {
    user: string
    elapsed: string
    answerTitle: string
    answer: string
    plans: readonly string[]
    recommend: string
    planLevels: readonly string[]
    stop: string
    composerHint: string
  }
  stream: {
    phase: Record<'RETRIEVING' | 'PROBING' | 'GENERATING' | 'RANKING' | 'DONE', string>
    running: string
    done: string
    failed: string
    digest: string
    digestTail: string
    empty: string
    actions: string
    steps: string
    summary: string
  }
  tools: {
    forms: Record<LabToolForm, string>
    formHints: Record<LabToolForm, string>
    read: string
    command: string
    output: string
    exitOk: string
    exitFailed: string
    expand: string
    collapse: string
  }
  sidebar: {
    label: string
    newSession: string
    pinned: string
    today: string
    earlier: string
    items: readonly string[]
    history: string
  }
  palette: {
    pair: string
    usage: string
    ratio: string
    rows: readonly string[]
    note: string
  }
  footer: string
}

const ZH: LabCopy = {
  brand: 'DevPrompt AI',
  name: 'Style Lab',
  intro: '同一份内容，三种视觉语言与三种流式呈现。选定风格与配色后进入全量落地。',
  hint: '本页仅开发环境可见，不进入生产构建。',
  controls: {
    style: '风格',
    palette: '配色',
    theme: '主题',
    variant: '流式变体',
    composition: '启动页构图',
    play: '播放',
    pause: '暂停',
    replay: '重放',
    speed: '速度',
  },
  themes: { light: '浅色', dark: '深色', system: '跟随系统' },
  styles: {
    blueprint: {
      name: '工程图纸',
      tagline: '发丝描边 · 零阴影 · 等宽微型标签',
      use: '评审、审计、长时间阅读',
    },
    terminal: {
      name: '终端工具',
      tagline: '三层暗面 · 紧凑行高 · 状态词优先',
      use: '写代码、跑命令、盯执行',
    },
    soft: {
      name: '柔和层叠',
      tagline: '暖纸底 · 双层投影 · 呼吸留白',
      use: '长时间对话、非工程读者',
    },
  },
  palettes: {
    signal: { name: '信号绿', note: '沿用品牌绿，只出现在状态与动作上' },
    graphite: { name: '石墨靛蓝', note: '中性界面 + 冷静强调，最像专业工具' },
    amber: { name: '墨黑琥珀', note: '暖色警示感，贴近执行日志气质' },
  },
  variants: {
    typewriter: { name: '打字机', note: '逐字出现 + 光标，强调「正在想」' },
    rail: { name: '阶段轨道', note: '每个动作一行，带耗时与结果摘要' },
    digest: { name: '折叠摘要', note: '思考中只占一行，结束展开' },
  },
  compositions: { centered: '居中主张', split: '左题右输入' },
  sections: {
    start: '01 · 启动页',
    thread: '02 · 对话线程',
    stream: '03 · 流式呈现',
    tools: '04 · 工具卡三形态',
    sidebar: '05 · 侧边栏',
    palette: '06 · 配色与对比度',
  },
  sectionHints: {
    start: '三种风格并列，同一份文案与控件',
    thread: '用户气泡 / 助手块 / 阶段账本 / 方案摘要',
    stream: '同一段事件序列，三种密度；上方切换风格',
    tools: '行内胶囊 · 信息卡 · 终端块，覆盖运行中与失败',
    sidebar: '项目分组、选中态、置顶、悬浮操作',
    palette: '强调色族 × 中性表面，附实测对比度',
  },
  start: {
    headA: '把一句模糊需求，变成 Agent 能直接执行的提示词',
    subA: '先读真实代码，再问关键未知，最后给三套方案与推荐理由。',
    headB: 'Prompt 工作台',
    subB: '选一个项目，写下你要改的事；剩余交给检索与研判。',
    chips: ['代码检索', '澄清追问', '三案对比'],
    placeholder: '例如：把 SSE 断流处理改成可恢复的，并补测试',
    folder: 'devprompt-ai',
    send: '发送',
    recent: '最近项目',
    recentItems: ['devprompt-ai', 'prompt-optimizer', 'web-console'],
  },
  thread: {
    user: '把 SSE 断流处理改成可恢复的，并补测试',
    elapsed: '12.4s',
    answerTitle: '结论',
    answer:
      '终态帧已经主动 close，问题在 error 分支把「用户取消」和「连接异常」混在一起。建议按事件来源分流，保留手动重连入口，不自动重连。',
    plans: ['最小修复：区分取消与断流', '可恢复：断流后按退避重连一次', '重构：抽出连接状态机'],
    recommend: '推荐',
    planLevels: ['A 保守', 'B 标准', 'C 激进'],
    stop: '停止生成',
    composerHint: '在同一会话里继续追问',
  },
  stream: {
    phase: {
      RETRIEVING: '检索代码',
      PROBING: '研判未知',
      GENERATING: '生成方案',
      RANKING: '评估推荐',
      DONE: '完成',
    },
    running: '运行中',
    done: '完成',
    failed: '失败',
    digest: '检索代码 · 3 个动作 · 12s',
    digestTail: '已折叠过程，点击展开',
    empty: '事件序列尚未开始',
    actions: '个动作',
    steps: '步',
    summary: '过程摘要',
  },
  tools: {
    forms: { pill: '行内胶囊', card: '信息卡', terminal: '终端块' },
    formHints: {
      pill: '最省空间，适合连续同类动作',
      card: '默认形态，带耗时与可展开输出',
      terminal: '命令类动作，保留提示符与退出码',
    },
    read: '读取',
    command: '命令',
    output: '输出',
    exitOk: 'exit 0',
    exitFailed: 'exit 1',
    expand: '展开',
    collapse: '收起',
  },
  sidebar: {
    label: '会话',
    newSession: '新建会话',
    pinned: '置顶',
    today: '今天',
    earlier: '更早',
    items: ['SSE 断流处理', '提示词评分阈值', '侧边栏收纳交互', '模型目录刷新'],
    history: '全部历史',
  },
  palette: {
    pair: '组合',
    usage: '用途',
    ratio: '对比度',
    rows: ['正文 / 画布', '次级 / 画布', '辅助 / 画布', '强调 / 画布', '深字 / 强调底'],
    note: '强调色不承担小字正文：11–13px 文本一律用 ink 或 primary-900。信号绿在浅色画布上低于 UI 元件 3:1 要求（见「强调 / 画布」行），要么降到 700 档，要么只用于大面积色块。',
  },
  footer: '本轮只交付样张。选定「风格 + 配色 + 流式变体」后再进入全量落地。',
}

const EN: LabCopy = {
  brand: 'DevPrompt AI',
  name: 'Style Lab',
  intro:
    'One set of content, three visual languages and three streaming treatments. Pick a style and palette to ship.',
  hint: 'Development only. Never bundled into production.',
  controls: {
    style: 'Style',
    palette: 'Palette',
    theme: 'Theme',
    variant: 'Stream variant',
    composition: 'Start composition',
    play: 'Play',
    pause: 'Pause',
    replay: 'Replay',
    speed: 'Speed',
  },
  themes: { light: 'Light', dark: 'Dark', system: 'System' },
  styles: {
    blueprint: {
      name: 'Blueprint',
      tagline: 'Hairline borders · no shadows · mono micro-labels',
      use: 'Review, audit, long reading',
    },
    terminal: {
      name: 'Terminal Pro',
      tagline: 'Three dark layers · tight rows · status words first',
      use: 'Coding, commands, watching runs',
    },
    soft: {
      name: 'Soft Stack',
      tagline: 'Warm paper · double shadow · breathing space',
      use: 'Long chats, non-engineer readers',
    },
  },
  palettes: {
    signal: { name: 'Signal green', note: 'Brand green kept, limited to state and action' },
    graphite: { name: 'Graphite indigo', note: 'Neutral UI with one calm accent' },
    amber: { name: 'Ink amber', note: 'Warm warning tone, close to a run log' },
  },
  variants: {
    typewriter: { name: 'Typewriter', note: 'Character-by-character with a caret' },
    rail: { name: 'Phase rail', note: 'One row per action, duration and result' },
    digest: { name: 'Folded digest', note: 'One line while thinking, expands at the end' },
  },
  compositions: { centered: 'Centered claim', split: 'Title + composer' },
  sections: {
    start: '01 · Start page',
    thread: '02 · Chat thread',
    stream: '03 · Streaming',
    tools: '04 · Tool cards',
    sidebar: '05 · Sidebar',
    palette: '06 · Palette & contrast',
  },
  sectionHints: {
    start: 'Three styles side by side, same copy and controls',
    thread: 'User bubble / assistant block / phase ledger / plans',
    stream: 'Same event sequence, three densities; style above',
    tools: 'Inline pill · info card · terminal block, with running and failed',
    sidebar: 'Project groups, selection, pin, hover actions',
    palette: 'Accent family × neutral surfaces, with measured contrast',
  },
  start: {
    headA: 'Turn a vague sentence into a prompt an agent can run',
    subA: 'Read real code first, ask only the unknowns, then propose three plans with reasons.',
    headB: 'Prompt workbench',
    subB: 'Pick a project, describe the change; retrieval and probing handle the rest.',
    chips: ['Code retrieval', 'Clarifying questions', 'Three plans'],
    placeholder: 'e.g. make SSE disconnects recoverable and add tests',
    folder: 'devprompt-ai',
    send: 'Send',
    recent: 'Recent projects',
    recentItems: ['devprompt-ai', 'prompt-optimizer', 'web-console'],
  },
  thread: {
    user: 'Make SSE disconnects recoverable and add tests',
    elapsed: '12.4s',
    answerTitle: 'Conclusion',
    answer:
      'Terminal frames already close cleanly; the error branch conflates user cancellation with transport failure. Split the two, keep a manual reconnect, never auto-retry.',
    plans: [
      'Minimal: split cancel vs. drop',
      'Recoverable: one backed-off retry',
      'Refactor: connection state machine',
    ],
    recommend: 'Recommended',
    planLevels: ['A conservative', 'B standard', 'C aggressive'],
    stop: 'Stop',
    composerHint: 'Continue in the same session',
  },
  stream: {
    phase: {
      RETRIEVING: 'Retrieving',
      PROBING: 'Probing',
      GENERATING: 'Generating',
      RANKING: 'Ranking',
      DONE: 'Done',
    },
    running: 'running',
    done: 'done',
    failed: 'failed',
    digest: 'Retrieving · 3 actions · 12s',
    digestTail: 'Process folded, click to expand',
    empty: 'Sequence not started',
    actions: 'actions',
    steps: 'steps',
    summary: 'Process summary',
  },
  tools: {
    forms: { pill: 'Inline pill', card: 'Info card', terminal: 'Terminal block' },
    formHints: {
      pill: 'Cheapest footprint, good for repeated calls',
      card: 'Default: duration plus expandable output',
      terminal: 'Shell actions keep prompt and exit code',
    },
    read: 'Read',
    command: 'Command',
    output: 'Output',
    exitOk: 'exit 0',
    exitFailed: 'exit 1',
    expand: 'Expand',
    collapse: 'Collapse',
  },
  sidebar: {
    label: 'Sessions',
    newSession: 'New session',
    pinned: 'Pinned',
    today: 'Today',
    earlier: 'Earlier',
    items: [
      'SSE disconnect handling',
      'Ranking weights',
      'Sidebar collapse',
      'Model catalog refresh',
    ],
    history: 'All history',
  },
  palette: {
    pair: 'Pair',
    usage: 'Usage',
    ratio: 'Contrast',
    rows: [
      'body / canvas',
      'secondary / canvas',
      'muted / canvas',
      'accent / canvas',
      'ink / accent-soft',
    ],
    note: 'Accent never carries small text: 11–13px uses ink or primary-900. Signal green falls under the 3:1 UI-component floor on light canvas (see the accent row): drop to the 700 step or use it as a large fill only.',
  },
  footer: 'Sample only. Pick style, palette and stream variant, then we ship it globally.',
}

export const LAB_COPY: Record<'zh-CN' | 'en', LabCopy> = { 'zh-CN': ZH, en: EN }

/** 样张语言跟随应用外观设置（lab 不引入第二套语言信号）。 */
export function useLabCopy(): LabCopy {
  const locale = useSettingsStore((s) => s.appearance.locale)
  return LAB_COPY[locale]
}
