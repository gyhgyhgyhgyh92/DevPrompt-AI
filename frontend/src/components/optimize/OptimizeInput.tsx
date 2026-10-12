import { useState } from 'react'
import './optimize.css'

interface OptimizeInputProps {
  /** 提交中禁用提交按钮（POST /optimize 有副作用，MUST-15 禁重试靠禁用按钮）。 */
  isSubmitting: boolean
  onSubmit: (sentence: string, project: string) => void
}

/** 优化输入（F-703）：项目路径 + 原句草稿为组件局部状态，提交即上抛（表单草稿不进 store）。 */
export function OptimizeInput({ isSubmitting, onSubmit }: OptimizeInputProps) {
  const [sentence, setSentence] = useState('')
  const [project, setProject] = useState('')

  const isSubmitDisabled = isSubmitting || sentence.trim() === '' || project.trim() === ''

  return (
    <form
      className="thread__form"
      onSubmit={(event) => {
        event.preventDefault()
        if (isSubmitDisabled) return
        onSubmit(sentence.trim(), project.trim())
      }}
    >
      <label className="field">
        <span>项目路径</span>
        <input
          className="field__input"
          value={project}
          onChange={(event) => setProject(event.target.value)}
          placeholder="D:/workspace/repo"
        />
      </label>
      <label className="field">
        <span>优化原句</span>
        <textarea
          className="field__textarea"
          value={sentence}
          onChange={(event) => setSentence(event.target.value)}
          placeholder="描述要改造的目标……"
          rows={4}
        />
      </label>
      <button type="submit" className="button button--primary" disabled={isSubmitDisabled}>
        {isSubmitting ? '提交中…' : '开始优化'}
      </button>
    </form>
  )
}
