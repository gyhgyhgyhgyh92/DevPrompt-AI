import { z } from 'zod'

/** 响应外壳元信息（契约 ApiResponse_* 的 code/message/request_id；MUST-19：不含堆栈）。 */
export const ApiResponseMetaSchema = z.object({
  code: z.number(),
  message: z.string(),
  request_id: z.string(),
})

/** 错误响应与响应外壳同构：仅 code + message + request_id。 */
export const ApiErrorSchema = ApiResponseMetaSchema
