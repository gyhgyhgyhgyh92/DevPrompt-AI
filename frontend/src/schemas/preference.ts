import { z } from 'zod'

/** L3 偏好向量四维（契约 PreferenceVectorPayload）。 */
export const PreferenceVectorSchema = z.object({
  detail_level: z.number(),
  include_diff: z.number(),
  specify_tests: z.number(),
  max_files_norm: z.number(),
})

/** PUT /preference 请求体（契约 PreferenceUpdateRequest；四维均可选，None=不变）。 */
export const PreferenceUpdateRequestSchema = z.object({
  detail_level: z.number().nullish(),
  include_diff: z.number().nullish(),
  specify_tests: z.number().nullish(),
  max_files_norm: z.number().nullish(),
})

/** 会话摘要（契约 HistoryItemPayload；脱敏：无原句明文，MUST-19）。 */
export const HistoryItemSchema = z.object({
  project: z.string(),
  session_id: z.string(),
  state: z.string(),
  updated_at: z.string(),
})

/** GET /history 数据体（契约 ApiResponse[list[HistoryItemPayload]] 的 data）。 */
export const HistoryListSchema = z.array(HistoryItemSchema)
