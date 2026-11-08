import { z } from 'zod'

/**
 * 运行时事件协议（2026-11-07 多端）。
 *
 * `seq` 按会话单调递增；`seq=0` 是每次建连重发的合成快照，不落库、天然幂等。
 * 前端按 `seq` 去重、按 `last_seq` 过滤历史回放，断线用 `?since=` 只补差。
 */
export const RunEventSchema = z.object({
  seq: z.number().int().nonnegative(),
  type: z.string(),
  run_id: z.string().default(''),
  data: z.record(z.string(), z.unknown()).default({}),
  ts: z.string().default(''),
})

export type RunEvent = z.infer<typeof RunEventSchema>

/** 建连快照：run 当前状态 + 未决审批 + 已落库的最大 seq。 */
export const SessionSnapshotSchema = z.object({
  session_id: z.string(),
  run: z
    .object({
      run_id: z.string(),
      status: z.string(),
      stop_reason: z.string().default(''),
      ended_at: z.string().nullable().default(null),
    })
    .nullable()
    .default(null),
  pending: z
    .array(
      z.object({
        request_id: z.string(),
        kind: z.string(),
        payload: z.record(z.string(), z.unknown()).default({}),
      }),
    )
    .default([]),
  last_seq: z.number().int().nonnegative().default(0),
})

export type SessionSnapshot = z.infer<typeof SessionSnapshotSchema>

export const StartRunRequestSchema = z.object({
  session_id: z.string().min(1).max(128),
  project: z.string().default(''),
  sentence: z.string().default(''),
  base_turn_id: z.string().default(''),
  locale: z.string().default('zh-CN'),
})

/** 入参类型用 z.input：带默认值的字段（locale 等）对调用方是可选的。 */
export type StartRunRequest = z.input<typeof StartRunRequestSchema>

export const StartRunResponseSchema = z.object({
  run_id: z.string(),
  session_id: z.string(),
  status: z.string(),
})

export type StartRunResponse = z.infer<typeof StartRunResponseSchema>

export const InterventionAnswerSchema = z.object({
  decision: z.enum(['approve', 'deny', 'answer']),
  answer: z.string().default(''),
})

/** 终态事件：收到后应主动关闭连接（服务端也会在 stop/error 后结束流）。 */
export function isTerminalEvent(event: RunEvent): boolean {
  return event.type === 'stop' || event.type === 'error'
}

/* ---- 事件载荷守卫（2026-11-08）：非终态新帧的安全解析面 ----
 *
 * 后端新增 agent.checkpoint / delegation.* / context.compacted 帧；这里只做
 * 「解析安全不崩」，delegation/compaction 帧解析后不渲染（视觉无新增元素）。
 */

export const CheckpointPayloadSchema = z.object({
  step: z.number().int().nonnegative(),
  action: z.string().default(''),
  facts_passed: z.number().int().nonnegative().default(0),
  request_id: z.string().default(''),
})

export const DelegationRejectedPayloadSchema = z.object({
  reason: z.string().default(''),
})

export const DelegationWavePayloadSchema = z.object({
  wave: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
  orders: z.array(z.string()).default([]),
})

export const CompactedPayloadSchema = z.object({
  layers: z.array(z.string()).default([]),
})

/** 按帧类型安全解析载荷；畸形帧返回 null（MUST-15：校验失败不重试不重发）。 */
export function parseEventPayload<T extends z.ZodTypeAny>(
  schema: T,
  data: Record<string, unknown>,
): z.infer<T> | null {
  const parsed = schema.safeParse(data)
  return parsed.success ? parsed.data : null
}
