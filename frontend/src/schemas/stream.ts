import { z } from 'zod'
import { FlowSnapshotSchema } from './optimize'

/**
 * 思考过程流事件契约（与后端 `POST /optimize/stream` 的 SSE 帧一一对应）。
 * 畸形帧由调用方丢弃，不重试（契约破坏重放只会复现，MUST-15）。
 */
export const ActionPayloadSchema = z.object({
  title: z.string(),
  detail: z.string(),
  scope: z.string(),
  /** 脱敏并截断后的命令输出（≤20 行 / ≤2000 字符）；空串表示无输出可展示。 */
  output: z.string().default(''),
  /** 动作结果；旧后端帧无此字段时按成功处理（2026-11-04）。 */
  status: z.enum(['ok', 'failed']).default('ok'),
})

export const StreamEventSchema = z.discriminatedUnion('type', [
  z.object({ type: z.literal('thought'), text: z.string(), phase: z.string().default('') }),
  z.object({
    type: z.literal('action'),
    phase: z.string().default(''),
    title: z.string(),
    detail: z.string(),
    scope: z.string(),
    output: z.string().default(''),
    status: z.enum(['ok', 'failed']).default('ok'),
  }),
  z.object({ type: z.literal('snapshot'), data: FlowSnapshotSchema }),
  z.object({
    type: z.literal('error'),
    code: z.number(),
    message: z.string(),
    request_id: z.string(),
  }),
])

export type StreamEvent = z.infer<typeof StreamEventSchema>
export type ThoughtEvent = Extract<StreamEvent, { type: 'thought' }>
export type ActionPayload = z.infer<typeof ActionPayloadSchema>
export type StreamActionEvent = Extract<StreamEvent, { type: 'action' }>
export type StreamSnapshotEvent = Extract<StreamEvent, { type: 'snapshot' }>
export type StreamErrorEvent = Extract<StreamEvent, { type: 'error' }>

/**
 * 思考区时间线条目（视图模型）：文字段逐字呈现，动作卡片整块出现。
 * detail 已在后端脱敏（只含仓库相对路径），前端不做任何裁剪或判定。
 */
export type ThinkingItem =
  | { id: string; kind: 'text'; text: string; phase: string }
  | {
      id: string
      kind: 'action'
      title: string
      detail: string
      scope: string
      output: string
      /** 动作结果：failed = 命令非零退出，卡片按错误色渲染（2026-11-04；旧数据缺省按成功）。 */
      status?: 'ok' | 'failed'
      phase: string
    }
