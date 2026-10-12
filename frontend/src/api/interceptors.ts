/**
 * 请求拦截（横切逻辑）+ 禁重试语义标注（MUST-15）。
 * 本 API 层不存在任何自动重试路径：POST /optimize 等端点有副作用，重放会产生重复流程；
 * Zod 校验失败属契约破坏，重试只会复现失败。失败一律上抛 ApiError，由业务层显式处置。
 */

/** 请求元信息：随每个请求透传的端点语义标注。 */
export interface RequestMeta {
  method: string
  path: string
  /** 有副作用端点（POST /optimize、/followup、/feedback）：重放会产生重复流程。 */
  hasSideEffect: boolean
  /** 禁重试语义（MUST-15）：固定 'never'，拦截器与调用方读同一份标注。 */
  retry: 'never'
}

/** 拦截器操作的请求描述：headers 归一为普通对象，避免 HeadersInit 联合类型在管道中扩散。 */
export interface InterceptableRequest {
  method: string
  headers: Record<string, string>
  body?: string
  signal: AbortSignal
}

export type RequestInterceptor = (
  request: InterceptableRequest,
  meta: RequestMeta,
) => InterceptableRequest

const acceptJsonInterceptor: RequestInterceptor = (request) => ({
  ...request,
  headers: { ...request.headers, accept: 'application/json' },
})

export const requestInterceptors: readonly RequestInterceptor[] = [acceptJsonInterceptor]

export function applyRequestInterceptors(
  request: InterceptableRequest,
  meta: RequestMeta,
): InterceptableRequest {
  return requestInterceptors.reduce((current, interceptor) => interceptor(current, meta), request)
}
