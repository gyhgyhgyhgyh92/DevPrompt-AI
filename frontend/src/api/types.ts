import type { components } from '../schemas/openapi.generated'

/** 请求/响应类型直接取自生成契约（F-705：字段以后端 Pydantic 为唯一来源，勿手写）。 */
export type AdoptionsClearResponse = components['schemas']['AdoptionsClearResponse']
export type FeedbackRequest = components['schemas']['FeedbackRequest']
export type FlowSnapshotResponse = components['schemas']['FlowSnapshotResponse']
export type FollowupRequest = components['schemas']['FollowupRequest']
export type HealthCheckItem = components['schemas']['HealthCheckItem']
export type HealthResponse = components['schemas']['HealthResponse']
export type HistoryItemPayload = components['schemas']['HistoryItemPayload']
export type HistoryUpdateRequest = components['schemas']['HistoryUpdateRequest']
export type OptimizeRequest = components['schemas']['OptimizeRequest']
export type PreferenceUpdateRequest = components['schemas']['PreferenceUpdateRequest']
export type PreferenceVectorPayload = components['schemas']['PreferenceVectorPayload']
export type RankingViewPayload = components['schemas']['RankingViewPayload']
export type ScanResponse = components['schemas']['ScanResponse']
export type SettingsResponse = components['schemas']['SettingsResponse']
export type SettingsUpdate = components['schemas']['SettingsUpdate']
export type UnknownItemPayload = components['schemas']['UnknownItemPayload']
export type VariantPayload = components['schemas']['VariantPayload']

/** 统一信封 ApiResponse<T>：外壳从契约 ApiResponse_NoneType_ 派生，仅把 data 换成泛型。 */
type EnvelopeShell = Omit<components['schemas']['ApiResponse_NoneType_'], 'data'>

export type ApiResponse<T> = EnvelopeShell & { data: T | null }
