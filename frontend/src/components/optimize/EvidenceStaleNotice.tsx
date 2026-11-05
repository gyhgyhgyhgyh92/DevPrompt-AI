/**
 * 证据过期提示（2026-11-05）。
 *
 * 背景：agentic 可以跳过检索直接交付，期间代码若被改动，方案引用的行号与
 * token 出处可能已经失效。后端在交付前比对 mtime 指纹，过期时置
 * `evidence_stale = true`；这里如实展示，不阻断用户使用。
 *
 * MUST-08：纯展示，不含任何判定逻辑。
 */

interface EvidenceStaleNoticeProps {
  stale: boolean
}

export function EvidenceStaleNotice({ stale }: EvidenceStaleNoticeProps) {
  if (!stale) {
    return null
  }
  return (
    <div
      className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200"
      role="status"
    >
      交付前检测到目标项目文件已变更，本方案基于上一轮取证结果，引用的行号与 token
      出处可能已过期。建议重新提交一次以获得最新证据。
    </div>
  )
}
