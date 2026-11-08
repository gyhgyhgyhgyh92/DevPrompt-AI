import { z } from 'zod'
import { i18n } from '../i18n'
import { EmptyDataSchema, HealthResponseSchema, ScanResponseSchema } from '../schemas/common'
import {
  FlowSnapshotSchema,
  FollowupRequestSchema,
  PagedTurnSummarySchema,
  RollbackRequestSchema,
  TurnDetailSchema,
  OptimizeRequestSchema,
} from '../schemas/optimize'
import {
  HistoryUpdateRequestSchema,
  PagedHistoryItemSchema,
  ProjectDeleteSchema,
} from '../schemas/history'
import {
  ModelCatalogRefreshRequestSchema,
  ModelCatalogResponseSchema,
  SettingsResponseSchema,
  SettingsUpdateSchema,
} from '../schemas/settings'
import { StreamEventSchema, type ActionPayload } from '../schemas/stream'
import {
  InterventionAnswerSchema,
  RunEventSchema,
  StartRunRequestSchema,
  StartRunResponseSchema,
  type RunEvent,
  type StartRunRequest,
  type StartRunResponse,
} from './protocol'
import {
  API_BASE_URL,
  openEventStream,
  openPostStream,
  request,
  type PostStreamHandlers,
  type SseHandlers,
} from './client'
import { businessError, contractError, type ApiError } from './errors'
import type {
  FlowSnapshotResponse,
  FollowupRequest,
  HealthResponse,
  HistoryUpdateRequest,
  OptimizeRequest,
  PagedHistoryItem,
  PagedTurnSummary,
  ScanResponse,
  SettingsResponse,
  SettingsUpdate,
  TurnDetailPayload,
} from './types'

/** 分页参数（契约：limit / offset，2026-11-05）。 */
export interface PageParams {
  limit?: number
  offset?: number
}

/** 分页条数：轮次摘要一页 20 条、会话摘要一页 50 条（与后端端点默认值一致）。 */
export const TURNS_PAGE_SIZE = 20
export const HISTORY_PAGE_SIZE = 50

/** 分页查询串：缺省不传，避免 URL 里出现无意义的默认值。 */
function pageQuery(params?: PageParams): string {
  if (!params) return ''
  const parts: string[] = []
  if (params.limit !== undefined) parts.push(`limit=${params.limit}`)
  if (params.offset !== undefined) parts.push(`offset=${params.offset}`)
  return parts.length > 0 ? `?${parts.join('&')}` : ''
}

/** 端点清单（与仓库根 openapi.json 的 paths 一一对应；新增端点必须先冻结契约）。 */
export const ENDPOINTS = {
  health: `${API_BASE_URL}/health`,
  optimize: `${API_BASE_URL}/optimize`,
  optimizeStream: `${API_BASE_URL}/optimize/stream`,
  progress: (flowId: string) => `${API_BASE_URL}/progress/${flowId}`,
  followup: (flowId: string) => `${API_BASE_URL}/followup/${flowId}`,
  followupStream: (flowId: string) => `${API_BASE_URL}/followup/${flowId}/stream`,
  result: (flowId: string) => `${API_BASE_URL}/result/${flowId}`,
  history: (params?: PageParams) => `${API_BASE_URL}/history${pageQuery(params)}`,
  historyProject: (projectRoot: string) =>
    `${API_BASE_URL}/history?project_root=${encodeURIComponent(projectRoot)}`,
  sessionTurns: (sessionId: string, params?: PageParams) =>
    `${API_BASE_URL}/history/${encodeURIComponent(sessionId)}/turns${pageQuery(params)}`,
  turn: (turnId: string) => `${API_BASE_URL}/turns/${encodeURIComponent(turnId)}`,
  sessionRollback: (sessionId: string) =>
    `${API_BASE_URL}/history/${encodeURIComponent(sessionId)}/rollback`,
  historyItem: (sessionId: string) => `${API_BASE_URL}/history/${encodeURIComponent(sessionId)}`,
  projectScan: (project: string) =>
    `${API_BASE_URL}/project/scan?project=${encodeURIComponent(project)}`,
  modelCatalog: (providerId: string) =>
    `${API_BASE_URL}/settings/models/catalog?provider_id=${encodeURIComponent(providerId)}`,
  refreshModelCatalog: `${API_BASE_URL}/settings/models/catalog/refresh`,
  settings: `${API_BASE_URL}/settings`,
  runs: `${API_BASE_URL}/runs`,
  runCancel: (runId: string) => `${API_BASE_URL}/runs/${encodeURIComponent(runId)}/cancel`,
  sessionStream: (sessionId: string, since: number) =>
    `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/stream?since=${since}`,
  interventionAnswer: (requestId: string) =>
    `${API_BASE_URL}/interventions/${encodeURIComponent(requestId)}/answer`,
  sessionModel: (sessionId: string) =>
    `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/model`,
  events: (sessionId: string, before: number, limit = 200) =>
    `${API_BASE_URL}/events?session_id=${encodeURIComponent(sessionId)}&before=${before}&limit=${limit}`,
} as const

/** 请求体校验：不合法即抛契约错误（编程错误，不发请求也不重试，MUST-15）。 */
function parseBody<S extends z.ZodType>(schema: S, body: unknown): z.infer<S> {
  const parsed = schema.safeParse(body)
  if (!parsed.success) {
    throw contractError(i18n.t('api.body_contract'), '', parsed.error)
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

/** 流式思考过程回调：thought / action 是增量，snapshot / error 是终态（只会来其一）。 */
export interface StreamOptimizeHandlers {
  onOpen?: () => void
  onThought: (text: string, phase: string) => void
  onAction: (action: ActionPayload, phase: string) => void
  onSnapshot: (snapshot: FlowSnapshotResponse) => void
  onError: (error: ApiError) => void
}

/** SSE 帧 → 回调（optimize / followup 两个流式端点共用，2026-11-03 提取）。 */
function streamEventHandlers(handlers: StreamOptimizeHandlers): PostStreamHandlers {
  return {
    onOpen: handlers.onOpen,
    onEvent: (raw) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(raw)
      } catch {
        return
      }
      const result = StreamEventSchema.safeParse(parsed)
      if (!result.success) return
      const event = result.data
      if (event.type === 'thought') {
        handlers.onThought(event.text, event.phase)
        return
      }
      if (event.type === 'action') {
        handlers.onAction(
          {
            title: event.title,
            detail: event.detail,
            scope: event.scope,
            output: event.output,
            status: event.status,
          },
          event.phase,
        )
        return
      }
      if (event.type === 'snapshot') {
        handlers.onSnapshot(event.data)
        return
      }
      handlers.onError(businessError(event.code, event.message, event.request_id))
    },
  }
}

/**
 * POST /optimize/stream：思考过程流（有副作用端点，禁重试 MUST-15）。
 * 畸形帧直接丢弃——契约破坏重放只会复现，不重试。
 */
export function streamOptimize(
  body: OptimizeRequest,
  handlers: StreamOptimizeHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return openPostStream(
    ENDPOINTS.optimizeStream,
    parseBody(OptimizeRequestSchema, body),
    streamEventHandlers(handlers),
    signal,
  )
}

/**
 * POST /followup/{flow_id}/stream：答复后的重新研判与生成过程（有副作用，禁重试 MUST-15）。
 * 与 /optimize/stream 共用帧格式；原 POST /followup 保留给非流式调用方（2026-11-03）。
 */
export function streamFollowup(
  flowId: string,
  body: FollowupRequest,
  handlers: StreamOptimizeHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return openPostStream(
    ENDPOINTS.followupStream(flowId),
    parseBody(FollowupRequestSchema, body),
    streamEventHandlers(handlers),
    signal,
  )
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

/** GET /history：会话摘要分页（置顶优先 + 更新时间倒序）。 */
export function getHistory(params?: PageParams, signal?: AbortSignal): Promise<PagedHistoryItem> {
  return request(ENDPOINTS.history(params), {
    method: 'GET',
    schema: PagedHistoryItemSchema,
    signal,
  })
}

/** GET /history/{session_id}/turns：会话的轮次摘要分页（升序，不含正文）。 */
export function getSessionTurns(
  sessionId: string,
  params?: PageParams,
  signal?: AbortSignal,
): Promise<PagedTurnSummary> {
  return request(ENDPOINTS.sessionTurns(sessionId, params), {
    method: 'GET',
    schema: PagedTurnSummarySchema,
    signal,
  })
}

/** GET /turns/{turn_id}：单轮全文（历史轮次展开时懒加载）。 */
export function getTurn(turnId: string, signal?: AbortSignal): Promise<TurnDetailPayload> {
  return request(ENDPOINTS.turn(turnId), { method: 'GET', schema: TurnDetailSchema, signal })
}

/** POST /history/{session_id}/rollback：撤销到某一轮（物理删除其后轮次，破坏性操作）。 */
export function rollbackSession(
  sessionId: string,
  turnId: string,
  signal?: AbortSignal,
): Promise<FlowSnapshotResponse> {
  const body = RollbackRequestSchema.parse({ turn_id: turnId })
  return request(ENDPOINTS.sessionRollback(sessionId), {
    method: 'POST',
    body: JSON.stringify(body),
    schema: FlowSnapshotSchema,
    signal,
  })
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

/** DELETE /history?project_root=：项目级批量删除该组全部会话（有副作用，禁重试，MUST-15）。 */
export async function deleteHistoryByProject(
  projectRoot: string,
  signal?: AbortSignal,
): Promise<number> {
  const data = await request(ENDPOINTS.historyProject(projectRoot), {
    method: 'DELETE',
    schema: ProjectDeleteSchema,
    hasSideEffect: true,
    signal,
  })
  return data.deleted
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

/** GET 模型目录：读上次落库快照（不联网）。键为供应商 id（2026-10-18 供应商中心化）。 */
export function getModelCatalog(
  providerId: string,
  signal?: AbortSignal,
): Promise<ModelCatalogResponse> {
  return request(ENDPOINTS.modelCatalog(providerId), {
    method: 'GET',
    schema: ModelCatalogResponseSchema,
    signal,
  })
}

/** POST 刷新：现场调该供应商端点的 `/models` → 落库 → 返回合并结果。 */
export async function refreshModelCatalog(
  providerId: string,
  signal?: AbortSignal,
): Promise<ModelCatalogResponse> {
  return request(ENDPOINTS.refreshModelCatalog, {
    method: 'POST',
    schema: ModelCatalogResponseSchema,
    body: parseBody(ModelCatalogRefreshRequestSchema, { provider_id: providerId }),
    signal,
  })
}

/** 目录响应类型（由 Zod schema 推导，避免与契约生成类型重复维护）。 */
export type ModelCatalogResponse = z.infer<typeof ModelCatalogResponseSchema>

// ---- 运行时协议（2026-11-07 多端）：先起 run，再订阅会话事件流 ----

const RunCancelSchema = z.object({ run_id: z.string(), cancelled: z.boolean() })

/** POST /runs：启动一次运行并立即返回（有副作用端点，禁重试 MUST-15）。 */
export function startRun(
  body: StartRunRequest,
  signal?: AbortSignal,
): Promise<StartRunResponse> {
  return request(ENDPOINTS.runs, {
    method: 'POST',
    schema: StartRunResponseSchema,
    body: parseBody(StartRunRequestSchema, body),
    hasSideEffect: true,
    signal,
  })
}

export interface RunStreamHandlers {
  onOpen?: () => void
  onEvent: (event: RunEvent) => void
  onError?: () => void
}

/**
 * GET /sessions/{id}/stream?since=N：会话事件流。
 * EventSource 只支持 GET，正好适合订阅；畸形帧直接丢弃（契约破坏不重放）。
 */
export function openSessionStream(
  sessionId: string,
  since: number,
  handlers: RunStreamHandlers,
): () => void {
  return openEventStream(ENDPOINTS.sessionStream(sessionId, since), {
    onOpen: handlers.onOpen,
    onMessage: (raw) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(raw)
      } catch {
        return
      }
      const result = RunEventSchema.safeParse(parsed)
      if (!result.success) return
      handlers.onEvent(result.data)
    },
    onError: handlers.onError,
  })
}

/** POST /interventions/{id}/answer：审批/提问应答（第一应答获胜；重复应答报 6001）。 */
export async function answerIntervention(
  requestId: string,
  decision: 'approve' | 'deny' | 'answer',
  answer = '',
  signal?: AbortSignal,
): Promise<void> {
  await request(ENDPOINTS.interventionAnswer(requestId), {
    method: 'POST',
    schema: z.object({ request_id: z.string(), decision: z.string() }),
    body: parseBody(InterventionAnswerSchema, { decision, answer }),
    hasSideEffect: true,
    signal,
  })
}

/** POST /runs/{id}/cancel：取消运行；执行体以 aborted 收尾。 */
export async function cancelRun(runId: string, signal?: AbortSignal): Promise<void> {
  await request(ENDPOINTS.runCancel(runId), {
    method: 'POST',
    schema: RunCancelSchema,
    hasSideEffect: true,
    signal,
  })
}

const SessionModelResponseSchema = z.object({
  session_id: z.string(),
  model_override: z.string(),
})

/** POST /sessions/{id}/model：会话级模型热切换（F10）；空串 = 清除覆盖（有副作用，禁重试 MUST-15）。 */
export async function setSessionModel(
  sessionId: string,
  modelId: string,
  signal?: AbortSignal,
): Promise<string> {
  const data = await request(ENDPOINTS.sessionModel(sessionId), {
    method: 'POST',
    schema: SessionModelResponseSchema,
    body: JSON.stringify({ model_id: modelId }),
    hasSideEffect: true,
    signal,
  })
  return data.model_override
}

/**
 * 取会话当前最大 seq（提交前调用）。
 * 用它作为 `since` 起点：run 启动后到订阅建立之间的事件不会被漏掉，旧轮次也不会重放。
 */
export async function fetchLastSeq(sessionId: string, signal?: AbortSignal): Promise<number> {
  const events = await request(ENDPOINTS.events(sessionId, 1 << 30, 1), {
    method: 'GET',
    schema: z.array(RunEventSchema),
    signal,
  })
  return events.at(-1)?.seq ?? 0
}
