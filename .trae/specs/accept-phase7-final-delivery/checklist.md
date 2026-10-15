# Checklist · 阶段七 整体验收与交付

> 逐项核验；通过后勾选。任一项失败须回 `tasks.md` 补任务修复后重验。
> 核验日期：2026-10-14（A 段 2026-10-15 更新）。**结论：T7-1~T7-7 全部通过；F-801 第二段已按 2026-10-15「方案甲」裁定关闭（排序准确率降为参考指标）→ 阶段七收口 ✅。**

## A. F-801 第二段（排序准确率）—— 通过（按 2026-10-15「方案甲」裁定关闭）

> **2026-10-15 决议**：①彻底移除 Jev（所有者批准选项 A），决策层统一为单一 LLM 实现；原「Jev 决策层启用与重测」门禁（T7J / Task 1）**关闭**。②同日裁定「方案甲」——F-801 第二段判据改写：以「LLM 决策 + ripgrep 精确取证」为价值主张，原「排序准确率 ≥80%」降为**参考指标**，不再作出口门禁 → **阶段七收口 ✅**。

- [x] Jev 相关门禁路径已按决议移除（`decision/jev.py`、`jev` extra、`typesafe-sdk`、`decider` 配置键与契约字段）
- [x] F-801 第二段判据已按「方案甲」改写（排序准确率降为参考指标，不再作出口门禁）
      → **依据＝2026-10-15 所有者裁定「方案甲」**；历史实测 58/100 = 58%（`eval/recall/report-ranking-2026-10-11.md`）作参考保留。
- [x] 阶段七据此收口 ✅（判据按所有者裁定改写，非伪造达标结论）。
      → 真源 §1 阶段七 ✅；F-801 第二段不再作出口门禁。

## B. T7-1 单测与覆盖率（F-803）—— 通过

- [x] `pytest-cov` 已登记 `pyproject` dev 依赖与技术栈版本表（`pytest-cov>=7.1,<8`；7.1.0 来源 PyPI JSON API；技术栈 §6.2）
- [x] SHOULD-10 八项必测边界均有对应用例（①②③④⑤⑥⑦ 既有；⑧ 由 `tests/test_boundaries_phase7.py` 补 6 例）
- [x] 后端核心覆盖率 ≥ 70%，报告已落盘（**93%**；`coverage/pytest-coverage.txt`）

## C. T7-2 恢复一致性（F-804）—— 通过

- [x] HTTP 路径与 resume 路径快照对照用例存在并通过（`tests/test_flow_recovery.py`，2 例，mock 决策层 + 固定种子）
- [x] 三套方案正文逐套 diff 为空
- [x] ranking 七字段（fit/pref/total/confidence/gap/marked/reason）逐字段相等
- [x] 不一致项均有明确原因说明（无静默）

## D. T7-3 成本监控（F-805）—— 通过

- [x] 单次优化 token 明细可输出（LLM token 明细；`FlowSnapshotResponse.cost`：`llm_tokens`/`total_tokens`/`llm_source`，2026-10-15 移除 Jev 后删除 `jev_tokens`/`jev_source`，additive 无新增路径）
- [x] state 超限 → 截断（非报错）+ `state.truncated` 日志（`tests/test_cost_monitoring.py` 9 例）

## E. T7-4 CI 六门禁（MUST-29）—— 通过

- [x] Ruff Lint + Format 全绿（All checks passed / 118 files formatted）
- [x] mypy 无类型错误（Success，115 files）
- [x] pytest 全通过（**350 passed / 2 skipped**）
- [x] 前端 build / tsc / ESLint / prettier / vitest 全绿（**218 passed**）
- [x] 架构约束检查通过
- [x] 契约冒烟通过（40 schema / 13 端点；两次 `gen:contract` SHA256 一致，无漂移）
- [x] 提交历史无 `--no-verify`

## F. T7-5 环境自检（§D 13 项）—— 通过

- [x] §D 13 项逐项通过（含 `GET /api/v1/health` 的 `is_healthy=true`，5 项 checks 全 ok）

## G. T7-6 文档与依赖清理 —— 通过

- [x] 中等 8/9（§3.3 错误码类别表 5 处对齐、§3.1 示例 4001→2006）已修正
- [x] 中等 11/12（Web 一期二期已随架构设计文档删除消解；§6 store 职责已统一）已修正
- [x] 轻微 16 条（命名/章节号/冗余/锚点）已修
- [x] 技术栈版本表口径修正（Playwright/structlog/asyncpg 标注未采用）
- [x] `pyproject` 已移除 `aiomysql`/`PyMySQL`，`uv.lock` 同步，全库无引用（pytest 仍 350 passed）
- [x] CI 清单仅保留 MUST-29 一处权威（架构 §2.4 与技术栈 §5.4 改为指向 MUST-29；功能清单 附录 B 为端点速查，非 CI 清单）

## H. T7-7 打包与部署 —— 通过

- [x] `uv build` 产出 wheel（`dist/devprompt_ai-0.1.0-py3-none-any.whl`；`dist/.gitignore` 已忽略产物）
- [x] `app.py` 挂载 `frontend/dist`，单端口访问页面与 `/api/v1/*` 均正常（8123 实测：`/` 200、health ok、SPA 深链 200、`/api/v1/nope` 404）
- [x] 健康检查失败回滚路径演练成功（**实测**：`DB_PATH` 指向无效目录 → `is_healthy=false` 且 `db_writable ok=false`，即回滚触发条件可被健康检查捕获；回滚可执行步骤见架构 §1.5）
- [x] L1/L2/L3 数据向后兼容确认（22 passed）

## I. T7-8 收口同步 —— 通过（2026-10-15 甲裁定后收口）

- [x] 真源 §1 阶段七状态 → ✅
      → **已达成**（标注为 `✅ 已完成（2026-10-15 按「方案甲」重述 F-801 第二段判据）`）
- [x] 真源 §13 追加本轮变更记录（2026-10-14 行 + 2026-10-15 移除 Jev 行 + 2026-10-15「方案甲」裁定/收口行）
- [x] 五份文档与实现一致（功能清单/技术栈/架构/真源；审查报告为历史记录）
- [x] 交叉校验：任务清单 T7-1~T7-7 全部闭环（Task 1 原 T7J 已于 2026-10-15 按「方案甲」关闭）

## J. 需求符合性（用户原始 5 条要求）

- [x] ① 阶段七既定任务清单逐项完成（T7-1~T7-7 全部完成；Task 1 原 T7J 已于 2026-10-15 按「方案甲」关闭）
- [x] ② 全部功能点与验收标准达标（含 F-801 两段）
      → F-801 第二段已按 2026-10-15「方案甲」裁定关闭（排序准确率降为参考指标）；F-801 第一段召回率 95% ≥80%。
- [x] ③ 相关文档全部同步更新
- [x] ④ 文档内容与实际实现完全一致（功能/参数/流程/注意事项）
- [x] ⑤ 交叉校验确认闭环且文档完整无误
