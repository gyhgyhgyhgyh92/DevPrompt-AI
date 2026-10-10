# Checklist · implement-phase3-retrieval

> 逐项对应 spec.md 的 ADDED Requirements 与实施计划各子阶段验收表。标注 ✅✅ 的项已由主流程亲自复验（2026-10-04）。

## 3A 文档修复（Task 1）

- [x] 功能清单 W2 表 4 行编号正确（F-204 反问触发与终止 / F-205 输入完备性差异 / F-301 单套消歧），依赖列同步 ✅✅（v1.1 注 2026-10-06：F-204 已更名「自适应反问」，规格随宪法 MUST-26 v1.1 重构）
- [x] 两处断链消除（无「按 §17」、无「见 §5 方法签名表」）✅✅（断言脚本 OK）
- [x] 中等 1 消解记录写入实施计划 1.5 节（三要点齐全）
- [x] 规格文本除编号/引用外零 diff

## 3B 公共工具层（Task 2）

- [x] `common/text.py` 12 用例绿（驼峰拆分/连续大写/蛇形连字符/数字路径/CJK 二元组/单字/混合/去重/空/英文驼峰/路径）
- [x] `common/hashing.py` 3 用例绿（确定性/顺序无关/mtime 变化）
- [x] `common/process.py` 4 用例绿（stdout/allowed_exit_codes/非零 ProcessError/1s 超时 ProcessTimeoutError）
- [x] grep 零命中：无 `shell=True`、无 `subprocess.run`（AST 级检测；docstring 中的禁令字面量不属调用）
- [x] 全函数类型注解，`uv run mypy` 零错误 ✅✅

## 3C F-101 符号表（Task 3）

- [x] `domain/models.py` 四个 dataclass 形状冻结（Symbol/Candidate/CodeLocation/FactResult）
- [x] `domain/retrieval/ports.py` 与宪法 MUST-06 落点表一致（CommandRunner/FileReader）
- [x] ctags 解析用例绿（JSON 行/脏行/kind 全词映射/空输入/缓存键 mtime+路径敏感性/顺序无关/POSIX 归一化/缺字段跳过/build_ctags_args）
- [x] `SymbolTableProvider` 用例绿（miss→hit/未再调 ctags/mtime 失效/TTL 过期/exclude 传参）
- [x] `cache.hit`/`cache.miss` 日志记录存在
- [x] 抽样核对：19/19 全对（10 随机 + 10 补抽代码符号；ctags 原始输出 + Python 逐行计数双工具交叉验证）✅✅（主流程另对 mock-react-admin 抽验 provider）
- [x] domain 单测离线可跑（Fake 注入，无真实进程/文件系统）

## 3D F-102 候选检索（Task 4）

- [x] 9 用例绿（精确/路径 source/25 截断/无正文/manual 两分支/空句/空符号表/降序）
- [x] `MAX_CANDIDATES=25` 截断不报错（MUST-09）
- [x] 候选序列化无 body/content 正文字段
- [x] `<3` 条 `manual_required=True`（F-102 降级条款）

## 3E F-103/F-104（Task 5）

- [x] locate：definition_line/selectors/tokens/test_paths 四要素正确（Fake 用例绿）
- [x] facts：七项键集合与 F-104 行为列完全一致
- [x] 每项证据非空、非「未知」；证据截断 ≤200 字符
- [x] `common/process.py` 已过滤 `--route-key`（真实 rg 不受影响，test_process 仍绿）✅✅
- [x] 真实 fixture（frontend/src/App.tsx）端到端输出七项判定（token/testid/多状态/测试文件均正确判 False 并给证据）
- [x] domain 测试全部 Fake 离线（MUST-06 验证标准）

## 3F F-003 配置（Task 6）

- [x] `domain/errors.py` 五类异常 + DevPromptError 基类（code/context），3 用例绿
- [x] `AppConfig` 默认值逐一符合 F-003（含 JEV_MODEL_ID=jev-1.13.0、MAX_STATE_TOKENS=30000）✅✅（主流程验证 model_fields=20）
- [x] 环境变量覆盖生效；`reload()` 热重载生效（验收：无需重启）
- [x] 权重和 ≠1.0 → `ConfigurationError(9002)`（非静默计算）
- [x] 非法 DECIDER 被拒（Literal/ValidationError）
- [x] 键集 = F-003 14 项 + 运行时组 6 项，无私增键（MySQL 键未预加）

## 3G F-201 决策层（Task 7）

- [x] mypy overrides 已加（agents.*/openai.*）
- [x] port 契约 7 用例绿：排列校验/越界拒绝/置信度 [0,1]/Score [0,4]/枚举
- [x] `harness/llm.py` SDK 三约束存在（chat_completions + set_tracing_disabled(True) + set_default_openai_client）
- [x] `chat_structured` 10s 超时（asyncio.wait_for）；未配置 LLM 抛 ConfigurationError(9002)
- [x] fallback 行为 4 用例绿（happy/数量不符 4003/未配置/透传）
- [x] `create_decider` 工厂返回 DecisionPort（MUST-12 降级结构预留）
- [x] 集成冒烟：无 env 自动 SKIP（预期行为，非失败）
- [x] openai-agents 0.23.1 API 逐条实测匹配，零适配（风险条款未触发，无需上报）

## 3H F-801 实测（Task 8）

- [x] `scripts/measure_recall.py` 类型注解完整（mypy 范围内零错误）✅✅
- [x] 对 mock 语料端到端跑通，生成 report-2026-10-04.json/.md ✅✅（主流程复跑）
- [x] 报告四要素：分仓表 + 符号总数 + <25 标注 + 失败案例 ✅✅（主流程亲自读报告核对）
- [x] 退出码语义 0=达标/1=未达标（实测退出码 1 与 59% 一致）✅✅
- [x] 报告与真源状态均标注「mock 占位语料，不作为 MUST-25 判定依据；生死线待真实语料」
- [x] 真源文档阶段三状态行与 §13 变更记录已更新（如实记录 59%，未沿用 95% 预期）
- [x] 全程零 LLM/Jev 调用（离线，仅 ctags）

## 全局合规

- [x] 九条质量命令在最终收口时全部退出码 0 ✅✅（后端 ruff/format/mypy/pytest 66p+1s/架构检查 + 前端 typecheck/lint/format:check/test 1 passed，均主流程亲自复验）
- [x] 架构约束检查脚本通过（domain 无实现层 import、SQL 仅 memory/、前端无阈值、组件命名）✅✅
- [x] 每子阶段一次提交，消息与计划原文一致（MUST-21），由主流程串行执行（10 笔：b7faf3f/ba007c1/fd003eb/ca0196b/8fdfed9/fadd094/791a060/85d1a99/d99cdb9/1f46de5 + gitignore chore）
- [x] 无 `--no-verify`；格式化全由工具（MUST-18）
- [x] 边界锁定复核：service.py/state.py/main.py/interfaces/web/app.py/memory/session_store.py 全部 0 字节；未实现 Jev/structlog/HTTP；未触碰阶段四任务 ✅✅
- [x] 宪法冲突记录：无新增冲突（openai-agents 0.23.1 API 实测匹配 MUST-24b 钉死版本；计划与宪法无冲突项）
- [x] 显式假设留痕：mock 语料限制已在报告（语料声明节 + corpus 字段）、真源（阶段三状态行 + 变更记录）、README、本清单四处标注

## 遗留事项（移交用户/后续阶段，不阻塞本 spec 完结）

- [ ] **用户决策**：mock 实测暴露的「纯中文指称与英文标识符零词元重叠」缺口（29/100）是否在真实语料接入前预研 F-102 similarity 通道（MUST-25 重做预案）
- [ ] **用户决策**：src 两处待修缺陷（`build_ctags_args` 缺 .tsx 映射、`SymbolTableProvider` 路径归一）——脚本层已补偿，修复后移除补偿（属 src 改动，按流程走）
- [ ] **用户决策**：真实仓库语料接入时点（生死线判定前置条件）
- [ ] git 提交范围：AGENTS.md/技术栈/架构文档/审查报告/.trae/.workbuddy 仍为未跟踪（用户决定入库时机）
