/**
 * 领域枚举（F-705：手工维护，与后端枚举对齐）。
 * 契约字段类型一律取自 `schemas/openapi.generated.ts`，此处不重复定义。
 */

/** 流程状态机 9 态镜像（后端 `state.py` FlowState；转移逻辑唯一在后端，MUST-07）。 */
export type FlowState =
  | 'INIT'
  | 'RETRIEVING'
  | 'PROBING'
  | 'ASKING'
  | 'CONFIRMING'
  | 'GENERATING'
  | 'RANKING'
  | 'DONE'
  | 'ABORTED'

/** 快照状态（后端 `service.py` SnapshotStatus + SSE 专有扩展值 aborted，见契约 FlowSnapshotResponse.status）。 */
export type SnapshotStatus = 'ask' | 'done' | 'guardrail' | 'aborted'

/** 方案档位（后端 domain VariantLevel）。 */
export type VariantLevel = 'A' | 'B' | 'C'

/** L3 偏好向量维度键（后端 `domain/ranking/ports.py` PreferenceKey）。 */
export type PreferenceKey = 'detail_level' | 'include_diff' | 'specify_tests' | 'max_files_norm'

/** SSE 连接状态（前端本地镜像，非后端契约字段）。 */
export type SseStatus = 'idle' | 'connecting' | 'open' | 'error'
