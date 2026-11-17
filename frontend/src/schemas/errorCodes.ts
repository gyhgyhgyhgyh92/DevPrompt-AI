/**
 * 后端错误码 → i18n key（N-7 + 2026-11-06 多语言）。
 *
 * 为什么需要这张表：后端 `message` 是给**日志**看的（含上下文、可能含路径），
 * 直接展示给用户既不安全（MUST-19）也不够友好——「LLM 上游服务异常，请稍后重试」
 * 比「LLM 两次输出均无法解析为约定 JSON 结构，output_type=MultiVariantDraft」有用得多。
 *
 * 约定（MUST-19）：`code` 是查表键，`message` 只进日志。值是语言包键
 * （`errors.<code>`），文案在 `i18n/locales/{zh-CN,en}.json`——两种语言共享同一键集合。
 * 本表**不含任何逻辑**（不参与评分/阈值判定，MUST-08）。
 *
 * 一致性由两层强制：`scripts/check_architecture.py::check_error_code_mapping`
 * （后端码集 ⊆ 本表 key 集）+ `src/i18n/keys.test.ts`（键→文案完备、两语言键集一致）。
 *
 * 权威来源：`src/devprompt_ai/domain/error_codes.py`（架构文档 §3.3）。
 */

/** 成功码：正常路径不查表。 */
export const SUCCESS_CODE = 0

/** 错误码 → 语言包键。key 必须覆盖后端 ERROR_CODES 全部条目。 */
export const ERROR_TEXT: Readonly<Record<number, string>> = {
  // 1 参数与校验
  1001: 'errors.1001',
  1002: 'errors.1002',
  1003: 'errors.1003',
  1004: 'errors.1004',

  // 2 检索与取证
  2001: 'errors.2001',
  2002: 'errors.2002',
  2003: 'errors.2003',
  2004: 'errors.2004',
  2005: 'errors.2005',
  2006: 'errors.2006',

  // 3 决策与置信度
  3001: 'errors.3001',
  3002: 'errors.3002',
  3003: 'errors.3003',
  3004: 'errors.3004',

  // 4 生成
  4001: 'errors.4001',
  4002: 'errors.4002',
  4003: 'errors.4003',

  // 5 外部依赖
  5001: 'errors.5001',
  5011: 'errors.5011',
  5012: 'errors.5012',
  5013: 'errors.5013',
  5014: 'errors.5014',
  5015: 'errors.5015',
  5021: 'errors.5021',

  // 6 状态机与流程
  6001: 'errors.6001',
  6002: 'errors.6002',
  6003: 'errors.6003',
  6004: 'errors.6004',

  // 9 系统内部
  9001: 'errors.9001',
  9002: 'errors.9002',
}
