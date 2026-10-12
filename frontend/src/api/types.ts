import type { components } from '../schemas/openapi.generated'

/** 请求/响应类型直接取自生成契约（F-705：字段以后端 Pydantic 为唯一来源，勿手写）。 */
export type FlowSnapshotResponse = components['schemas']['FlowSnapshotResponse']
export type HealthResponse = components['schemas']['HealthResponse']
export type HistoryItemPayload = components['schemas']['HistoryItemPayload']
export type PreferenceVectorPayload = components['schemas']['PreferenceVectorPayload']
export type SettingsResponse = components['schemas']['SettingsResponse']
export type UnknownItemPayload = components['schemas']['UnknownItemPayload']
export type VariantPayload = components['schemas']['VariantPayload']
