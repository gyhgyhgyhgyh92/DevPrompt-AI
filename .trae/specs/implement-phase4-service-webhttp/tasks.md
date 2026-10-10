# Tasks · 阶段四（W2 服务层与 Web HTTP）

> **执行蓝图**：`doc-阶段/2026-10-06-阶段四-W2服务层与WebHTTP-实施计划.md` v1.1——每任务的完整步骤与代码以计划对应章节为准（标注于任务名后）。波次：W1={4A}；W2={4B}；W3={4D,4E,4G} 三并行；W4={4C}；W5={4F}；W6={4H}。
> **git 约定**：子代理零 git 操作；主流程每任务收口串行提交（提交信息按计划各节给出）。
> **门禁**：每任务收口跑九命令（ruff check / format / format --check / mypy / pytest / check_architecture + 前端四脚本收口时）；DoD 见计划各节验收表。

- [x] Task 1: 4A 配置基线与环境预检（计划 §1，开工首项）✅ 2026-10-07 提交 579f410；偏差 3 项已记录（extras 需 --all-extras 恢复 / db_path 注释换行 / 瞬时语法损坏已修）
  - [ ] 1.1 TDD：test_config.py 删 `max_followup_rounds` 断言，加 `followup_soft_round_guard/followup_cost_budget/db_path` 三断言（先红）
  - [ ] 1.2 config.py：删旧键与 `mysql_*`，插入三新键（计划 1.2 第二步代码）；`.env.example` 同步（FOLLOWUP 两键 + DB_PATH，删 MySQL 块）
  - [ ] 1.3 `uv remove aiomysql pymysql` + `uv lock --check` + `uv sync --frozen` + import 确证 ModuleNotFoundError
  - [ ] 1.4 架构检查脚本兼容性验证（SQL 目录级规则）
  - [ ] 1.5 九命令绿 + 提交（`feat(config): 反问软护栏与 SQLite 存储配置基线`，含 BREAKING CHANGE）
- [x] Task 2: 4B 状态机与 L1 会话存储（计划 §2）✅ 2026-10-07 提交 c8c4f65；偏差 4 项（CAS 测试计划缺陷已修正——先推进版本再触发真实冲突 / mypy None 收窄 / Write 替代空文件 Edit / 门禁先 format 后 check）
  - [ ] 2.1 domain/models.py 追加 `FlowSession` + `SessionStore` Protocol（计划 2.2 第一步）
  - [ ] 2.2 TDD：tests/test_state.py 6 用例（先红）→ 实现 state.py（计划第三步代码）
  - [ ] 2.3 实现 memory/schema.py（SQLite DDL）+ memory/session_store.py（SQLiteSessionStore，计划第四步代码）
  - [ ] 2.4 tests/memory/test_session_store.py 4 用例（tmp_path 无 skip，含 WAL 确证）
  - [ ] 2.5 九命令绿 + 提交（`feat(service): 实现优化流程状态机与 SQLite 会话存储`）
- [x] Task 3: 4D 探针与自适应反问编排（计划 §3，与 4/5 并行）✅ 2026-10-07 提交 44a4f57；偏差 2 项（should_trigger 参数改 GuardrailConfig 结构契约——架构门禁禁 domain→config，AppConfig 鸭子类型满足 4C 无感 / 测试对齐工具门禁）
  - [ ] 3.1 TDD：tests/domain/decision/test_followup.py 7 用例（先红）
  - [ ] 3.2 实现 domain/decision/probes.py（PROBE_ASK_TEXT）+ followup.py（UnknownItem/build_unknowns/GuardrailState，计划第三步代码）
  - [ ] 3.3 门禁绿 + 提交（`feat(decision): 实现自适应反问编排（unknowns 驱动 + 软护栏）`）
- [x] Task 4: 4E 单套生成与档位裁定（计划 §4，与 3/5 并行；不碰 domain/decision 与 memory）✅ 2026-10-07 提交 62e3a69；偏差 4 项（补 validate_variant 用例至 6 / as-import 拆分 / E501 / type ignore）
  - [ ] 4.1 TDD：tests/domain/generate/test_generate.py 6 用例（先红）
  - [ ] 4.2 实现 domain/generate/ports.py + variants.py + templates/{a,b,c,__init__}.py（计划第二~四步代码）
  - [ ] 4.3 harness/llm.py 追加 `LLMGenerator` + `_last_usage` ContextVar + `last_usage()`；harness/guardrails.py 追加 `validate_variant`（计划第五/六步）
  - [ ] 4.4 门禁绿 + 提交（`feat(generate): 实现单套生成与档位裁定`）
- [x] Task 5: 4G L2 notes 与横跨项（计划 §5，与 3/4 并行；不碰 domain/generate 与 harness/llm）✅ 2026-10-07 提交 b6abe66；偏差 4 项（tests 无 __init__.py 改内联 Fake / 路由键修正 / 删未用 import / run_streamed 去 await——计划代码缺陷实证修正）
  - [ ] 5.1 TDD：tests/memory/test_project_notes.py 5 用例（先红）
  - [ ] 5.2 实现 memory/project_notes.py（write_note/read_notes/ensure_push_config/refresh_notes/init_note，计划第二步代码）
  - [ ] 5.3 实现 scripts/smoke_provider.py（F-802 四项冒烟，无 env 退出码 2，计划第三步代码）
  - [ ] 5.4 门禁绿 + 提交（`feat(memory): 实现 L2 Git notes 与供应商冒烟脚本`）
- [x] Task 6: 4C ForgeService 统一入口（计划 §6，域接口冻结后组装）✅ 2026-10-07 提交 7abbf56；偏差 6 项（关键：F-102 MIN_CANDIDATES=3 下测试改 3 符号 / escape 与 guardrail 拒绝分支移除双重 GENERATING 转移——计划状态机缺陷 / asdict / SnapshotStatus 别名 / mypy strict 适配 / 测试拆分达 8 用例）
  - [ ] 6.1 TDD：tests/test_service.py 8 用例（Fake store/decider/generator/runner/reader，先红；按计划修正后的 FakeRunner 路由与 `_service` 构造）
  - [ ] 6.2 实现 service.py：ForgeService 六方法 + `_probe_and_route`/`_reprobe`/`_generate_and_finish`/`_require`/`_snapshot` + `_summarize_facts` + `build_default`（计划第二步代码，含 asdict 修正）
  - [ ] 6.3 门禁绿 + 提交（`feat(service): 实现 ForgeService 统一业务入口`）
- [x] Task 7: 4F Web HTTP 端点与交互（计划 §7）✅ 2026-10-07 提交 d517b9b；偏差 6 项（单快照响应 / 掩码键 LLM_API_KEY / asdict / 错误渲染导入 / 模块级 build_default 保 monkeypatch / 默认入口可达）
  - [ ] 7.1 TDD：tests/api/test_routes.py 6 用例（httpx ASGITransport + monkeypatch build_default，先红）
  - [ ] 7.2 实现 interfaces/api/{app,routes,schemas,health}.py（计划第二步代码 + 九端点表；health 用 SQLite 探针）
  - [ ] 7.3 九端点注册确证（路由表）+ 门禁绿 + 提交（`feat(web): 实现 Web HTTP 九端点与自适应反问三模式`）
- [x] Task 8: 4H 出口验收（计划 §8，主流程亲自执行）✅ 2026-10-07 提交 8442045 + docs；偏差 2 项（service 补只读 resume——Web 层不得直读会话存储 / 统一错误信封友好呈现——修复 6003 裸 traceback）；端到端 mock 六段全 PASS，真实 LLM e2e 待 .env（留痕 9.5）
  - [ ] 8.1 service 补只读 `resume` + result/progress 端点恢复（恢复语义：只读快照，交互经 followup 三模式继续）
  - [ ] 8.2 端到端实测：eval/repos 真实仓库跑通 ask/escape/guardrail 三路径 + 中断恢复（PATH 前置 ctags）
  - [ ] 8.3 九命令 + `GET /api/v1/health` 全绿（§D 自检）
  - [ ] 8.4 真源 §1 阶段四 ✅ + §13 变更记录 + 计划 0.4 进度表 + 9.5 留痕区回填；提交 `docs: 阶段四出口验收通过并更新真源状态`
  - [ ] 8.5 checklist.md 全项核验 + 用户出口签收

# Task Dependencies

- Task 1 → Task 2（db_path 键）；Task 2 → Task 6；{Task 3, 4, 5} 并行且互不碰文件（接口冻结）→ Task 6 → Task 7 → Task 8
- 串行约束：Task 6 必须在 3/4/5 域接口冻结后组装；Task 7 必须在 6 后；Task 8 收口
- git 由主流程在每任务收口串行执行，避免并行提交竞争

# 执行约束（来自用户指令）

- 越界需求 → 暂停标记「待讨论项」上报（RANKING/三套/Web/L3 落库均在后续阶段）
- 与宪法冲突 → 以宪法为准并记录冲突原因于任务执行记录
- 每任务 DoD 未过不进下一任务；失败即停上报（SHOULD-03）
