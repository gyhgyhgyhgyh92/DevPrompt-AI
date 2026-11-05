import { z } from 'zod'

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
