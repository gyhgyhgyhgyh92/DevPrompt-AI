import type { z } from 'zod'
import { i18n } from '../i18n'
import { ApiResponseMetaSchema } from '../schemas/common'
import {
  SUCCESS_CODE,
  abortedError,
  businessError,
  contractError,
  httpError,
  networkError,
  timeoutError,
} from './errors'
import { applyRequestInterceptors, type RequestMeta } from './interceptors'

export const API_BASE_URL = '/api/v1'

/** 单次 HTTP 往返超时（毫秒）：覆盖 POST /optimize 的检索+探针耗时；超时即中止并上抛。 */
const DEFAULT_TIMEOUT_MS = 60_000

/** request_id 响应头：优先读它，缺失时回退信封内 request_id。 */
const REQUEST_ID_HEADER = 'x-request-id'

export type RequestMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface RequestOptions<S extends z.ZodType> {
  method: RequestMethod
  schema: S
  body?: unknown
  signal?: AbortSignal
  timeoutMs?: number
  /** 有副作用端点标注：随请求透传禁重试语义（MUST-15）。 */
  hasSideEffect?: boolean
}

/** SSE 事件回调：onError 触发即代表流已关闭，是否重订由业务层显式决定（MUST-15）。 */
export interface SseHandlers {
  onOpen?: () => void
  onMessage?: (data: string) => void
  onError?: () => void
}

/**
 * 统一请求：信封解包（code=0 取 data，非 0 抛 ApiError）→ 目标 schema 校验 data。
 * 全程无自动重试：校验失败属契约破坏，副作用端点重放会产生重复流程（MUST-15）。
 */
export async function request<S extends z.ZodType>(
  path: string,
  options: RequestOptions<S>,
): Promise<z.infer<S>> {
  const {
    method,
    schema,
    body,
    signal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    hasSideEffect = false,
  } = options
  const meta: RequestMeta = { method, path, hasSideEffect, retry: 'never' }

  if (signal?.aborted) {
    throw abortedError('')
  }

  const controller = new AbortController()
  let hasTimedOut = false
  const timer = setTimeout(() => {
    hasTimedOut = true
    controller.abort()
  }, timeoutMs)
  const abortFromCaller = () => controller.abort()
  signal?.addEventListener('abort', abortFromCaller)

  let response: Response
  try {
    const payload = applyRequestInterceptors(
      {
        method,
        headers: {
          accept: 'application/json',
          // 界面语言（2026-11-06）：后端按此头输出进度流/披露/方案模板的语言
          'accept-language': i18n.language,
          // 带 JSON body 必须声明 content-type，否则后端不解包请求体
          ...(body === undefined ? {} : { 'content-type': 'application/json' }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      },
      meta,
    )
    response = await fetch(path, payload)
  } catch (error) {
    if (controller.signal.aborted) {
      throw hasTimedOut ? timeoutError('') : abortedError('')
    }
    throw networkError(i18n.t('api.network_failed'), error)
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', abortFromCaller)
  }

  const headerRequestId = response.headers.get(REQUEST_ID_HEADER) ?? ''

  let raw: unknown
  try {
    raw = await response.json()
  } catch (error) {
    throw contractError(
      i18n.t('api.json_invalid', { status: response.status }),
      headerRequestId,
      error,
    )
  }

  const envelopeResult = ApiResponseMetaSchema.safeParse(raw)
  if (!envelopeResult.success) {
    throw contractError(i18n.t('api.contract_envelope'), headerRequestId, envelopeResult.error)
  }
  const envelope = envelopeResult.data
  const requestId = headerRequestId !== '' ? headerRequestId : envelope.request_id

  if (envelope.code !== SUCCESS_CODE) {
    throw businessError(envelope.code, envelope.message, requestId)
  }

  const dataResult = schema.safeParse(envelope.data)
  if (!dataResult.success) {
    throw contractError(i18n.t('api.contract_data'), requestId, dataResult.error)
  }
  return dataResult.data
}

/** 流式响应回调：onEvent 收到一条已解帧的 data 载荷（原始 JSON 字符串）。 */
export interface PostStreamHandlers {
  onOpen?: () => void
  onEvent?: (data: string) => void
}

/** 单个 SSE 块取 data 载荷；注释帧（`: ping`）与空块返回 null。 */
function frameData(block: string): string | null {
  const lines = block
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.replace(/^data:\s?/, ''))
  return lines.length === 0 ? null : lines.join('\n')
}

/**
 * POST + 流式响应（SSE）消费：EventSource 只支持 GET，而用户原句不能进 URL /
 * 访问日志（MUST-19），故用 fetch 读 ReadableStream 并按空行分帧。
 *
 * 断流即返回，不自动重连（MUST-15 重订由业务层显式发起）；无总超时——服务端每
 * 15s 发保活注释帧，真卡死由调用方的 AbortSignal 收口。
 */
export async function openPostStream(
  path: string,
  body: unknown,
  handlers: PostStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  // 刻意不走 applyRequestInterceptors：其 accept 拦截器固定为 application/json
  let response: Response
  try {
    response = await fetch(path, {
      method: 'POST',
      headers: {
        accept: 'text/event-stream',
        'content-type': 'application/json',
        'accept-language': i18n.language,
      },
      body: JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw abortedError('')
    throw networkError(i18n.t('api.network_failed'), error)
  }
  if (!response.ok) {
    throw httpError(response.status, i18n.t('api.stream_unavailable'))
  }
  const reader = response.body?.getReader()
  if (!reader) throw networkError(i18n.t('api.stream_unsupported'))

  handlers.onOpen?.()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      // CRLF 归一：服务端固定 \n\n，但代理可能改写换行
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let cut = buffer.indexOf('\n\n')
      while (cut >= 0) {
        const data = frameData(buffer.slice(0, cut))
        buffer = buffer.slice(cut + 2)
        if (data !== null) handlers.onEvent?.(data)
        cut = buffer.indexOf('\n\n')
      }
    }
  } catch (error) {
    if (signal?.aborted) throw abortedError('')
    throw networkError(i18n.t('api.stream_broken'), error)
  } finally {
    reader.releaseLock()
  }
}

/**
 * SSE 订阅封装（GET /progress/{flow_id} 专用传输）：返回关闭函数，close 时机由调用方掌控。
 * MUST-15：错误即关闭连接、不自动重连（EventSource 原生重连被显式禁止），重订必须由业务层显式发起。
 */
export function openEventStream(url: string, handlers: SseHandlers): () => void {
  const source = new EventSource(url)
  source.onopen = () => handlers.onOpen?.()
  source.onmessage = (event: MessageEvent<string>) => handlers.onMessage?.(event.data)
  source.onerror = () => {
    source.close()
    handlers.onError?.()
  }
  return () => {
    source.onopen = null
    source.onmessage = null
    source.onerror = null
    source.close()
  }
}
