import { useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { putSettings, scanProject } from '../../api/endpoints'
import { nativePickErrorText, pickFolderViaNative } from '../../api/nativeFolder'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { errorMessage } from '../settings/errorMessage'
import { ModelPicker, type ModelTuning } from './ModelPicker'
import './ConsoleInput.css'

/** 启动页主视觉固定文案（逐字，spec Task 3）：作为输入区占位展示，用户输入时隐藏。 */
const PROMPT_HINT_KEY = 'console.prompt_hint'

/** 输入自适应高度区间（1~6 行），超出由 textarea 内部滚动（上限见 ConsoleInput.css）。 */
const MIN_TEXT_ROWS = 1
const MAX_TEXT_ROWS = 6

interface ConsoleInputProps {
  /** 提交中禁用发送按钮（POST /optimize 有副作用，MUST-15 禁重试靠禁用按钮）。 */
  isSubmitting: boolean
  /** 多轮 composer：项目路径沿用会话，允许空（后端按 session 继承）。 */
  projectOptional?: boolean
  /** 整体禁用（2026-11-05 形态层）：思考中输入区不再整块隐藏，改为禁用输入 + 停止按钮。 */
  disabled?: boolean
  /** 重挂载回填：思考视图切换会卸载本组件，失败退回输入页时草稿不能丢。 */
  initialSentence?: string
  initialProject?: string
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
 * 仅含发送按钮 / 模型下拉（F-604 多模型注册表）/ 选择文件夹（本地，页内浏览器）；
 * 不含附件/审批/麦克风/音频等已移除元素。
 */
export function ConsoleInput({
  isSubmitting,
  initialSentence = '',
  initialProject = '',
  projectOptional = false,
  disabled = false,
  onSubmit,
}: ConsoleInputProps) {
  const { t } = useTranslation()
  // 订阅 settings 单字段（selector 内禁返回新引用：`?? []` 会触发无限重渲染，MUST-16）
  const settings = useSettingsStore((s) => s.settings)
  const setSettings = useSettingsStore((s) => s.setSettings)
  const entries = settings?.models ?? []
  const [sentence, setSentence] = useState(initialSentence)
  const [project, setProject] = useState(initialProject)
  const [isPickingFolder, setPickingFolder] = useState(false)
  const [isSwitchingModel, setSwitchingModel] = useState(false)
  const [projectError, setProjectError] = useState<string | null>(null)
  const textRef = useRef<HTMLTextAreaElement | null>(null)

  // 随内容自动增高（含自动换行，不只是 \n 行数）：先复位再量 scrollHeight，上限由 CSS 收口。
  // shortcut: jsdom 的 scrollHeight 恒为 0，此时不写内联高度，退回 rows 按行数估算
  useLayoutEffect(() => {
    const node = textRef.current
    if (node === null) return
    // 空输入交回 rows 的自然高度：实测窄屏下清空后量到 2 行（placeholder 折行），高度回不去
    if (sentence === '') {
      node.style.height = ''
      return
    }
    node.style.height = 'auto'
    if (node.scrollHeight === 0) return
    node.style.height = `${node.scrollHeight}px`
  }, [sentence])

  const isDisabled =
    disabled ||
    isSubmitting ||
    sentence.trim() === '' ||
    (!projectOptional && project.trim() === '')

  // 当前生效条目（默认展示其完整名称 label）；无激活位时回退首条（防御未激活态）
  const activeEntry = entries.find((m) => m.is_active) ?? entries[0]
  const activeId = activeEntry?.id ?? ''

  /**
   * 按模型粒度改参数（思考强度 / 上下文窗口档位，2026-10-18 迁入启动页）。
   *
   * `models` 是**整表替换**语义，故必须带上全部条目；`api_key` 不回传明文（MUST-19，
   * 后端对缺省值按「沿用同 id 旧值」处理）。失败不自动重试（MUST-15）。
   */
  async function handleTune(id: string, patch: ModelTuning): Promise<void> {
    if (entries.length === 0) return
    const models = entries.map((entry) => ({
      id: entry.id,
      provider_id: entry.provider_id,
      model_id: entry.model_id,
      ...(entry.id === id ? patch : {}),
    }))
    try {
      const next = await putSettings({ models })
      setSettings(next)
      setProjectError(null)
    } catch {
      setProjectError(t('console.save_failed'))
    }
  }

  /** 切换模型（F-604）：经 PUT /settings 落库并整条生效；失败提示不自动重试（MUST-15）。 */
  async function handleSelectModel(id: string): Promise<void> {
    setSwitchingModel(true)
    try {
      const next = await putSettings({ active_model_id: id })
      setSettings(next)
      setProjectError(null)
    } catch {
      setProjectError(t('console.switch_failed'))
    } finally {
      setSwitchingModel(false)
    }
  }

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
    } catch (error) {
      // 按错误码查文案（2001 路径不存在 / 2004 工具失败 / 其余降级），不再一律说「路径不存在」
      setProjectError(errorMessage(error, t('console.scan_failed')))
    }
  }

  /** 页内浏览器确认回调（F-601）：写入后复校验（沿用 GET /project/scan；失败提示不自动重试 MUST-15）。 */
  /**
   * 调起系统原生文件夹选择器（2026-10-19：页内资源管理器已下线，改经浏览器扩展
   * → native messaging host）。取消（空串）时保持原状；未装扩展等失败给明确文案。
   */
  async function handlePickFolder(): Promise<void> {
    if (isPickingFolder) return
    setPickingFolder(true)
    try {
      const { path } = await pickFolderViaNative()
      if (path === '') return
      setProject(path)
      setProjectError(null)
      await validateProject(path)
    } catch (error) {
      setProjectError(nativePickErrorText(error))
    } finally {
      setPickingFolder(false)
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
          ref={textRef}
          aria-label={t('console.aria_sentence')}
          className="console-input__text"
          value={sentence}
          rows={textRows(sentence)}
          placeholder={t(PROMPT_HINT_KEY)}
          disabled={disabled}
          onChange={(event) => setSentence(event.currentTarget.value)}
        />
        <div className="console-input__tools">
          <span className="console-input__spacer" />
          <ModelPicker
            entries={entries}
            providers={settings?.providers}
            activeId={activeId}
            disabled={isSwitchingModel}
            onSelect={(id) => void handleSelectModel(id)}
            onTune={(id, patch) => void handleTune(id, patch)}
          />
          <button
            type="submit"
            className="console-input__send"
            aria-label={t('console.aria_send')}
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
            aria-label={t('console.aria_pick_folder')}
            title={project.trim() !== '' ? project : undefined}
            onClick={() => void handlePickFolder()}
            disabled={isPickingFolder}
          >
            <FolderIcon />
            <span>
              {isPickingFolder
                ? t('console.opening')
                : project.trim() !== ''
                  ? baseName(project)
                  : t('console.pick_folder')}
            </span>
          </button>
        </div>
        {projectError !== null ? <p className="console-input__error">{projectError}</p> : null}
      </form>
    </div>
  )
}
