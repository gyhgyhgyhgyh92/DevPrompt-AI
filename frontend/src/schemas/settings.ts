import { z } from 'zod'
import { ModelCapabilitiesSchema } from './modelSpec'

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
  max_tokens: z.number().nullish(),
  model_id: z.string(),
  provider: z.string(),
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

/** 模型注册表条目脱敏视图（契约 ModelEntryView；api_key 恒脱敏，MUST-19）。 */
export const ModelEntryViewSchema = z.object({
  id: z.string(),
  label: z.string(),
  provider: z.string(),
  base_url: z.string(),
  model_id: z.string(),
  api_key_masked: z.string(),
  is_active: z.boolean(),
  // 2026-09-17 模型管理迁移：能力元数据与每模型参数覆盖（只读展示）
  capabilities: ModelCapabilitiesSchema.optional(),
  /** 2026-09-17 多供应商扩展：空 = 按 provider 默认推断 */
  api_mode: z.string().default(''),
  reasoning_effort: z.string().default(''),
  max_context_length: z.number().nullish(),
})

export type ModelEntryView = z.infer<typeof ModelEntryViewSchema>

/** PUT /settings models 段条目（契约 ModelEntryUpdate；id 空=新增，api_key 空=保留原值）。 */
export const ModelEntryUpdateSchema = z.object({
  id: z.string().nullish(),
  label: z.string().nullish(),
  provider: z.string().nullish(),
  base_url: z.string().nullish(),
  model_id: z.string().nullish(),
  api_key: z.string().nullish(),
  /**
   * 三态语义（对齐后端与源项目 manager.ts:968-972）：
   * 省略或 null = 沿用同 id 旧值；显式 `{}` = 清空；显式 dict = 整体替换。
   * 序列化时 nullish 会被剔除，故「清空」必须显式传空对象才能表达。
   */
  api_mode: z.string().nullish(),
  reasoning_effort: z.string().nullish(),
  max_context_length: z.number().nullish(),
})

/** GET/PUT /settings 数据体（契约 SettingsResponse；locked 项仅只读渲染，MUST-08）。 */
/** provider 目录条目（契约 ProviderDirectoryEntry）：前端 provider 下拉的数据源。 */
export const ProviderDirectoryEntrySchema = z.object({
  id: z.string(),
  label: z.string(),
  /** 空 = 官方端点未登记，UI 须提示用户自行查询文档填写 */
  base_url: z.string(),
  needs_key: z.boolean(),
  default_api_mode: z.string(),
  supported_api_modes: z.array(z.string()).default([]),
  max_context_length: z.number().nullish(),
  supports_reasoning: z.boolean(),
  quirks: z.string(),
})

export type ProviderDirectoryEntry = z.infer<typeof ProviderDirectoryEntrySchema>

export const SettingsResponseSchema = z.object({
  locked: LockedSchema,
  models: z.array(ModelEntryViewSchema),
  /** 2026-09-17 迁移：provider key → 参数定义数组，参数编辑器的数据来源。 */
  providers: z.array(ProviderDirectoryEntrySchema).optional(),
  model_service: ModelServiceSchema,
  process: ProcessSchema,
})

/** PUT /settings 模型段（契约 ModelServiceUpdate；None/空=不变，api_key 仅入参明文）。 */
export const ModelServiceUpdateSchema = z.object({
  api_key: z.string().nullish(),
  base_url: z.string().nullish(),
  max_tokens: z.number().nullish(),
  model_id: z.string().nullish(),
  provider: z.string().nullish(),
  temperature: z.number().nullish(),
  timeout: z.number().nullish(),
})

/** PUT /settings 流程段（契约 ProcessUpdate；None=不变）。 */
export const ProcessUpdateSchema = z.object({
  followup_cost_budget: z.number().nullish(),
  followup_soft_round_guard: z.number().nullish(),
  telemetry: z.boolean().nullish(),
})

/** PUT /settings 请求体（契约 SettingsUpdate；models 整表替换，active_model_id 切换生效项）。 */
export const SettingsUpdateSchema = z.object({
  models: z.array(ModelEntryUpdateSchema).nullish(),
  active_model_id: z.string().nullish(),
  model_service: ModelServiceUpdateSchema.nullish(),
  process: ProcessUpdateSchema.nullish(),
})
