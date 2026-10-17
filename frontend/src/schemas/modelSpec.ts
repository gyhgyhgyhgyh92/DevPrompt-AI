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

/** 模型能力标记（契约 ModelCapabilitiesView）。 */
export const ModelCapabilitiesSchema = z.object({
  supports_tools: z.boolean().default(true),
  supports_reasoning: z.boolean().default(false),
  max_context_length: z.number().nullish(),
})

export type ModelCapabilities = z.infer<typeof ModelCapabilitiesSchema>
