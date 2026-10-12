import { z } from 'zod'

/** 通用外观设置（F-604）：持久化在 localStorage，键前缀 `devprompt:v1:`。 */
export const AppearanceSettingsSchema = z.object({
  theme: z.enum(['light', 'dark', 'system']),
  locale: z.enum(['zh-CN', 'en']),
  codeFont: z.string(),
  restoreSessionOnLaunch: z.boolean(),
  desktopNotification: z.boolean(),
})

export type AppearanceSettings = z.infer<typeof AppearanceSettingsSchema>

/** 模型服务设置视图（契约 ModelServiceSettings；api_key 恒脱敏，MUST-19）。 */
export const ModelServiceSchema = z.object({
  api_key_masked: z.string(),
  base_url: z.string(),
  decider: z.enum(['auto', 'jev', 'fallback']),
  max_tokens: z.number().nullish(),
  model_id: z.string(),
  temperature: z.number().nullish(),
  timeout: z.number(),
})

/** 流程参数视图（契约 ProcessSettings）。 */
export const ProcessSchema = z.object({
  followup_cost_budget: z.number(),
  followup_soft_round_guard: z.number(),
  telemetry: z.boolean(),
})

/** 宪法锁定项（契约 LockedSettings；只读下发不接受修改，MUST-09）。 */
export const LockedSchema = z.object({
  candidate_limit: z.number(),
})

/** GET/PUT /settings 数据体（契约 SettingsResponse；locked 项仅只读渲染，MUST-08）。 */
export const SettingsResponseSchema = z.object({
  locked: LockedSchema,
  model_service: ModelServiceSchema,
  process: ProcessSchema,
})

/** PUT /settings 模型段（契约 ModelServiceUpdate；None=不变，api_key 仅入参明文）。 */
export const ModelServiceUpdateSchema = z.object({
  api_key: z.string().nullish(),
  base_url: z.string().nullish(),
  decider: z.enum(['auto', 'jev', 'fallback']).nullish(),
  max_tokens: z.number().nullish(),
  model_id: z.string().nullish(),
  temperature: z.number().nullish(),
  timeout: z.number().nullish(),
})

/** PUT /settings 流程段（契约 ProcessUpdate；None=不变）。 */
export const ProcessUpdateSchema = z.object({
  followup_cost_budget: z.number().nullish(),
  followup_soft_round_guard: z.number().nullish(),
  telemetry: z.boolean().nullish(),
})

/** PUT /settings 请求体（契约 SettingsUpdate）。 */
export const SettingsUpdateSchema = z.object({
  model_service: ModelServiceUpdateSchema.nullish(),
  process: ProcessUpdateSchema.nullish(),
})
