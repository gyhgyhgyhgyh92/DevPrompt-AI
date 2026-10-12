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

/** POST /followup/{flow_id} 请求体（契约 FollowupRequest：批量答复 / 逃生 / 护栏裁决三模式）。 */
export const FollowupRequestSchema = z.object({
  answers: z.record(z.string(), z.string()).nullish(),
  escape: z.boolean(),
  guardrail_action: z.enum(['continue', 'generate']).nullish(),
})
