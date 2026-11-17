import { z } from 'zod'
import { i18n } from '../i18n'

/** 领域包 id（契约 OptimizeRequest.domain，2026-11-14）；缺省 = 自动路由。15 个预置包。 */
export const DomainIdSchema = z.enum([
  'code',
  'work',
  'life',
  'creative',
  'learning',
  'data',
  'marketing',
  'translation',
  'legal',
  'medical',
  'finance',
  'game',
  'visual',
  'av',
  'operations',
])
export type DomainId = z.infer<typeof DomainIdSchema>

/** 视觉生成风格（2026-11-14 多模态）：仅 domain=visual 时生效；缺省 = 通用风格。 */
export const VisualStyleSchema = z.enum([
  'general',
  'photography',
  'creative',
  'chinese-model',
  'json-structured',
  'video',
])
export type VisualStyle = z.infer<typeof VisualStyleSchema>

/** 图生图参考图上限（与后端 validate_images 对齐）。 */
export const MAX_IMAGES = 3
export const MAX_IMAGE_BYTES = 4 * 1024 * 1024

/** 领域路由结论（契约 FlowSnapshotResponse.domain）：值与质量标记成对返回。 */
export const DomainVerdictSchema = z.object({
  domain: z.string(),
  source: z.string(),
  confidence: z.number(),
})
export type DomainVerdictPayload = z.infer<typeof DomainVerdictSchema>

/** POST /optimize 请求体（契约 OptimizeRequest）；session_id 非空 = 同一会话开新一轮。 */
export const OptimizeRequestSchema = z.object({
  // 原句可留空：留空表示「沿用上一轮目标」（追问入口）或「以 base_turn_id 为基线继续」。
  sentence: z.string(),
  project: z.string(),
  session_id: z.string().optional(),
  /** 以某一历史轮为基线新开一轮（2026-11-05「以此轮继续」）；空串 = 不指定基线。 */
  base_turn_id: z.string(),
  /** 领域覆盖（2026-11-14 领域包）：缺省 = 自动路由。 */
  domain: DomainIdSchema.nullish(),
  /** 视觉生成风格（2026-11-14 多模态）：仅 domain=visual 生效，后端契约层白名单校验。 */
  style: VisualStyleSchema.nullish(),
  /** 图生图参考图：base64 data URL，仅 domain=visual 接受（≤3 张、单张 ≤4MB）。 */
  images: z.array(z.string()).nullish(),
})

/** POST /history/{session_id}/rollback 请求体（2026-11-05 撤销，物理删除其后轮次）。 */
export const RollbackRequestSchema = z.object({ turn_id: z.string() })

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

/** 方案正文中的一条可核对断言（契约 Claim；kind/target/note 由后端生成）。 */
export const ClaimSchema = z.object({
  kind: z.string(),
  target: z.string(),
  note: z.string().default(''),
  negates: z.string().nullish(),
})

/** 方案（契约 VariantPayload；body 为后端生成文本，前端不加工）。 */
export const VariantSchema = z.object({
  body: z.string(),
  changes: z.array(z.string()).default([]),
  claims: z.array(ClaimSchema).default([]),
  /** 本轮主流程异常、已降级为保守输出；前端须给可见提示。 */
  fallback: z.boolean().default(false),
  title: z.string(),
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

/** 交付证据门（契约 DeliveryGatePayload，2026-11-05）：只镜像状态，不做判定（MUST-08）。 */
export const DeliveryGateSchema = z.object({
  disclosure: z.string(),
  reasons: z.array(z.string()),
  status: z.string(),
  /** 语义色阶由后端领域层给出（ok / warn / error），前端只按它选样式（MUST-33）。 */
  tone: z.string(),
})

/**
 * 流程快照（契约 FlowSnapshotResponse）。
 * state/status 按契约为自由字符串，前端只镜像不判定（MUST-07）。
 */
export const FlowSnapshotSchema = z.object({
  cleared: z.array(z.string()).optional(),
  /** 本轮归属（2026-11-04，additive）：前端据此决定该轮进历史列表还是当前对话区。 */
  current_turn_id: z.string().nullish(),
  /** 交付证据门（2026-11-05，additive）：缺省表示未过门（反问中 / 进行中）。 */
  delivery_gate: DeliveryGateSchema.nullish(),
  // agentic 进度（2026-11-04）：仅 status === 'running' 时有值，用于时间线渲染
  agent_step: z.number().nullish(),
  agent_action: z.string().nullish(),
  agent_elapsed_ms: z.number().nullish(),
  // 交付时证据已过期（2026-11-05）：期间代码被改，方案基于旧证据。
  // 用 default 而非 optional：后端带默认值 => OpenAPI 视为总会返回，生成类型是必填。
  evidence_stale: z.boolean().default(false),
  // 纯回答轮的正文（2026-11-05）：本轮只回答、不产出方案。
  reply_text: z.string().default(''),
  facts: z.array(FactSchema).optional(),
  message: z.string(),
  questions: z.array(UnknownItemSchema).optional(),
  session_id: z.string(),
  state: z.string(),
  status: z.string(),
  target: SymbolSchema.nullish(),
  /** 领域路由结论（2026-11-14 领域包）：nullable+catch 与生成契约对齐，旧后端缺键归 null。 */
  domain: DomainVerdictSchema.nullable().catch(null),
  /** 本轮唯一方案；null / 缺省表示尚未产出（反问中 / 纯回答轮）。 */
  variant: VariantSchema.nullish(),
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

/** 分页轮次摘要（契约 PagedTurnSummary，2026-11-05）：裸数组 → 包装对象。 */
export const PagedTurnSummarySchema = z.object({
  has_more: z.boolean(),
  items: z.array(TurnSummarySchema),
  limit: z.number(),
  offset: z.number(),
})

/** 单轮详情（GET /turns/{turn_id}）：正文懒加载。 */
export const TurnDetailSchema = TurnSummarySchema.extend({
  input: z.string().default(''),
  variants: z.array(VariantSchema).default([]),
  facts: z.array(FactSchema).default([]),
  /** 本轮动作序列（2026-11-05 形态层）：历史轮可回看「这一步在做什么」。 */
  steps: z.array(z.record(z.string(), z.unknown())).default([]),
  /** 本轮思考帧重建（2026-11-15）：后端从 run_events 还原，action 含工具 output（截断）。 */
  thinking: z.array(z.record(z.string(), z.unknown())).default([]),
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
  // superRefine 而非 refine：文案要在**每次校验时**求值（refine 的 message 只能是常量，
  // 写常量会在模块加载时锁定首次语言，切到英文后仍出中文）。
  .superRefine((value, ctx) => {
    const enabled = [value.answers != null, value.escape, value.guardrail_action != null].filter(
      Boolean,
    ).length
    if (enabled !== 1) {
      ctx.addIssue({
        code: 'custom',
        message: i18n.t('validation.followup_mode_exclusive'),
      })
    }
  })
