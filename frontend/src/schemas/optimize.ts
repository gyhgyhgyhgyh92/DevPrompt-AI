import { z } from 'zod'

/** POST /optimize 请求体（契约 OptimizeRequest）；session_id 非空 = 同一会话开新一轮。 */
export const OptimizeRequestSchema = z.object({
  sentence: z.string().min(1),
  project: z.string(),
  session_id: z.string().optional(),
})

/** 反问未知项（契约 UnknownItemPayload，MUST-26 四要素）。 */
export const AskOptionSchema = z.object({
  label: z.string(),
  description: z.string(),
})

export const UnknownItemSchema = z.object({
  key: z.string(),
  reason: z.string(),
  best_guess: z.string(),
  ask: z.string(),
  /** 短标签（官方 AskUserQuestion 的 header，≤12 字；空串表示不显示）。 */
  header: z.string().default(''),
  /** 选项（官方 2~4 个；空数组表示只有自由输入）。缺省视为空，兼容旧后端。 */
  options: z.array(AskOptionSchema).default([]),
  multi_select: z.boolean().default(false),
})

/** 方案（契约 VariantPayload；body 为后端生成文本，前端不加工）。 */
export const VariantSchema = z.object({
  body: z.string(),
  changes: z.array(z.string()).optional(),
  level: z.string(),
  title: z.string(),
})

/** 推荐视图（契约 RankingViewPayload；标记与否由后端判定，前端只渲染，MUST-08）。 */
export const RankingViewSchema = z.object({
  confidence: z.number(),
  fit: z.number(),
  gap: z.number(),
  marked: z.boolean(),
  pref: z.number(),
  reason: z.string(),
  total: z.number(),
  variant: z.string(),
})

/** 目标定位（契约 SymbolPayload）：symbol@path:line；line 为 0 表示不带行号。 */
export const SymbolSchema = z.object({
  line: z.number(),
  name: z.string(),
  path: z.string(),
})

/** 取证事实（契约 FactPayload，F-104 判定结果只读透出）。 */
export const FactSchema = z.object({
  evidence: z.string(),
  key: z.string(),
  passed: z.boolean(),
})

/**
 * 流程快照（契约 FlowSnapshotResponse）。
 * state/status/level/variant 按契约为自由字符串，前端只镜像不判定（MUST-07）。
 */
export const FlowSnapshotSchema = z.object({
  cleared: z.array(z.string()).optional(),
  facts: z.array(FactSchema).optional(),
  message: z.string(),
  questions: z.array(UnknownItemSchema).optional(),
  ranking: RankingViewSchema.nullish(),
  session_id: z.string(),
  state: z.string(),
  status: z.string(),
  target: SymbolSchema.nullish(),
  variants: z.array(VariantSchema).optional(),
})

/** POST /feedback 请求体（契约 FeedbackRequest：variant 采纳 / +edited_text 编辑采纳 / 皆无=跳过）。 */
/** 多轮轮次摘要（GET /history/{session_id}/turns）：不含原句与方案正文。 */
export const TurnSummarySchema = z.object({
  turn_id: z.string(),
  turn_index: z.number(),
  state: z.string(),
  target: z.string().default(''),
  conclusion: z.string().default(''),
  open_items: z.array(z.string()).default([]),
  created_at: z.string().default(''),
})

export const TurnSummaryListSchema = z.array(TurnSummarySchema)

/** 单轮详情（GET /turns/{turn_id}）：正文懒加载。 */
export const TurnDetailSchema = TurnSummarySchema.extend({
  input: z.string().default(''),
  variants: z.array(VariantSchema).default([]),
  facts: z.array(FactSchema).default([]),
})

export const FeedbackRequestSchema = z.object({
  action: z.string(),
  edited_text: z.string().nullish(),
  session_id: z.string(),
  variant: z.enum(['A', 'B', 'C']).nullish(),
})

/**
 * POST /followup/{flow_id} 请求体（契约 FollowupRequest）。
 * 三模式互斥是契约语义（后端按模式路由）：混用会让后端静默走错分支，故在请求侧即拒绝。
 */
export const FollowupRequestSchema = z
  .object({
    answers: z.record(z.string(), z.string()).nullish(),
    escape: z.boolean(),
    guardrail_action: z.enum(['continue', 'generate']).nullish(),
  })
  .refine(
    (value) =>
      [value.answers != null, value.escape, value.guardrail_action != null].filter(Boolean)
        .length === 1,
    { message: 'answers / escape / guardrail_action 三种模式必须且只能启用一种' },
  )
