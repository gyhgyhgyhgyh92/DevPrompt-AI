# 阶段三 · W1 检索层与可行性验证 Spec

> change-id: `implement-phase3-retrieval`
> 上游依据：`doc-阶段/2026-10-04-阶段三-W1检索层与可行性验证-实施计划.md` v1.1（唯一执行真源，含 3A~3H 八个子阶段的完整步骤与代码）
> 执行优先级：`AGENTS.md`（宪法）> 实施计划 > 本 spec

## Why

阶段二工程基线已就绪（52 模块占位、质量门禁运行中），但项目尚无任何业务能力。按真源文档 §4，必须先实现检索取证四件套并用离线实测验证候选集召回率——这是 MUST-25 规定的生死线，先于一切框架代码。

## What Changes

- **3A 文档修复**：功能清单 W2 表编号错位（F-203/F-204/F-205 串位）+ 两处断链引用（§17、§5 方法签名表）；中等 1 已随架构设计文档删除消解（仅记录）
- **3B 公共工具层**：`common/text.py`（CJK 二元组 + 驼峰拆分）、`common/hashing.py`（sha256 + mtime 摘要）、`common/process.py`（异步子进程，MUST-13 全项）
- **3C F-101 符号表**：`domain/retrieval/ports.py`（CommandRunner/FileReader Protocol）、`domain/models.py`（Symbol/Candidate/CodeLocation/FactResult）、`domain/retrieval/symbols.py`（ctags 解析纯函数 + 缓存键）、`harness/process.py`（Protocol 实现 + SymbolTableProvider，TTL 1h，MUST-14）
- **3D F-102 候选检索**：`domain/retrieval/candidates.py`（词元重叠打分、≤25 硬截断、<3 条人工降级、无代码正文）
- **3E F-103/F-104**：`domain/retrieval/locate.py`（rg 定位/选择器/token/测试文件）+ `facts.py`（七项事实，布尔+证据无未知）
- **3F F-003 配置**：`domain/errors.py`（五类领域异常）+ `config.py`（AppConfig 全键 + reload 热重载 + 权重校验 9002）
- **3G F-201 决策层**：`domain/decision/port.py` + `decision/prompts.py` + `decision/fallback.py` + `harness/llm.py`（SDK 三约束）+ `harness/guardrails.py`
- **3H F-801 实测**：`scripts/measure_recall.py` + `eval/recall/` 语料（**mock 占位语料已存在**）→ 实测报告
- **边界锁定（违反即任务失败）**：不实现 service.py/state.py/interfaces/（阶段四）；不实现 Jev（阶段五）；不实现 structlog/HTTP/SSE（阶段六）；src 空占位模块仅按计划填充 3B~3G 所列文件；**不启动阶段四任何任务**

**显式假设（MUST-05，源于用户既定决策）**：用户已决策「暂不创建远程仓库，语料以 mock 占位」。因此 3H 的实测基于 `eval/recall/` 的 5 个 mock 仓库 × 20 条：报告与真源状态必须标注「mock 语料，不作为 MUST-25 生死线判定依据」；**阶段四开工许可在真实语料实测达标前保持冻结**（除非用户明确放行）。集成冒烟（3G）在无 `LLM_BASE_URL/LLM_MODEL` 环境变量时自动 skip，不视为失败。

## Impact

- Affected specs：`establish-phase2-baseline`（已完成，其工程基线是本 spec 的前置）
- Affected code：
  - 新增：`common/{text,hashing}.py` 实现、`common/process.py` 实现、`domain/models.py`、`domain/errors.py`、`domain/retrieval/{ports,symbols,candidates,locate,facts}.py`、`domain/decision/port.py`、`config.py`、`decision/{prompts,fallback}.py`、`harness/{llm,guardrails}.py`、`harness/process.py` 追加、`scripts/measure_recall.py`
  - 修改：`DevPrompt-AI-功能清单.md`（3A 修复）、`pyproject.toml`（mypy SDK override）、`DevPrompt-AI-实施真源文档.md`（阶段三状态）
  - 已就绪：`eval/recall/` mock 语料（README + manifest + 5 仓库 + 100 cases）
- 宪法冲突处理：实施中若计划与 `AGENTS.md` 冲突，以宪法为准，记录冲突点并暂停上报（用户约束 3）。已知项核对：计划版本（openai-agents `>=0.23.1,<1.0`）已符合 MUST-24b；检索顺序符合 MUST-09；无已知冲突。

## ADDED Requirements

### Requirement: 3A 文档修复（T3-8）

执行体 SHALL 修正功能清单 W2 表编号错位与两处断链引用，并留痕中等 1 消解结论。

#### Scenario: 修复零残留
- **WHEN** 执行断言脚本（§17/§5 方法签名表/F-203 反问触发/F-204 输入完备性 均不存在）
- **THEN** 输出 OK；规格文本除编号/引用外零改动

### Requirement: 3B 公共工具层（MUST-13/17、§4.7）

执行体 SHALL 实现分词/哈希/异步进程三个纯工具模块，全签名类型注解，零新增依赖。

#### Scenario: 异步进程合规
- **WHEN** grep `common/process.py`
- **THEN** 无 `shell=True`、无 `subprocess.run`；超时用例（1s）抛 `ProcessTimeoutError` 且僵尸进程被清理

#### Scenario: 分词规则
- **WHEN** 调用 `tokenize_sentence("把用户中心页面的提交按钮背景色改为 primary-500")`
- **THEN** 输出含 提交/按钮/用户/primary/500 等词元（中文二元组 + 英文驼峰拆分）

### Requirement: 3C F-101 符号表构建

执行体 SHALL 实现 Protocol 落点（MUST-06 表）、ctags JSON 解析纯函数、带 mtime 摘要键与 1h TTL 的符号表缓存。

#### Scenario: domain 无 I/O 可验证
- **WHEN** 运行 domain 层单测（Fake 注入）
- **THEN** 不起真实子进程、不读真实文件即通过（§4.9 客观标准）

#### Scenario: 缓存合规（MUST-14）
- **WHEN** 同一 root 二次调用 `SymbolTableProvider.get`
- **THEN** 第二次 `cache_hit=True` 且 ctags 调用次数为 1；mtime 变化后失效重建；命中记 `cache.hit`

#### Scenario: 抽样验收（F-101 验收）
- **WHEN** 对项目自体构建符号表并随机抽 10 个符号
- **THEN** 路径与行号与实际文件全部一致

### Requirement: 3D F-102 候选检索（MUST-09）

执行体 SHALL 实现词元重叠打分候选检索，硬约束 ≤25 条（超限截断不报错）、仅符号名+路径、<3 条置 `manual_required`。

#### Scenario: 硬约束
- **WHEN** 61 个符号、原句广泛命中
- **THEN** 输出恰 25 条且按匹配度降序、抛错不发生

#### Scenario: 无正文
- **WHEN** 序列化候选集
- **THEN** 无 body/content 等正文字段（类型层强制）

### Requirement: 3E F-103 定位 + F-104 七项取证

执行体 SHALL 实现 rg 定位（定义行号/选择器/设计 token/测试文件）与七项事实逐项判定。

#### Scenario: 七项无未知
- **WHEN** 对 fixture 运行 `verify_facts`
- **THEN** 键集合与 F-104 行为列完全一致，每项有布尔值与非空非「未知」证据

### Requirement: 3F F-003 配置管理

执行体 SHALL 实现 F-003 十四键 + 运行时组的 `AppConfig`、`reload()` 热重载、权重和 ≠1.0 报 `ConfigurationError(9002)`，并落地 §3.4 五类领域异常。

#### Scenario: 热重载
- **WHEN** 环境变量 `PREFER_ADAPT_WEIGHT` 改变后调用 `reload()`
- **THEN** 新值生效，无需重启（F-003 验收）

### Requirement: 3G F-201 决策层接口（LLM 版）

执行体 SHALL 实现 `DecisionPort` 三能力（排序/研判/打分）与 `LLMFallbackDecider`，SDK 三约束（chat_completions / 禁 tracing / base_url 客户端）生效，输出契约（排列/值域）内聚校验。

#### Scenario: 无 Jev 密钥可跑（F-201 验收）
- **WHEN** 无 `TYPESAFE_API_KEY` 环境
- **THEN** `create_decider` 返回 LLM 版，三能力可调用（单测用 Fake llm，集成冒烟无 env 自动 skip）

#### Scenario: 未配置 LLM
- **WHEN** `LLM_BASE_URL`/`LLM_MODEL` 为空时调用
- **THEN** 抛 `ConfigurationError(9002)`（F-004 降级条款）

### Requirement: 3H F-801 实测链路与报告

执行体 SHALL 实现 `scripts/measure_recall.py`（离线测量：符号表+候选检索→分仓统计→<25 符号仓库标注→失败案例→退出码 0/1），并对 `eval/recall/` 语料执行实测出具报告。

#### Scenario: 链路端到端
- **WHEN** 运行 `uv run python scripts/measure_recall.py`
- **THEN** 生成 `report-<日期>.json/.md`；报告含分仓表、符号总数、失败案例；退出码反映 ≥80% 与否

#### Scenario: 生死线判定的 mock 限制（显式假设）
- **WHEN** 报告基于 mock 语料生成
- **THEN** 报告与真源状态标注「mock 占位语料，不作为 MUST-25 判定依据；生死线判定待真实仓库语料」，阶段四开工许可保持冻结直至真实语料达标或用户明确放行

### Requirement: 出口与全局门禁

执行体 SHALL 在每子阶段收口时通过全量门禁（Ruff Lint+Format / mypy / pytest / 架构约束检查 / 前端四脚本不受影响），每子阶段一次 MUST-21 规范提交。

#### Scenario: 全量门禁
- **WHEN** 任一子阶段收口
- **THEN** 九条命令全部退出码 0；提交信息与计划原文一致；无 `--no-verify`

## MODIFIED Requirements

（无）

## REMOVED Requirements

（无）
