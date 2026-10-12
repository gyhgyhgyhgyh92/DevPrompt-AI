import type { FlowSnapshotResponse, PreferenceVectorPayload } from '../../api/types'

/** 契约载荷按生成类型派生（F-705：勿手写结构）。 */
type SymbolPayload = NonNullable<FlowSnapshotResponse['target']>
type FactPayload = NonNullable<FlowSnapshotResponse['facts']>[number]

/** L3 偏好四维键（后端 domain/ranking/ports.py PreferenceKey 顺序）；纯展示，不参与任何计算判定。 */
const PREFERENCE_KEYS = ['detail_level', 'include_diff', 'specify_tests', 'max_files_norm'] as const

/** 目标定位展示：symbol@path[:line]；line 为 0 表示后端未带行号（契约默认值语义）。 */
function formatTarget(target: SymbolPayload): string {
  return target.line > 0
    ? `${target.name}@${target.path}:${target.line}`
    : `${target.name}@${target.path}`
}

interface ContextPanelProps {
  /** 目标定位（契约 target；null 渲染空态）。 */
  target: SymbolPayload | null
  /** 取证事实清单（契约 facts；key + passed 标记 + evidence 只读渲染）。 */
  facts: readonly FactPayload[]
  /** L3 偏好向量（GET /preference），只读进度条展示。 */
  vector: PreferenceVectorPayload | null
}

export function ContextPanel({ target, facts, vector }: ContextPanelProps) {
  return (
    <aside className="context-panel" aria-label="上下文面板">
      <section>
        <h2>目标定位</h2>
        {target ? (
          <code className="context-panel__target">{formatTarget(target)}</code>
        ) : (
          <p className="context-panel__empty">暂无目标定位</p>
        )}
      </section>
      <section>
        <h2>取证事实</h2>
        {facts.length === 0 ? (
          <p className="context-panel__empty">暂无取证事实</p>
        ) : (
          <ul className="context-panel__facts">
            {facts.map((fact) => (
              <li key={fact.key}>
                <span>{fact.passed ? '✓' : '✗'}</span>
                <span>{fact.key}</span>
                <span>{fact.evidence}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h2>L3 偏好向量</h2>
        {vector ? (
          PREFERENCE_KEYS.map((key) => {
            const percent = Math.round(vector[key] * 100)
            return (
              <div className="vector-bar" key={key}>
                <span className="vector-bar__label">{key}</span>
                <span className="vector-bar__track">
                  <span className="vector-bar__fill" style={{ inlineSize: `${percent}%` }} />
                </span>
                <span className="vector-bar__value">{percent}%</span>
              </div>
            )
          })
        ) : (
          <p className="context-panel__empty">暂无偏好数据</p>
        )}
      </section>
    </aside>
  )
}
