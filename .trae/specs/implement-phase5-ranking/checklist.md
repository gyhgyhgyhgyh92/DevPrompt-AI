# Checklist

## 宪法级（每任务收口必过）
- [x] ruff check + ruff format --check 全绿（2026-10-11 复验：All checks passed / 104 files formatted）
- [x] mypy strict 零错误（68 source files, no issues）
- [x] pytest 全绿（基线 143+，逐任务递增：143→187→228→250→257 passed + 1 skipped）
- [x] scripts/check_architecture.py 通过（2026-10-11 复验通过；ranking/recommend 判定仅存在于 domain/ranking/recommend.py；前端零阈值常量）
- [x] 无新增第三方依赖（typesafe-sdk 走既有 jev extra；429 退避手写）
- [x] 子代理零 git 操作；提交信息 type(scope) 符合 MUST-21；5F 提交 7b32ed4 含 BREAKING CHANGE footer

## 功能验收（对应 tasks.md 逐项）
- [x] F-804 两条可执行验收落入功能清单，无空括号（T5-11①，5A e85caf7）
- [x] FEATURE_TABLE 四维取值与 F-402 原文逐值一致（D-5B-1 裁决按原文，c52118c）
- [x] 加权总分手工验算断言通过（SHOULD-10，tests/test_ranking_score.py）
- [x] MUST-27 五条优先级各有测试且命中即止（四情形 + 压序）
- [x] 推荐不标时 reason 文案具体（无静默不标）
- [x] 三套同次调用；A 无行号、C 含行号+token 出处+测试指令（F-302/303/304；5C 真实冒烟梯度 440/696/1038 字符）
- [x] 仅 A 档：单套输出 + 跳过打分与推荐 + 不计算 d（MUST-28）
- [x] L3 五类更新规则单测通过；连续采纳 C 偏好移动；跳过回归 0.5（开放决策 #1 定稿公式，0.6→0.57 精确断言）
- [x] adoption_history 入库可查
- [x] JEV_MODEL_ID 恒 jev-1.13.0（禁别名断言）；30000 截断记 state.truncated；429 指数退避（0.5×2^n，n≤4）
- [x] Jev(mock) 与 fallback 输出结构逐字段一致（MUST-12）
- [x] 无 key 全链路可跑（SHOULD-11；5H 真实 LLM 实测即无 Jev key 环境全链路证据）
- [x] rank_components 进 RETRIEVING 主链；缓存键含阈值配置 hash（MUST-14）
- [x] RANKING 态流转真实发生（状态机断言）
- [x] GET /preference 返回 L3 真实向量；feedback 后向量变化
- [x] PUT /preference 与 /history 维持 501/9004
- [x] uvicorn 真实冒烟：optimize 三套+推荐标记；escape 单套 A 无 ranking（6.5）

## 生死线与收口
- [x] measure_ranking 100 条全量跑（5 仓 × 20 条，2026-10-11 单进程完整运行）
- [x] 报告标注「LLM 排序准确率」（不与 Jev 混用；metric_source 字段落档）
- [x] 主流程复跑判定——**结果 58/100 = 58% ＜ 80%，未达标**（干净测量：无 402/429 污染；10 条基础设施 error 诚实计 MISS，最好上限 68% 仍不达标；前日 27% 测量因 DeepSeek 余额中途耗尽作废）
- [x] 失败案例逐条归因（eval/recall/report-ranking-2026-10-11.md：分仓分布 + error 审计 + 规模负相关机制；32 条真实 MISS 逐条明细保留于同日 JSON details 字段）
- [x] 真源 §1 阶段五状态 + §13 变更记录更新（2026-10-11）
- [x] F-202 三处空规格补全确认（T5-11②：TYPESAFE_API_KEY / jev-1.13.0 / 0.5×2^n 退避）
- [x] <80% 时：停止、上报、等用户甲/乙裁决（MUST-25）——用户 2026-10-11 裁决**方案甲**：LLM 决策转正，价值主张改「LLM 决策 + ripgrep 精确取证」，Jev 路径 dormant 保留待重测
