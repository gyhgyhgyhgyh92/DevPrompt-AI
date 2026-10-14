# Tasks · 阶段七 整体验收与交付

> 依 `spec.md` 与 真源 §8.2（T7-1~T7-7）。任务按依赖排序；**T7J 为阶段七第一道阻塞门**。

- [ ] Task 1（T7J · F-801 第二段 Jev 重测）：启用 Jev 路径并重测排序准确率，出具报告。
  > ⛔ **阻塞（2026-10-14）**：SubTask 1.1 输入校验不通过 —— `TYPESAFE_API_KEY` 未配置（env 为空），Jev 路径无法执行。版本侧已核实（MUST-24b）：`typesafe-sdk` PyPI latest 0.7.4，0.7.2 存在，`pyproject` 的 `>=0.7.2,<1.0` 可满足。
  > 待用户提供 `TYPESAFE_API_KEY`（写入 `.env` 或 `settings.json`，0600；本 Agent 不读取/不记录明文）后解阻。
  - [ ] SubTask 1.1: 输入校验 — 确认 `TYPESAFE_API_KEY` 就绪；`uv sync --extra jev` 安装 `typesafe-sdk`（版本核实 MUST-24b）；若 key 缺失则**停止并上报**待确认项（不得以 LLM 指标冒充 Jev）。
  - [ ] SubTask 1.2: 复用 T5-10 实测脚本/口径，`decider=jev` 重跑 `eval/recall` 样本（100 条，5 仓），产出 `eval/recall/report-ranking-<日期>.md`（Jev 排序准确率 + 逐条明细 + 失败案例分析 + 指标来源标注）。
  - [ ] SubTask 1.3: 判定 — ≥80% → 通过；<80% → 触发 MUST-25 甲/乙决策树并上报用户裁决。
- [x] Task 2（T7-1 · F-803 单测收口 + 覆盖率）：必测边界补齐 + 覆盖率 ≥70%。
  > 交付：`pyproject` dev 增 `pytest-cov>=7.1,<8`（7.1.0，来源 PyPI JSON API）+ `uv.lock` 更新 + 技术栈 §6.2 登记；新增 `tests/test_boundaries_phase7.py`（6 例，补第⑧项「响应契约畸形拒绝」）；**总覆盖率 93%**（≥70%，报告 `coverage/pytest-coverage.txt`）；后端 **350 passed / 2 skipped**；ruff/mypy 全绿。
  > 假设：SHOULD-10 ⑧「Zod 对畸形响应拒绝」在前端已有 Zod 用例（`src/schemas/schemas.test.ts`），本轮以后端等价物（Pydantic 响应契约）补测。
  - [x] SubTask 2.1: `pyproject.toml` 增 dev 依赖 `pytest-cov`（同步技术栈版本表）。
  - [x] SubTask 2.2: 复核 SHOULD-10 八项必测边界用例覆盖，缺失者补齐。
  - [x] SubTask 2.3: 运行 `uv run pytest --cov=devprompt_ai`，覆盖率 ≥70%；报告落盘。
- [x] Task 3（T7-2 · F-804 恢复一致性）：新增 mock 决策层 + 固定种子下的两形态一致性用例。
  > 交付：`tests/test_flow_recovery.py`（2 用例，确定性 fake + 固定种子，不调真实 LLM）；`pytest -q` 2 passed、ruff 通过、mypy 通过。
  - [x] SubTask 3.1: HTTP 路径（`POST /optimize`→`GET /result/{flow_id}`）取快照。
  - [x] SubTask 3.2: resume 路径（SSE 中断改 `GET /result`；反问后 `POST /followup` 再拉取）取快照。
  - [x] SubTask 3.3: 断言 ①三套正文 diff 为空 ②ranking 七字段逐字段相等；不一致须说明原因。
- [x] Task 4（T7-3 · F-805 成本监控）：成本明细输出 + state 截断日志。
  > 交付：新增 `src/devprompt_ai/common/cost.py`（ContextVar 累计器）+ `tests/test_cost_monitoring.py`（9 用例）；`FlowSnapshotResponse` 增 `cost`（additive，13 路径/16 操作不变）；改 llm/jev/fallback/service/schemas/routes；`pytest tests/test_cost_monitoring.py` 9 passed；架构约束与 mypy 通过。
  - [x] SubTask 4.1: 输出单次优化 token 明细（Jev 与 LLM 分别计）。
  - [x] SubTask 4.2: 断言 state 超限 → 截断 + `state.truncated` 日志（不报错）。
- [x] Task 5（T7-4 · CI 六门禁）：本地复跑六项门禁并全绿。
  > 结果：Ruff Lint/Format ✅、mypy ✅（115 files）、pytest ✅（**350 passed / 2 skipped**）、前端 build/tsc/ESLint/prettier/vitest ✅（**218 passed**）、架构约束 ✅、契约冒烟 ✅（40 schema / 13 端点，两次 `gen:contract` SHA256 一致）；`git log` 无 `--no-verify`。
  > 注：`pnpm check:contract` 内含 `git diff --exit-code`，未提交工作区必然失败（预期）；提交后 CI 通过。
  - [x] SubTask 5.1: 后端 Ruff Lint/Format、mypy、pytest。
  - [x] SubTask 5.2: 前端 build/tsc/ESLint/prettier/vitest。
  - [x] SubTask 5.3: 架构约束检查 + `pnpm check:contract`。
- [x] Task 6（T7-5 · §D 13 项自检）：按架构文档 §D 顺序逐项执行并记录结果。
  > 结果：13 项全通过（Python 3.12.13 / uv sync / rg 15.0.0 / ctags 6.1.0 / health.llm_config ok / 后端 8123 监听 / Jev key 空 → LLM 降级符合期望 / pnpm install / vite 5173 可访问 / `is_healthy=true` 5 项 checks 全 ok / Lint / 类型检查 / pytest）。服务用完已清理。
- [x] Task 7（T7-6 · 文档清理 + 依赖清理）。
  > 交付：§3.3 错误码类别表 5 处对齐清单；§3.1 示例 4001→2006（去「25 条」冲突表述）；§6 store 职责统一（§6.1/§6.3/§6.2 一致）；§2.4 不可执行 rebase 规则改可执行；§4.6 APScheduler 去重；目录锚点补双连字符；§2.4/§5.4 CI 清单统一为「以 MUST-29 为准」（功能清单 附录 B 已为端点速查，无 CI 清单）；Playwright/structlog/asyncpg 标注**未采用**；命名对齐（`decision/`、`OptimizePage`）；**`pyproject` 移除 `aiomysql`/`PyMySQL`**（`uv.lock` 同步、代码零引用、pytest 仍 350 passed）；登记 `DEVPROMPT_FRONTEND_DIST`；真源 §8.4 + 功能清单 F-801 写入 Jev 口径。
  > `uv run pytest -q` 350 passed / 2 skipped；ruff 全绿；`rg aiomysql|PyMySQL pyproject.toml` 无输出。
  - [x] SubTask 7.1: 中等 8/9（错误码表 5 处、§3.1 示例 4001）；中等 11/12（Web 一期二期、store 职责）。
  - [x] SubTask 7.2: 轻微 16 条（命名/章节号/冗余/锚点失效）。
  - [x] SubTask 7.3: 技术栈版本表口径修正（Playwright/structlog 标注未采用）。
  - [x] SubTask 7.4: `pyproject` 移除 `aiomysql`/`PyMySQL` + `uv lock` 更新 + 无引用确认。
- [x] Task 8（T7-7 · 打包与单端口部署）：wheel + dist 托管 + 回滚 + 兼容性。
  > 交付：`app.py` 增 `_SpaStaticFiles`（SPA 回退，`/api` 不遮蔽）+ `_frontend_dist()`（支持 `DEVPROMPT_FRONTEND_DIST` 覆盖）+ 存在时 `app.mount("/")`；wheel `dist/devprompt_ai-0.1.0-py3-none-any.whl`（`uv build` 自带 `dist/.gitignore` 已忽略产物）；`pnpm build` 成功；单端口 8123 实测 `/` 200、`/api/v1/health` `is_healthy=True`、SPA 深链 200、`/api/v1/nope` 404；`pytest tests/api` 32 passed；L1/L2/L3 22 passed。回滚步骤已形成（架构 §1.5）；`DEVPROMPT_FRONTEND_DIST` 登记入 Task 7 文档清理；回滚触发验证并入 Task 6（§D 健康检查）。
  - [x] SubTask 8.1: `uv build` 出 wheel。
  - [x] SubTask 8.2: `app.py` 挂载 `frontend/dist`（StaticFiles + SPA 回退），单端口实测页面 + API。
  - [x] SubTask 8.3: 健康检查失败回滚策略演练；L1/L2/L3 数据向后兼容确认。
- [x] Task 9（T7-8 · 收口同步）：门禁全绿后更新真源 §1 状态 + §13 记录 + 五文档同步。
  > 交付：真源 §1 阶段七行 `⬜` → **`⛔ 部分完成（T7-1~T7-7 已交付并验证；F-801 第二段待 Jev，阻塞收口）`**（**未**标 ✅）；真源 §13 追加 2026-10-14 变更记录（含全事实与阻塞原因）；架构 §4.8 `app.py` 注释补单端口托管、§1.5 补回滚可执行步骤；技术栈 §5.5 补单端口说明；功能清单 F-803/F-804/F-805 补「阶段七验收：已通过」，F-801 第二段补「截至 2026-10-14 因 key 缺失未执行」。
  > ⛔ 部分阻塞：因 Task 1（F-801 第二段 Jev 重测）未闭环，阶段七**不得宣告收口**，§1 状态保持 ⛔。

# Task Dependencies

- Task 2/3/4/5/6/7/8 均无相互依赖，可并行推进。
- **Task 9 依赖 Task 1~8 全部完成**。
- **Task 1（T7J）为项目级阻塞门**：SubTask 1.1 输入校验不通过（无 key）时，Task 1 阻塞并上报；在裁决前不宣告阶段七收口。
- Task 2 的 SubTask 2.1（新增 pytest-cov）须先于 SubTask 2.3（覆盖率实测）。
- Task 7 的 SubTask 7.4（移除 MySQL 依赖）须先于 Task 8（打包）。
