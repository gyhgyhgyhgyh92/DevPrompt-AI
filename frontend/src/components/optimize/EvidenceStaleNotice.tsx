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

import { useTranslation } from 'react-i18next'
import { makeS } from '../../utils/css'
import styles from './ChatStream.module.css'

const s = makeS(styles)

export function EvidenceStaleNotice({ stale }: EvidenceStaleNoticeProps) {
  const { t } = useTranslation()
  if (!stale) {
    return null
  }
  return (
    <div className={s('evidence-stale')} role="status">
      {t('gate.evidence_stale')}
    </div>
  )
}
