import { z } from 'zod'

/** L3 偏好向量四维（契约 PreferenceVectorPayload）。 */
export const PreferenceVectorSchema = z.object({
  detail_level: z.number(),
  include_diff: z.number(),
  specify_tests: z.number(),
  max_files_norm: z.number(),
})

/** PUT /preference 请求体（契约 PreferenceUpdateRequest；四维均可选）。 */
export const PreferenceUpdateRequestSchema = z.object({
  detail_level: z.number().nullish(),
  include_diff: z.number().nullish(),
  specify_tests: z.number().nullish(),
  max_files_norm: z.number().nullish(),
})
