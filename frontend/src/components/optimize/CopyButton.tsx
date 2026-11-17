import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import styles from './optimize.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

interface CopyButtonProps {
  /** 待复制文本（方案 body 原文，前端零加工）。 */
  text: string
  label?: string
}

/** 复制按钮：复制成功后短暂切换文案（本地态即弃，不上提，MUST-16）。 */
export function CopyButton({ text, label }: CopyButtonProps) {
  const { t } = useTranslation()
  const [isCopied, setIsCopied] = useState(false)

  async function handleCopy(): Promise<void> {
    await navigator.clipboard.writeText(text)
    setIsCopied(true)
  }

  return (
    <button
      type="button"
      className={s(isCopied ? 'copy-button copy-button--done' : 'copy-button')}
      onClick={() => void handleCopy()}
    >
      {isCopied ? t('common.copied') : (label ?? t('common.copy'))}
    </button>
  )
}
