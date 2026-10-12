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

/** GET/PUT /settings 契约镜像（契约 SettingsResponse；locked 项仅只读渲染，MUST-08）。 */
export const SettingsResponseSchema = z.object({
  model_service: z.object({
    api_key_masked: z.string().nullish(),
    base_url: z.string().nullish(),
    decider: z.enum(['auto', 'jev', 'fallback']).nullish(),
    max_tokens: z.number().nullish(),
    model_id: z.string().nullish(),
    temperature: z.number().nullish(),
    timeout: z.number().nullish(),
  }),
  process: z.object({
    followup_cost_budget: z.number().nullish(),
    followup_soft_round_guard: z.number().nullish(),
    telemetry: z.boolean().nullish(),
  }),
  locked: z.object({ candidate_limit: z.number() }),
})
