import { z } from 'zod'

/** POST /optimize 请求体（契约 OptimizeRequest）。 */
export const OptimizeRequestSchema = z.object({
  sentence: z.string().min(1),
  project: z.string().min(1),
})

/** 反问未知项（契约 UnknownItemPayload，MUST-26 四要素）。 */
export const UnknownItemSchema = z.object({
  key: z.string(),
  reason: z.string(),
  best_guess: z.string(),
  ask: z.string(),
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

/**
 * 流程快照（契约 FlowSnapshotResponse）。
 * state/status/level/variant 按契约为自由字符串，前端只镜像不判定（MUST-07）。
 */
export const FlowSnapshotSchema = z.object({
  cleared: z.array(z.string()).optional(),
  message: z.string(),
  questions: z.array(UnknownItemSchema).optional(),
  ranking: RankingViewSchema.nullish(),
  session_id: z.string(),
  state: z.string(),
  status: z.string(),
  variants: z.array(VariantSchema).optional(),
})

/** POST /feedback 请求体（契约 FeedbackRequest：variant 采纳 / +edited_text 编辑采纳 / 皆无=跳过）。 */
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
