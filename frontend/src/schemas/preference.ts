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

/** 会话摘要（契约 HistoryItemPayload；脱敏：无原句明文，MUST-19）。title 只为条目展示，pinned 为排序优先级。 */
export const HistoryItemSchema = z.object({
  pinned: z.boolean(),
  project: z.string(),
  project_root: z.string(),
  session_id: z.string(),
  state: z.string(),
  title: z.string(),
  updated_at: z.string(),
})

/** PATCH /history/{session_id} 请求体（契约 HistoryUpdateRequest；title/pinned 至少一项，None=不变）。 */
export const HistoryUpdateRequestSchema = z.object({
  pinned: z.boolean().nullish(),
  title: z.string().nullish(),
})

/** GET /history 数据体（契约 ApiResponse[list[HistoryItemPayload]] 的 data）。 */
/** 分页会话摘要（契约 PagedHistoryItem，2026-11-05）：裸数组 → 包装对象。 */
export const PagedHistoryItemSchema = z.object({
  has_more: z.boolean(),
  items: z.array(HistoryItemSchema),
  limit: z.number(),
  offset: z.number(),
})

/** DELETE /history?project_root= 数据体（契约 ProjectDeleteResponse；实际删除的会话条数）。 */
export const ProjectDeleteSchema = z.object({
  deleted: z.number(),
})

/** DELETE /preference/adoptions 数据体（契约 AdoptionsClearResponse；清空条数）。 */
export const AdoptionsClearSchema = z.object({
  cleared: z.number(),
})
