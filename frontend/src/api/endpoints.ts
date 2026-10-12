import type { z } from 'zod'
import {
  EmptyDataSchema,
  HealthResponseSchema,
  ProjectPickResponseSchema,
  ScanResponseSchema,
} from '../schemas/common'
import {
  FeedbackRequestSchema,
  FlowSnapshotSchema,
  FollowupRequestSchema,
  OptimizeRequestSchema,
} from '../schemas/optimize'
import {
  AdoptionsClearSchema,
  HistoryListSchema,
  HistoryUpdateRequestSchema,
  PreferenceUpdateRequestSchema,
  PreferenceVectorSchema,
} from '../schemas/preference'
import { SettingsResponseSchema, SettingsUpdateSchema } from '../schemas/settings'
import { API_BASE_URL, openEventStream, request, type SseHandlers } from './client'
import { contractError } from './errors'
import type {
  AdoptionsClearResponse,
  FeedbackRequest,
  FlowSnapshotResponse,
  FollowupRequest,
  HealthResponse,
  HistoryItemPayload,
  HistoryUpdateRequest,
  OptimizeRequest,
  PreferenceUpdateRequest,
  PreferenceVectorPayload,
  ProjectPickResponse,
  ScanResponse,
  SettingsResponse,
  SettingsUpdate,
} from './types'

/** 端点清单（与仓库根 openapi.json 的 paths 一一对应；新增端点必须先冻结契约）。 */
export const ENDPOINTS = {
  health: `${API_BASE_URL}/health`,
  optimize: `${API_BASE_URL}/optimize`,
  progress: (flowId: string) => `${API_BASE_URL}/progress/${flowId}`,
  followup: (flowId: string) => `${API_BASE_URL}/followup/${flowId}`,
  result: (flowId: string) => `${API_BASE_URL}/result/${flowId}`,
  feedback: `${API_BASE_URL}/feedback`,
  preference: `${API_BASE_URL}/preference`,
  preferenceAdoptions: `${API_BASE_URL}/preference/adoptions`,
  history: `${API_BASE_URL}/history`,
  historyItem: (sessionId: string) => `${API_BASE_URL}/history/${encodeURIComponent(sessionId)}`,
  projectScan: (project: string) =>
    `${API_BASE_URL}/project/scan?project=${encodeURIComponent(project)}`,
  projectPick: `${API_BASE_URL}/project/pick`,
  settings: `${API_BASE_URL}/settings`,
} as const

/** 请求体校验：不合法即抛契约错误（编程错误，不发请求也不重试，MUST-15）。 */
function parseBody<S extends z.ZodType>(schema: S, body: unknown): z.infer<S> {
  const parsed = schema.safeParse(body)
  if (!parsed.success) {
    throw contractError('请求体不符合契约', '', parsed.error)
  }
  return parsed.data
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request(ENDPOINTS.health, { method: 'GET', schema: HealthResponseSchema, signal })
}

/** POST /optimize：有副作用端点（禁重试，MUST-15）。 */
export async function postOptimize(
  body: OptimizeRequest,
  signal?: AbortSignal,
): Promise<FlowSnapshotResponse> {
  return request(ENDPOINTS.optimize, {
    method: 'POST',
    schema: FlowSnapshotSchema,
    body: parseBody(OptimizeRequestSchema, body),
    hasSideEffect: true,
    signal,
  })
}

/** GET /progress/{flow_id}：SSE 订阅（12 操作之一）；关闭函数交调用方在 cleanup 中触发。 */
export function subscribeProgress(flowId: string, handlers: SseHandlers): () => void {
  return openEventStream(ENDPOINTS.progress(flowId), handlers)
}

/** POST /followup/{flow_id}：answers / escape / guardrail_action 三模式互斥（有副作用）。 */
export async function postFollowup(
  flowId: string,
  body: FollowupRequest,
  signal?: AbortSignal,
): Promise<FlowSnapshotResponse> {
  return request(ENDPOINTS.followup(flowId), {
    method: 'POST',
    schema: FlowSnapshotSchema,
    body: parseBody(FollowupRequestSchema, body),
    hasSideEffect: true,
    signal,
  })
}

/** GET /result/{flow_id}：服务端权威恢复（刷新后重建流程状态）。 */
export function getResult(flowId: string, signal?: AbortSignal): Promise<FlowSnapshotResponse> {
  return request(ENDPOINTS.result(flowId), { method: 'GET', schema: FlowSnapshotSchema, signal })
}

/** POST /feedback：有副作用端点（禁重试，MUST-15）；契约 data 恒为 null。 */
export async function postFeedback(body: FeedbackRequest, signal?: AbortSignal): Promise<void> {
  await request(ENDPOINTS.feedback, {
    method: 'POST',
    schema: EmptyDataSchema,
    body: parseBody(FeedbackRequestSchema, body),
    hasSideEffect: true,
    signal,
  })
}

export function getPreference(signal?: AbortSignal): Promise<PreferenceVectorPayload> {
  return request(ENDPOINTS.preference, {
    method: 'GET',
    schema: PreferenceVectorSchema,
    signal,
  })
}

export function putPreference(
  body: PreferenceUpdateRequest,
  signal?: AbortSignal,
): Promise<PreferenceVectorPayload> {
  return request(ENDPOINTS.preference, {
    method: 'PUT',
    schema: PreferenceVectorSchema,
    body: parseBody(PreferenceUpdateRequestSchema, body),
    signal,
  })
}

export function getHistory(signal?: AbortSignal): Promise<HistoryItemPayload[]> {
  return request(ENDPOINTS.history, { method: 'GET', schema: HistoryListSchema, signal })
}

/** PATCH /history/{session_id}：重命名 / 置顶（有副作用端点，禁重试，MUST-15）；契约 data 恒为 null。 */
export async function patchHistory(
  sessionId: string,
  body: HistoryUpdateRequest,
  signal?: AbortSignal,
): Promise<void> {
  await request(ENDPOINTS.historyItem(sessionId), {
    method: 'PATCH',
    schema: EmptyDataSchema,
    body: parseBody(HistoryUpdateRequestSchema, body),
    hasSideEffect: true,
    signal,
  })
}

/** DELETE /history/{session_id}：删除会话（有副作用端点，禁重试，MUST-15）；契约 data 恒为 null。 */
export async function deleteHistory(sessionId: string, signal?: AbortSignal): Promise<void> {
  await request(ENDPOINTS.historyItem(sessionId), {
    method: 'DELETE',
    schema: EmptyDataSchema,
    hasSideEffect: true,
    signal,
  })
}

/** DELETE /preference/adoptions：清空服务端采纳历史（有副作用端点，禁重试，MUST-15）。 */
export async function clearAdoptions(signal?: AbortSignal): Promise<AdoptionsClearResponse> {
  return request(ENDPOINTS.preferenceAdoptions, {
    method: 'DELETE',
    schema: AdoptionsClearSchema,
    hasSideEffect: true,
    signal,
  })
}

export function getSettings(signal?: AbortSignal): Promise<SettingsResponse> {
  return request(ENDPOINTS.settings, { method: 'GET', schema: SettingsResponseSchema, signal })
}

export function putSettings(body: SettingsUpdate, signal?: AbortSignal): Promise<SettingsResponse> {
  return request(ENDPOINTS.settings, {
    method: 'PUT',
    schema: SettingsResponseSchema,
    body: parseBody(SettingsUpdateSchema, body),
    signal,
  })
}

export function scanProject(project: string, signal?: AbortSignal): Promise<ScanResponse> {
  return request(ENDPOINTS.projectScan(project), {
    method: 'GET',
    schema: ScanResponseSchema,
    signal,
  })
}

/**
 * 系统原生文件夹选择（F-601/F-602）：后端弹本机对话框返回绝对路径；取消返回空串。
 * 超时放宽至 310s（略大于后端 300s，保证后端超时错误优先返回）；hasSideEffect——
 * 潜在自动重试会重复弹窗（MUST-15）。
 */
export function pickProjectFolder(signal?: AbortSignal): Promise<ProjectPickResponse> {
  return request(ENDPOINTS.projectPick, {
    method: 'POST',
    schema: ProjectPickResponseSchema,
    signal,
    timeoutMs: 310_000,
    hasSideEffect: true,
  })
}
