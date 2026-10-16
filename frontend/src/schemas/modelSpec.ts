import { z } from 'zod'

/**
 * 文本模型的能力元数据与参数定义（2026-09-17 模型管理迁移）。
 *
 * 数据全部来自后端 `GET /settings` 的 `model_specs` 段与各条目的 `capabilities`
 * 字段——**前端只负责渲染，不做任何判定**（MUST-08）：取值范围、枚举、是否原生下发
 * 一律以后端定义为准，前端不得内置第二份「真相」。
 *
 * 多模态按裁定 D4 全部排除，此处只有文本模型相关字段。
 */

/** 单个参数的类型（对齐后端 `ParameterType`）。 */
export const ParameterTypeSchema = z.enum([
  'number',
  'integer',
  'boolean',
  'string',
  'string-array',
])

export type ParameterType = z.infer<typeof ParameterTypeSchema>

/** 参数定义（契约 ParameterDefinitionView）。 */
export const ParameterDefinitionSchema = z.object({
  name: z.string(),
  type: ParameterTypeSchema,
  label: z.string(),
  description: z.string().default(''),
  default_value: z.unknown().nullish(),
  min_value: z.number().nullish(),
  max_value: z.number().nullish(),
  step: z.number().nullish(),
  allowed_values: z.array(z.string()).optional(),
  unit: z.string().default(''),
  /** 是否会被 ModelSettings 原生下发；false 表示当前仅登记与校验，实际不生效。 */
  is_native: z.boolean().default(true),
})

export type ParameterDefinition = z.infer<typeof ParameterDefinitionSchema>

/** 模型能力标记（契约 ModelCapabilitiesView）。 */
export const ModelCapabilitiesSchema = z.object({
  supports_tools: z.boolean().default(true),
  supports_reasoning: z.boolean().default(false),
  max_context_length: z.number().nullish(),
})

export type ModelCapabilities = z.infer<typeof ModelCapabilitiesSchema>

/** provider key → 参数定义数组（契约 SettingsResponse.model_specs）。 */
export const ModelSpecsSchema = z.record(z.string(), z.array(ParameterDefinitionSchema))

export type ModelSpecs = z.infer<typeof ModelSpecsSchema>
