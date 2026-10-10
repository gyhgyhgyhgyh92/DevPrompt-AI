# Checklist · 阶段四（W2 服务层与 Web HTTP）

> 全项核验完成：2026-10-07，主流程逐项复核（8 笔提交 579f410~8442045 + docs）

## 4A 配置基线

- [x] `config.py` 含 `followup_soft_round_guard=10` / `followup_cost_budget=0.0` / `db_path`，零 `max_followup_rounds` 与 `mysql_*` 残留（grep src 确证）
- [x] `uv lock --check` 与 `uv sync --frozen` 通过；`uv run python -c "import aiomysql"` 抛 ModuleNotFoundError
- [x] `.env.example` 含 FOLLOWUP 两键与 `DB_PATH`，无 MySQL 连接块
- [x] 4A 提交信息含 `BREAKING CHANGE:`（配置语义变更）

## 4B 状态机与 L1

- [x] `state.py` 是状态机唯一实现（9 态 + TRANSITIONS，含 RETRIEVING→ASKING 与 GENERATING→RANKING 预留）
- [x] 非法转移不落盘且抛 6001；CAS 版本冲突抛 6001；未知 session 抛 6003（test_state.py 6 用例）
- [x] `SQLiteSessionStore`：WAL 确证（journal_mode=wal）、幂等建表、CAS 冲突返回 False（test_session_store.py 4 用例全量必跑）
- [x] SQL 仅出现在 `memory/` 内（架构检查脚本通过）

## 4D 反问编排

- [x] `build_unknowns`：失败/低置信事实 → 未知项；已澄清 key 跳过；全过 → 空（4 用例）
- [x] `GuardrailState.should_trigger`：轮数触发 / 成本触发 / 预算 0 禁用 / 清零（3 用例）
- [x] `PROBE_ASK_TEXT` 七项全部绑定具体未知，无「是否继续」类泛化文案
- [x] `domain/decision/{probes,followup}.py` 零 I/O（纯函数，离线测试通过）

## 4E 单套生成

- [x] `resolve_level`：C/B/A 三分支正确；逃生/护栏路径强制 A（service 侧覆写）
- [x] `TEMPLATE_BY_LEVEL` 三档路由，A 档 SYSTEM 含「禁止编造路径」
- [x] `LLMGenerator.generate_single` 走模板路由 + `validate_variant`（Fake 注入用例过）
- [x] `chat_structured` 捕获 usage（`last_usage()`），零接口破坏

## 4G L2 与横跨

- [x] `project_notes`：读/写/空/8KB 超限 ValueError/init 5 用例；git 经 `run_command`（MUST-13）
- [x] `scripts/smoke_provider.py`：无 env 退出码 2；四项各自 PASS/FAIL 输出

## 4C ForgeService

- [x] 六方法齐全，首参 `user_id`（恒 "local"），全 Protocol 注入
- [x] 全流程：ask → 答复 → done；零提问直达 done（MUST-26 ①）；逃生 → A 档保守版
- [x] 护栏：轮数达阈值 → status="guardrail"，裁决继续 → 清零回 ask（轮数无上限）
- [x] 6001/6003 语义正确；`interfaces/` 外零业务判定（架构检查）

## 4F Web HTTP

- [x] `/api/v1` 九端点注册齐全（路由表确证）；请求/响应契约模型生效
- [x] 反问三模式：answers 批量答复、escape 逃生、guardrail_action continue/generate；响应信封结构正确
- [x] 错误信封仅 code+message+request_id（无明文密钥，MUST-19）；501 占位端点如实标注
- [x] 路由层零业务判定（grep 无阈值常量；渲染仅消费 FlowSnapshot）

## 4H 出口验收（W2 门禁）

- [x] 端到端：mock 决策层 + 真实 SQLite 六段全 PASS（零提问直达 C 档 / ask / 护栏双分支 / 逃生 A 档）；**真实 LLM 三路径待 .env 配置后补跑**（留痕：计划 9.5 待办 ①）
- [x] resume 中断恢复：状态与数据不丢失（e2e [3] 段 + 6003 统一错误信封验证）
- [x] 九命令 + `GET /api/v1/health` 全绿（§D 相关项；llm_config ✗ 为未配置预期）
- [x] 真源 §1 阶段四 ✅ + §13 变更记录 + 计划 0.4/9.5 回填
- [x] 用户出口签收：spec 已批准（2026-10-07 NotifyUser 批准即开工授权）；W2 出口条件达成，正式签收留待用户确认本轮报告

## 合规横切

- [x] 全程无 `--no-verify`；提交信息均为 `type(scope): subject` + body 说明为什么（MUST-21）
- [x] 子代理零 git 操作（主流程串行提交 8 笔）
- [x] 越界需求（若有）全部标记「待讨论项」并上报，未擅自实现（本阶段未出现越界；RANKING/三套/Web/L3 落库均未触碰）
- [x] spec/tasks/checklist 勾选状态与实际进度一致
