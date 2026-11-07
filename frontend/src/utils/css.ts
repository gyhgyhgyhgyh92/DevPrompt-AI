/**
 * CSS Modules 类名映射（2026-11-07 全量迁移）。
 *
 * 组件 className 仍写编辑期的可读名（`chat-reply__phase--current`），由这里映射成模块
 * 导出的哈希名。TSX 因此不出现 `styles['…']` 噪音，迁移是机械的。
 *
 * 两层语义：
 * - 模块内定义的类 → 映射为哈希名（真正的隔离）；
 * - 未在模块里定义的类 → 原样透传，交给 `styles/global.css` 的全局原语层
 *   （`.button` / `.field` / `.ask-panel` 这类跨组件基元是设计系统的一部分，故意不隔离）。
 *   透传在 DEV 下打一次告警，让「漏迁移的模块类」在开发时就暴露。
 */

export type ClassMap = Readonly<Record<string, string>>

export function makeS(map: ClassMap) {
  const warned = new Set<string>()

  return (...parts: ReadonlyArray<string | false | null | undefined>): string =>
    parts
      .flatMap((part) => (typeof part === 'string' ? part.split(/\s+/) : []))
      .filter((name) => name !== '')
      .map((name) => {
        const mapped = map[name]
        if (mapped !== undefined) return mapped
        // 全局原语（.button/.field 等）是设计系统的一部分，按约定透传；
        // 只有 BEM 的元素/修饰名（含 __ 或 --）漏映射才是事故——它们属于某个模块。
        const looksLocal = name.includes('__') || name.includes('--')
        if (looksLocal && import.meta.env.DEV && !warned.has(name)) {
          warned.add(name)
          // 只在 DEV 提示漏迁的模块类，生产不执行
          console.warn(`[css] BEM 类名未进入模块，样式会失效：${name}`)
        }
        return name
      })
      .filter((name) => name !== '')
      .join(' ')
}
