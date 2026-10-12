/** 请求拦截器（横切逻辑挂载点，如 request_id 透传；当前为空管道）。 */
export type RequestInterceptor = (init: RequestInit) => RequestInit

export const requestInterceptors: readonly RequestInterceptor[] = []
