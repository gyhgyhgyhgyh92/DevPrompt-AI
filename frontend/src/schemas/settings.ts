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

/** 可观测性三模块开关视图（契约 ObservabilitySettings；各模块独立启停）。 */
export const ObservabilitySchema = z.object({
  trace_enabled: z.boolean(),
  trace_retention_days: z.number(),
  metrics_enabled: z.boolean(),
  replay_enabled: z.boolean(),
})

export type ObservabilitySettings = z.infer<typeof ObservabilitySchema>

/** 模型注册表条目脱敏视图（契约 ModelEntryView；api_key 恒脱敏，MUST-19）。 */
export const ModelEntryViewSchema = z.object({
  id: z.string(),
  /** 引用的供应商配置 id（端点与密钥都在那里，一个端点只配一次） */
  provider_id: z.string(),
  provider: z.string(),
  model_id: z.string(),
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
  /** 引用的供应商配置 id；端点与密钥在 providers 段，不再随条目下发 */
  provider_id: z.string().nullish(),
  model_id: z.string().nullish(),
  /**
   * 三态语义（对齐后端与源项目 manager.ts:968-972）：
   * 省略或 null = 沿用同 id 旧值；显式 `{}` = 清空；显式 dict = 整体替换。
   * 序列化时 nullish 会被剔除，故「清空」必须显式传空对象才能表达。
   */
  api_mode: z.string().nullish(),
  reasoning_effort: z.string().nullish(),
  max_context_length: z.number().nullish(),
})

/** 供应商配置脱敏视图（契约 ProviderConfigView）：端点与密钥只存一份。 */
export const ProviderConfigViewSchema = z.object({
  id: z.string(),
  provider: z.string(),
  base_url: z.string(),
  api_key_masked: z.string(),
})

export type ProviderConfigView = z.infer<typeof ProviderConfigViewSchema>

/** PUT /settings providers 段条目：id 空=新增；`api_key` 空=保留原值（前端只有脱敏值）。 */
export const ProviderConfigUpdateSchema = z.object({
  id: z.string().nullish(),
  provider: z.string().nullish(),
  base_url: z.string().nullish(),
  api_key: z.string().nullish(),
})

/** GET/PUT /settings 数据体（契约 SettingsResponse；locked 项仅只读渲染，MUST-08）。 */
/** 模型目录条目（契约 ModelDirectoryEntry）：窗口/档位/思考强度下沉到模型级。 */
export const ModelDirectoryEntrySchema = z.object({
  model_id: z.string(),
  label: z.string(),
  /** nullish = 该模型窗口未登记，前端不展示、告警不触发 */
  max_context_length: z.number().nullish(),
  /** 空 = 只能用标称值，无可选档位 */
  context_window_tiers: z.array(z.number()).default([]),
  /** 该模型官方的思考强度档位（按模型粒度，各模型不可共用）；空 = 不展示该段 */
  reasoning_efforts: z.array(z.string()).default([]),
  /** 官方标注的默认强度；空 = 取第一档 */
  default_effort: z.string().default(''),
})

export type ModelDirectoryEntry = z.infer<typeof ModelDirectoryEntrySchema>

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
  context_window_tiers: z.array(z.number()).default([]),
  /** 已核实的模型目录；空数组 = 未登记，回落厂商级窗口 */
  models: z.array(ModelDirectoryEntrySchema).default([]),
  supports_reasoning: z.boolean(),
  quirks: z.string(),
})

export type ProviderDirectoryEntry = z.infer<typeof ProviderDirectoryEntrySchema>

/** 模型目录条目（契约 ModelCatalogItem）：下拉里的一个模型选项。 */
export const ModelCatalogItemSchema = z.object({
  model_id: z.string(),
  label: z.string(),
  max_context_length: z.number().nullish(),
  context_window_tiers: z.array(z.number()).default([]),
  /** 该模型官方的思考强度档位（按模型粒度，各模型不可共用）；空 = 不展示该段 */
  reasoning_efforts: z.array(z.string()).default([]),
  /** 官方标注的默认强度；空 = 取第一档 */
  default_effort: z.string().default(''),
  /** remote = 端点实时返回的窗口；static = 静态表兜底 */
  source: z.enum(['remote', 'static']).default('remote'),
  /** 已配置但不在当前列表中（存量不失效，仅标注） */
  is_stale: z.boolean().default(false),
})

export type ModelCatalogItem = z.infer<typeof ModelCatalogItemSchema>

/** 模型目录响应（契约 ModelCatalogResponse）。`warning` 非空 = 本次刷新失败，展示上次结果。 */
export const ModelCatalogResponseSchema = z.object({
  provider: z.string(),
  base_url: z.string(),
  fetched_at: z.string().nullish(),
  models: z.array(ModelCatalogItemSchema).default([]),
  warning: z.string().nullish(),
})

export type ModelCatalogResponse = z.infer<typeof ModelCatalogResponseSchema>

/** 刷新请求体：只有条目 id——api_key 由后端从 settings.json 取，绝不进前端（MUST-19）。 */
export const ModelCatalogRefreshRequestSchema = z.object({
  /** 供应商 id（2026-10-18 起目录挂在端点而非条目上） */
  provider_id: z.string().min(1),
})

export type ModelCatalogRefreshRequest = z.infer<typeof ModelCatalogRefreshRequestSchema>

/** 技能列表项（目录与自定义同形，source 区分）。 */
export const SkillViewSchema = z.object({
  skill_id: z.string().default(''),
  name: z.string(),
  description: z.string().default(''),
  source: z.enum(['dir', 'custom']).default('dir'),
  domains: z.array(z.string()).default([]),
  enabled: z.boolean().default(true),
})

export const SkillsSettingsSchema = z.object({
  dirs: z.array(z.string()).default([]),
  items: z.array(SkillViewSchema).default([]),
})

/** PUT /settings 自定义技能项（整表替换，未出现即删除）。 */
export const SkillUpdateSchema = z.object({
  skill_id: z.string().nullish(),
  name: z.string().min(1),
  description: z.string().default(''),
  body: z.string().default(''),
  domains: z.array(z.string()).default([]),
  enabled: z.boolean().default(true),
})

const McpTransportSchema = z.enum(['stdio', 'sse', 'streamable-http'])

export const McpServerViewSchema = z.object({
  id: z.string(),
  name: z.string(),
  transport: McpTransportSchema.default('stdio'),
  command: z.string().default(''),
  args: z.array(z.string()).default([]),
  env: z.record(z.string(), z.string()).default({}),
  url: z.string().default(''),
  headers: z.record(z.string(), z.string()).default({}),
  enabled: z.boolean().default(false),
  tool_allowlist: z.array(z.string()).default([]),
})

/** PUT /settings MCP 项（env/headers 空值 = 沿用同 id 旧值）。 */
export const McpServerUpdateSchema = z.object({
  id: z.string().nullish(),
  name: z.string().min(1),
  transport: McpTransportSchema.default('stdio'),
  command: z.string().default(''),
  args: z.array(z.string()).default([]),
  env: z.record(z.string(), z.string()).default({}),
  url: z.string().default(''),
  headers: z.record(z.string(), z.string()).default({}),
  enabled: z.boolean().default(false),
  tool_allowlist: z.array(z.string()).default([]),
})

/** 测试连接结果：失败只回报，不抛。 */
export const McpProbeResultSchema = z.object({
  ok: z.boolean(),
  tools: z.array(z.string()).default([]),
  error: z.string().default(''),
})

export type McpProbeResult = z.infer<typeof McpProbeResultSchema>
export type SkillView = z.infer<typeof SkillViewSchema>
export type SkillsSettings = z.infer<typeof SkillsSettingsSchema>
export type McpServerView = z.infer<typeof McpServerViewSchema>
export type McpServerUpdate = z.infer<typeof McpServerUpdateSchema>

export const SettingsResponseSchema = z.object({
  locked: LockedSchema,
  models: z.array(ModelEntryViewSchema),
  /** 用户自己配置的供应商（可写，端点与密钥只存一份） */
  provider_configs: z.array(ProviderConfigViewSchema).optional(),
  /** 后端静态厂商目录（只读），驱动供应商下拉与档位数据源 */
  providers: z.array(ProviderDirectoryEntrySchema).optional(),
  model_service: ModelServiceSchema,
  process: ProcessSchema,
  observability: ObservabilitySchema,
  skills: SkillsSettingsSchema.default({ dirs: [], items: [] }),
  mcp_servers: z.array(McpServerViewSchema).default([]),
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

/** PUT /settings 可观测性段（契约 ObservabilityUpdate；None=不变，保存后即时生效）。 */
export const ObservabilityUpdateSchema = z.object({
  trace_enabled: z.boolean().nullish(),
  trace_retention_days: z.number().nullish(),
  metrics_enabled: z.boolean().nullish(),
  replay_enabled: z.boolean().nullish(),
})

/** PUT /settings 请求体（契约 SettingsUpdate；models 整表替换，active_model_id 切换生效项）。 */
export const SettingsUpdateSchema = z.object({
  provider_configs: z.array(ProviderConfigUpdateSchema).nullish(),
  models: z.array(ModelEntryUpdateSchema).nullish(),
  active_model_id: z.string().nullish(),
  model_service: ModelServiceUpdateSchema.nullish(),
  process: ProcessUpdateSchema.nullish(),
  observability: ObservabilityUpdateSchema.nullish(),
  skills: z.array(SkillUpdateSchema).nullish(),
  mcp_servers: z.array(McpServerUpdateSchema).nullish(),
})
