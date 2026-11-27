/**
 * 自动更新源与清单校验（纯函数，不 import electron，便于 `node --test`）。
 *
 * 发布侧只维护一个 `updates` 预发布 tag：latest.yml / exe / blockmap 同目录，
 * latest.yml 使用相对路径。同一份清单在任意镜像前缀下都会解析到该镜像自己的
 * releases/download/updates/，因此不需要为每个镜像生成不同的清单。
 */

export type UpdateSourceId = 'ghfast' | 'ghproxy' | 'ghproxy-com' | 'github' | 'dev'

export interface UpdateSource {
  id: UpdateSourceId
  /** 末尾一定带 `/`，可直接拼 `latest.yml` 或交给 generic provider。 */
  baseUrl: string
}

/** GitHub 上的发布路径（不带域名），镜像前缀与直连共用。 */
export const UPDATES_RELEASE_PATH = 'gyhgyhgyhgyh92/DevPrompt-AI/releases/download/updates'

export const GITHUB_ORIGIN = 'https://github.com'

/** 按顺序尝试；GitHub 直连放最后。 */
const MIRROR_PREFIXES: ReadonlyArray<{ id: UpdateSourceId; prefix: string }> = [
  { id: 'ghfast', prefix: 'https://ghfast.top' },
  { id: 'ghproxy', prefix: 'https://ghproxy.net' },
  { id: 'ghproxy-com', prefix: 'https://gh-proxy.com' },
]

/** 下载主机白名单：镜像本身 + GitHub 资产域名（含 302 之后的 CDN）。 */
const ALLOWED_HOSTS = new Set([
  'ghfast.top',
  'ghproxy.net',
  'gh-proxy.com',
  'github.com',
  'objects.githubusercontent.com',
  'release-assets.githubusercontent.com',
])

function ensureTrailingSlash(url: string): string {
  return url.endsWith('/') ? url : `${url}/`
}

/**
 * 构建按序尝试的更新源。
 *
 * @param overrideBaseUrl 仅开发联调使用（`DPROMPT_UPDATE_BASE_URL`），非打包态才允许传入。
 */
export function buildSourceList(overrideBaseUrl?: string): UpdateSource[] {
  if (overrideBaseUrl !== undefined && overrideBaseUrl.trim() !== '') {
    return [{ id: 'dev', baseUrl: ensureTrailingSlash(overrideBaseUrl.trim()) }]
  }
  const sources: UpdateSource[] = MIRROR_PREFIXES.map(({ id, prefix }) => ({
    id,
    baseUrl: `${prefix}/${GITHUB_ORIGIN}/${UPDATES_RELEASE_PATH}/`,
  }))
  sources.push({
    id: 'github',
    baseUrl: `${GITHUB_ORIGIN}/${UPDATES_RELEASE_PATH}/`,
  })
  return sources
}

/**
 * 是否允许从该 URL 下载更新文件。
 *
 * 只做主机/协议白名单，不负责 SHA512；SHA512 由 electron-updater 按清单校验。
 * loopback 只在开发联调时放行，生产包必须为 false。
 */
export function isAllowedUpdateHost(raw: string, allowLoopback = false): boolean {
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    return false
  }
  const host = url.hostname.toLowerCase()
  if (allowLoopback && (host === '127.0.0.1' || host === 'localhost')) {
    return url.protocol === 'http:' || url.protocol === 'https:'
  }
  return url.protocol === 'https:' && ALLOWED_HOSTS.has(host)
}

/**
 * 从 latest.yml 提取“版本 + 全部 sha512”的指纹。
 *
 * 不引入 YAML 依赖：清单格式由 electron-builder 生成且稳定（version / files[].sha512），
 * 只比较这两个字段即可判断两个源是否发布了同一份产物。缺字段返回空串（视为不可信）。
 */
export function manifestFingerprint(text: string): string {
  const version = /^version:\s*['"]?([^'"\r\n]+?)['"]?\s*$/m.exec(text)?.[1]?.trim() ?? ''
  const shas = [...text.matchAll(/^\s*sha512:\s*['"]?([^'"\r\n]+?)['"]?\s*$/gm)]
    .map((match) => (match[1] ?? '').trim())
    .filter((value) => value !== '')
    .sort()
  if (version === '' || shas.length === 0) return ''
  return `${version}|${shas.join(',')}`
}

/**
 * 两个源的 latest.yml 是否指向同一版本、同一批产物。
 *
 * 比较原始文本的指纹而不是解析后的对象：镜像应字节透传同一份清单，
 * 指纹一致即可放行；任一源缺少 version/sha512 则拒绝交叉校验。
 */
export function sameManifest(a: string, b: string): boolean {
  const fingerprint = manifestFingerprint(a)
  return fingerprint !== '' && fingerprint === manifestFingerprint(b)
}

/** 更新包大小的展示文本；未知时返回空串，由文案层决定降级。 */
export function formatBytes(bytes: number | undefined): string {
  if (bytes === undefined || !Number.isFinite(bytes) || bytes <= 0) return ''
  const mb = bytes / (1024 * 1024)
  return `${mb >= 100 ? Math.round(mb) : mb.toFixed(1)} MB`
}
