import { z } from 'zod'

/** 统一信封外壳（契约 ApiResponse_*）：data 为原始载荷，由目标 schema 单独校验。 */
export const ApiResponseMetaSchema = z.object({
  code: z.number(),
  message: z.string(),
  request_id: z.string(),
  data: z.unknown(),
})

/** 错误响应与信封同构：仅 code + message + request_id（MUST-19：不回传堆栈）。 */
export const ApiErrorSchema = ApiResponseMetaSchema

/** 无载荷响应（契约 ApiResponse_NoneType_：data 恒为 null）。 */
export const EmptyDataSchema = z.null().optional()

/** GET /health 单项自检（契约 HealthCheckItem）。 */
export const HealthCheckItemSchema = z.object({
  detail: z.string(),
  name: z.string(),
  ok: z.boolean(),
})

/** GET /health 数据体（契约 HealthResponse）。 */
export const HealthResponseSchema = z.object({
  checks: z.array(HealthCheckItemSchema),
  is_healthy: z.boolean(),
})

/** GET /project/scan 数据体（契约 ScanResponse）。 */
export const ScanResponseSchema = z.object({
  kind_counts: z.record(z.string(), z.number()),
  total_files: z.number(),
  total_symbols: z.number(),
})

/** POST /project/pick 数据体（契约 ProjectPickResponse）：取消为空串。 */
export const ProjectPickResponseSchema = z.object({
  path: z.string(),
})
