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
 *
 * 「类名写错/挂错文件」由 `scripts/check_css_modules.py` 在门禁里把关（它能区分全局层
 * 与模块层），这里不做运行时告警——运行时无法区分「全局原语」和「漏迁」。
 */

export type ClassMap = Readonly<Record<string, string>>

export function makeS(map: ClassMap) {
  return (...parts: ReadonlyArray<string | false | null | undefined>): string =>
    parts
      .flatMap((part) => (typeof part === 'string' ? part.split(/\s+/) : []))
      .filter((name) => name !== '')
      .map((name) => map[name] ?? name)
      .filter((name) => name !== '')
      .join(' ')
}
