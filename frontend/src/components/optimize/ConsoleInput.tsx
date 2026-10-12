import { useState } from 'react'
import { pickProjectFolder, scanProject } from '../../api/endpoints'
import { useSettingsStore } from '../../stores/useSettingsStore'
import './ConsoleInput.css'

/** 启动页主视觉固定文案（逐字，spec Task 3）：作为输入区占位展示，用户输入时隐藏。 */
const PROMPT_HINT = '帮你优化每一段提示词，从理清需求到上线-端到端交付生产级结果'

/** 输入自适应高度区间（1~6 行），超出由 textarea 内部滚动。 */
const MIN_TEXT_ROWS = 1
const MAX_TEXT_ROWS = 6

interface ConsoleInputProps {
  /** 提交中禁用发送按钮（POST /optimize 有副作用，MUST-15 禁重试靠禁用按钮）。 */
  isSubmitting: boolean
  /** 提交原句与项目路径（草稿不进 store，上抛交页面调 optimize 流）。 */
  onSubmit: (sentence: string, project: string) => void
}

function textRows(value: string): number {
  const lines = value.split('\n').length
  return Math.min(MAX_TEXT_ROWS, Math.max(MIN_TEXT_ROWS, lines))
}

/** 路径末段展示（与侧栏同口径，纯展示非业务判定）。 */
function baseName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path
}

function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M1.5 4a1 1 0 0 1 1-1h3l1.2 1.2h6.8a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      />
    </svg>
  )
}

/**
 * 启动页居中主视觉输入卡片（图一 1:1，spec Task 3，F-602/F-703）。
 * 仅含发送按钮 / 模型名只读 / 选择文件夹（本地，系统原生对话框）；不含附件/审批/麦克风/音频等已移除元素。
 */
export function ConsoleInput({ isSubmitting, onSubmit }: ConsoleInputProps) {
  const modelId = useSettingsStore((s) => s.settings?.model_service.model_id ?? '')
  const [sentence, setSentence] = useState('')
  const [project, setProject] = useState('')
  const [isPicking, setPicking] = useState(false)
  const [projectError, setProjectError] = useState<string | null>(null)

  const isDisabled = isSubmitting || sentence.trim() === '' || project.trim() === ''

  /** 选择成功后复校验（沿用 GET /project/scan；顺路预热符号表缓存；失败提示不自动重试 MUST-15）。 */
  async function validateProject(raw: string): Promise<void> {
    const value = raw.trim()
    if (value === '') {
      setProjectError(null)
      return
    }
    try {
      await scanProject(value)
      setProjectError(null)
    } catch {
      setProjectError('项目路径不存在或无法扫描')
    }
  }

  /** 系统原生文件夹选择（POST /project/pick）：取消（空串）保持原状不报错；仅接受本机真实目录。 */
  async function handlePickFolder(): Promise<void> {
    setPicking(true)
    try {
      const { path } = await pickProjectFolder()
      if (path !== '') {
        setProject(path)
        setProjectError(null)
        void validateProject(path)
      }
    } catch {
      setProjectError('无法打开系统文件夹选择器')
    } finally {
      setPicking(false)
    }
  }

  return (
    <div className="console-input">
      <form
        className="console-input__card"
        onSubmit={(event) => {
          event.preventDefault()
          if (isDisabled) return
          onSubmit(sentence.trim(), project.trim())
        }}
      >
        <textarea
          aria-label="优化原句"
          className="console-input__text"
          value={sentence}
          rows={textRows(sentence)}
          placeholder={PROMPT_HINT}
          onChange={(event) => setSentence(event.currentTarget.value)}
        />
        <div className="console-input__tools">
          <span className="console-input__spacer" />
          <span className="console-input__model">{modelId !== '' ? modelId : '未配置模型'}</span>
          <button
            type="submit"
            className="console-input__send"
            aria-label="发送"
            disabled={isDisabled}
          >
            <span aria-hidden="true">↑</span>
          </button>
        </div>
        <div className="console-input__divider" />
        <div className="console-input__folder">
          <button
            type="button"
            className="console-input__folder-toggle"
            aria-label="选择文件夹（本地）"
            title={project.trim() !== '' ? project : undefined}
            disabled={isPicking}
            onClick={() => void handlePickFolder()}
          >
            <FolderIcon />
            <span>{project.trim() !== '' ? baseName(project) : '选择文件夹（本地）'}</span>
          </button>
        </div>
        {projectError !== null ? <p className="console-input__error">{projectError}</p> : null}
      </form>
    </div>
  )
}
