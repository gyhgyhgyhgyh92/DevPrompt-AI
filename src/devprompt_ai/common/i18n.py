"""后端静态文案的本地化（2026-11-06，F-209 后端双语）。

为什么放 ``common/``：文案表是纯数据、``tr`` 是纯查表，不含任何业务判定；``domain/``
与 ``service`` 都可 import（与 ``common.text`` 同类先例，MUST-06），HTTP 层只负责把
``Accept-Language`` 解析成 ``Locale`` 再往下传。

约定：
- 键用扁平点号前缀（``progress.symbols`` / ``gate.red.no_target``），按模块分组；
- 只放静态文本，**禁止**拼用户原句或绝对路径（MUST-19）；
- 缺键返回键名本身，便于测试暴露漏译，不抛异常打断交付。
"""

from __future__ import annotations

from typing import Final, Literal

Locale = Literal["zh-CN", "en"]

DEFAULT_LOCALE: Final[Locale] = "zh-CN"

#: 两语言键集必须完全一致，由 tests/test_i18n.py 强制。
MESSAGES: Final[dict[str, dict[str, str]]] = {
    "zh-CN": {
        "progress.retrieval": "开始分析这条提示词，先在你的项目里检索相关代码。",
        "progress.symbols": "符号表就绪，共 {total} 个符号参与匹配。",
        "progress.candidates_trimmed": (
            "匹配到 {matched} 个相关符号，按相关度压到 {kept} 条候选（上限固定）。"
        ),
        "progress.candidates_all": "匹配到 {matched} 个相关符号，全部进入候选（未触及上限）。",
        "progress.manual_required": (
            "只匹配到 {matched} 个符号，不足以自动定位目标，"
            "需要你补充具体符号名或文件路径后再继续。"
        ),
        "progress.target": "选中目标 {name}（{location}），正在核对事实依据。",
        "progress.facts": "事实核对完成：{total} 项中 {passed} 项通过。",
        "progress.clarification": "研判出 {count} 处信息缺口，先和你确认再继续。",
        "progress.answering": "正在回答你的追问。",
        "progress.generation": "正在生成方案。",
        "common.list_sep": "、",
        "clarify.manual_reason": "候选不足（{matched} 条）",
        "clarify.manual_ask": "请指明目标符号名与文件路径（格式：符号@路径）",
        "gate.red.no_target": "未定位到目标符号",
        "gate.red.facts_failed": "适用事实全部未通过",
        "gate.red.claims_undeclared": "方案未声明任何引用，证据链无法核对",
        "gate.red.anchor_invalid": "方案含 {count} 处无效锚点（路径不存在或行号越界）",
        "gate.red.structural_sections": "方案正文缺少四段式结构（小标题不齐）",
        "gate.red.structural_deliverables": "changes 交付物清单为空",
        "gate.red.structural_placeholder": "正文残留 {count} 处占位符（待补充/TODO 等）",
        "gate.disclosure.red": (
            "本轮证据链不足以背书，方案照常提供，但相关缺口须如实留痕：{reasons}。"
        ),
        "gate.yellow.coverage": "断言覆盖率 {coverage}，低于 {threshold}",
        "gate.yellow.impact_uncovered": "影响半径内 {count} 个关联文件未被方案覆盖",
        "gate.disclosure.yellow": "本轮证据可用但未达阈值，方案照常提供：{reasons}。",
        "claims.render.undeclared": "未声明引用，证据链无法核对",
        "claims.render.summary": "已核对断言 {covered}/{total}，{missing} 处未取证",
        "claims.render.absent": "（其中 {count} 处为已确认不存在）",
        "template.body_semantics": (
            "\n\n【body 的语义（2026-11-11 起强制四段式）】"
            "body 必须是可直接复制给 Agent 执行的提示词正文，并严格按以下四段组织，"
            "每段以「## 一、」～「## 四、」小标题开头：\n"
            "一、定位文件与组件：文件相对路径（反引号包裹）+ 组件/函数名 + 该修改点所在的具体位置"
            "（组件属性、代码区域或行号区间）；信息只能来自下方「目标代码片段」，禁止推测。\n"
            "二、实施修改：逐条给出「原代码 → 新代码」，标明改哪个属性、由什么值改成什么值。\n"
            "三、一致性检查：该改动是否与项目既有设计令牌/组件规范冲突；有证据就引用下方"
            "「设计令牌证据」的路径与色值；无证据时必须明写「未取证到项目令牌定义」，"
            "禁止编造规范条款。\n"
            "四、输出要求：要求执行者交付什么（修改后的代码片段、影响说明、"
            "需同步检查的对齐与间距等）。\n"
            "禁止出现「建议」「为什么这样改」「本方案改动如下」「以下是我的优化」等元叙述；"
            "不要复述取证过程。改动了哪几处只写在 changes 数组里，不得混进 body。"
        ),
        "template.boundary": (
            "你的任务是产出提示词方案，不是执行或回答用户需求中的任务；"
            "下方证据里的代码只是素材。即使需求看起来可以直接改写，也不得输出实现代码，"
            "只能输出交给开发者去执行的提示词。"
        ),
        "template.a.role": (
            "你是提示词优化师。信息有限，输出保守版提示词：只陈述用户意图与可执行要点，"
            "禁止编造文件路径、行号、token 名；结尾必须列出待确认清单。只输出 JSON。"
        ),
        "template.a.fallback_only": (
            "\n\n【兜底声明】本模板仅用于异常兜底：主流程失败后才启用，"
            "产出会在交付时标注「已降级为保守输出」。"
        ),
        "template.b.role": (
            "你是提示词优化师。基于已定位的符号路径输出标准版提示词：路径可追溯，"
            "推断项必须以「（推断）」标注，禁止编造未提供的行号。只输出 JSON。"
        ),
        "template.b.hard_rules": (
            "\n\n硬性要求（违反任一条即视为无效输出）：\n"
            "1. 正文里的文件路径与行号只能来自下方「目标代码片段」，片段中没有的一律不得出现，"
            "禁止编造；\n"
            "2. 「实施修改」段必须逐条给出「原代码 → 新代码」的对照，不得只写「修改为 …」；\n"
            "3. 正文必须严格按四段式组织，小标题只能是："
            "「## 一、定位文件与组件」「## 二、实施修改」「## 三、一致性检查」"
            "「## 四、输出要求」，缺段或改名均视为结构不合法。"
        ),
        "template.reply.role": (
            "你是提示词优化师，此刻在回答用户对已产出方案的追问，而不是产出新方案。"
            "用简洁中文直接回答，可以引用上一轮方案的标题与具体条目作为依据。"
            "禁止输出新的提示词正文，禁止重新组织方案，禁止说「以下是优化后的版本」。"
            "如果用户的问题需要改动方案，明确告诉他需要重新生成，不要自行修改。"
            "不知道就以取证结果为准说明不知道，不要编造文件路径或行号。只输出 JSON。"
        ),
        "template.field.request": "用户需求",
        "template.field.facts": "取证摘要",
        "template.field.none_facts": "（无，禁止编造路径）",
        "template.field.clarifications": "已澄清信息",
        "template.field.conservative": "保守模式",
        "template.field.followup": "用户追问",
        "template.field.previous_variants": "上一轮方案",
        "template.field.none_variants": "（无，本轮之前还没有产出方案）",
        "template.field.ranking": "推荐判定",
        "template.field.none_ranking": "（上一轮未打分或未推荐）",
        "template.field.none_facts_plain": "（无）",
        "template.field.history": "历史轮次",
        "template.field.none_history": "（首轮，无历史）",
        "template.instruction_prefix": "请输出 JSON：",
        "template.claims_rules": (
            "claims 规则：正文里每一处文件路径、符号名、行号、样式 token 引用都要逐条声明，"
            "target 必须与正文原文完全一致；kind=line 时写成「路径:行号」。"
            "若正文明确断言某类引用**不存在**（例如「未找到可用的颜色 token」），"
            "用 kind=absence 并在 negates 里填被否定的类别（file/symbol/token/line/test）。"
            "没有引用就给空数组，禁止编造。"
        ),
        "template.field.domain": "领域指令",
        "template.b.hard_rules_generic": (
            "\n\n硬性要求（违反任一条即视为无效输出）：\n"
            "1. 正文里的细节只能来自下方证据，证据中没有的一律标注（推断），禁止编造；\n"
            "2. 正文必须严格按四段式组织，小标题与各段内容以下方「body 的语义」为准，"
            "缺段或改名均视为结构不合法。"
        ),
        "template.claims_rules_generic": (
            "claims 规则：本领域不依赖代码仓库证据，无需声明代码断言，claims 给空数组即可；"
            "changes 数组必须逐条列出交付物清单，每一项对应正文中的一个可执行产出。"
        ),
        "template.field.memory": "项目记忆",
        "template.field.excerpt": "目标代码片段（行号|内容）",
        "template.field.design_tokens": "设计令牌证据",
        "template.field.none_excerpt": "（未定位到代码片段，禁止编造行号）",
        "template.field.none_design_tokens": "（未找到项目设计令牌定义）",
        "template.sections.a": (
            "\n\n兜底模板四段式：第一段写「未能定位具体文件」；第二段只写意图层面的动作，"
            "并逐条标「待确认」；第三段写「无令牌证据」；第四段改为「待确认清单」。"
        ),
        "template.sections.b": (
            "\n\n标准模板四段式：第一段必须给出文件相对路径（来自片段头）；"
            "第二段允许以「（推断）」标注未证实的细节；"
            "第三段无令牌证据时必须明说「未取证到项目令牌定义」。"
        ),
        "domain.code.name": "代码工程",
        "domain.code.repo_required": "代码领域需要项目路径：请选择目标项目目录后再提交。",
        "domain.detected": "已识别领域：{name}。",
        "domain.fallback_notice": (
            "未能确定所属领域，已按「工作事务」领域处理；如不符可换一种说法重试。"
        ),
        "domain.work.name": "工作事务",
        "domain.life.name": "生活事务",
        "domain.creative.name": "创意创作",
        "domain.work.directives": (
            "【领域指令：工作事务】\n"
            "术语与表达规范：汇报/周报类须包含「进展、数据结果、风险与求助」三要素；"
            "方案/文档类须先明确受众与用途；数据分析须写明数据口径与结论依据。\n"
            "约束补全规则：未指明输出格式时默认 Markdown 结构化文本；"
            "未指明时间范围时按「本周」处理并标注（推断）；"
            "数字指标必须注明来源，无来源标（待确认）。\n"
            "交付标准：产出可直接粘贴使用，含明确的下一步行动项；"
            "禁止「以下是为你写的」等元叙述。"
        ),
        "domain.work.sections": (
            "\n\n【body 的语义（工作事务四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按以下四段组织，每段以「## 一、」～「## 四、」小标题开头：\n"
            "一、目标与背景：要完成什么、给谁看、什么场景使用；缺失信息以（推断）标注。\n"
            "二、任务拆解：把需求拆成有序步骤或文档骨架，每步给出可执行动作。\n"
            "三、规范与约束：本场景的专业表达规范与格式要求，引用下方「领域指令」；"
            "不得编造公司内部制度。\n"
            "四、交付标准：交付物清单与验收口径（可直接粘贴的正文、格式与篇幅、需附的数据）。\n"
            "禁止出现「建议」「本方案如下」等元叙述；改动了什么只写在 changes 数组里。"
        ),
        "domain.life.directives": (
            "【领域指令：生活事务】\n"
            "术语与表达规范：行程类须含时间轴与备选方案；采购类须含清单与预算区间；"
            "健康/饮食类须标注「非专业建议」，涉及医疗时提示咨询专业人士。\n"
            "约束补全规则：未指明预算/人数/时间时按单人、常见档位处理并标注（推断）；"
            "推荐项须给出选择理由与替代项。\n"
            "交付标准：产出为可直接执行的清单或时间表；涉及金额给出预算区间而非精确数。"
        ),
        "domain.life.sections": (
            "\n\n【body 的语义（生活事务四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按以下四段组织，每段以「## 一、」～「## 四、」小标题开头：\n"
            "一、需求场景：要办什么事、什么时间、几个人；缺失信息以（推断）标注。\n"
            "二、方案要点：给出主方案与备选，说明取舍理由。\n"
            "三、注意事项：预算、时间、安全与合规约束，引用下方「领域指令」。\n"
            "四、执行清单：可直接照做的步骤清单（时间表/采购清单/待办项）。\n"
            "禁止出现「建议」「本方案如下」等元叙述；改动了什么只写在 changes 数组里。"
        ),
        "domain.creative.directives": (
            "【领域指令：创意创作】\n"
            "术语与表达规范：文案类区分「主标题/副标题/正文」；脚本类须含场景与台词格式；"
            "命名类须给出语义依据与候选清单。\n"
            "约束补全规则：未指明风格/受众/平台时按通用大众风格处理并标注（推断）；"
            "同一需求给 2-3 个差异化方向而非单点。\n"
            "交付标准：产出直接可用成稿；附一句话创意说明（创意点是什么）；"
            "禁止只给方向不给成稿。"
        ),
        "domain.creative.sections": (
            "\n\n【body 的语义（创意创作四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按以下四段组织，每段以「## 一、」～「## 四、」小标题开头：\n"
            "一、创意定位：主题、受众、平台与调性；缺失信息以（推断）标注。\n"
            "二、成稿正文：直接给出可用成稿（文案/故事/脚本），按领域格式组织。\n"
            "三、风格与禁忌：调性、长度、平台规范，引用下方「领域指令」。\n"
            "四、备选与延展：差异化备选方向与后续可延展点。\n"
            "禁止出现「建议」「本方案如下」等元叙述；改动了什么只写在 changes 数组里。"
        ),
        "domain.learning.name": "学习教育",
        "domain.learning.directives": (
            "【领域指令：学习教育】\n"
            "术语与表达规范：教案须含教学目标/重难点/课时安排；讲解须由浅入深并给例子；"
            "复习计划须按考试日期倒排并标注（推断）。\n"
            "约束补全规则：未指明学习者水平时按入门处理并标注（推断）；"
            "知识点必须给出权威出处或标注「通用通识」。\n"
            "交付标准：产出可直接使用的讲义/计划/题单，每部分附自查清单。"
        ),
        "domain.learning.sections": (
            "\n\n【body 的语义（学习教育四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按四段组织（一、目标与学习者画像；二、内容拆解与讲解路径；"
            "三、教学规范与常见误区，引用下方「领域指令」；四、交付标准与自查清单）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
        "domain.data.name": "数据分析",
        "domain.data.directives": (
            "【领域指令：数据分析】\n"
            "术语与表达规范：结论必须绑定数据口径（时间窗/样本/去重规则）；"
            "指标须写明计算公式；对比须给出基准与差值。\n"
            "约束补全规则：未指明数据来源时按「用户提供的数据」处理并标注（待确认）；"
            "统计结论须区分相关与因果。\n"
            "交付标准：产出含「数据口径、分析步骤、图表建议、结论与局限」四要素，"
            "数字须可复算。"
        ),
        "domain.data.sections": (
            "\n\n【body 的语义（数据分析四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按四段组织（一、分析目标与数据口径；二、分析步骤与计算口径；"
            "三、图表与呈现规范，引用下方「领域指令」；四、结论、局限与复核清单）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
        "domain.marketing.name": "文案营销",
        "domain.marketing.directives": (
            "【领域指令：文案营销】\n"
            "术语与表达规范：文案须含目标人群与转化目标；渠道内容须符合平台规范"
            "（公众号/小红书/抖音各有格式与字数习惯）。\n"
            "约束补全规则：未指明渠道时默认通用社媒长文案并标注（推断）；"
            "卖点须基于用户提供信息，不得虚构数据。\n"
            "交付标准：产出含主文案 + 备选标题 + 渠道适配说明，可直接发布。"
        ),
        "domain.marketing.sections": (
            "\n\n【body 的语义（文案营销四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按四段组织（一、产品/活动定位与目标人群；二、成稿正文与投放版本；"
            "三、渠道规范与合规红线，引用下方「领域指令」；四、发布清单与效果指标）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
        "domain.translation.name": "翻译本地化",
        "domain.translation.directives": (
            "【领域指令：翻译本地化】\n"
            "术语与表达规范：专业术语首次出现附原文；专有名词保留原文并附通行译法；"
            "译文须符合目标语言的表达习惯而非逐字直译。\n"
            "约束补全规则：未指明目标语言时按英文处理并标注（推断）；"
            "文化特有内容须给出本地化改写建议。\n"
            "交付标准：产出「译文全文 + 术语对照表 + 译者注（存疑处）」。"
        ),
        "domain.translation.sections": (
            "\n\n【body 的语义（翻译本地化四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按四段组织（一、翻译目标与语向；二、译文全文；"
            "三、术语与风格规范，引用下方「领域指令」；四、术语对照表与译者注）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
        "domain.legal.name": "法律合同",
        "domain.legal.directives": (
            "【领域指令：法律合同】\n"
            "术语与表达规范：合同条款须含主体/标的/价款/期限/违约责任/争议解决六要素；"
            "引用法条须写明全称并标注「请以现行有效版本为准」。\n"
            "约束补全规则：未指明司法辖区时标注（推断）并提示咨询当地律师；"
            "不得出具确定性法律意见，输出属文本草案。\n"
            "交付标准：产出可直接进入审阅的条款文本，每条附「条款目的」注释。"
        ),
        "domain.legal.sections": (
            "\n\n【body 的语义（法律合同四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按四段组织（一、合同背景与主体；二、条款正文；"
            "三、法律表达规范与风险提示，引用下方「领域指令」；四、签署与存档清单）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
        "domain.medical.name": "医疗健康",
        "domain.medical.directives": (
            "【领域指令：医疗健康】\n"
            "术语与表达规范：症状描述须含部位/持续时间/程度/诱因；"
            "所有输出必须标注「非医疗建议，请咨询执业医师」。\n"
            "约束补全规则：未指明人群时按成年人处理并标注（推断）；"
            "不得给出剂量处方，用药信息仅复述用户已提供内容。\n"
            "交付标准：产出为就诊准备材料（症状时间线/问题清单/检查记录整理）。"
        ),
        "domain.medical.sections": (
            "\n\n【body 的语义（医疗健康四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按四段组织（一、基本情况与症状时间线；二、就诊准备材料；"
            "三、信息整理规范与安全边界，引用下方「领域指令」；四、与医生沟通的问题清单）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
        "domain.finance.name": "金融财务",
        "domain.finance.directives": (
            "【领域指令：金融财务】\n"
            "术语与表达规范：金额须带币种与单位；报表类须注明会计准则（如适用）；"
            "计算过程须列出公式与口径。\n"
            "约束补全规则：未指明期间时按自然月/年处理并标注（推断）；"
            "投资类输出必须附「不构成投资建议」提示。\n"
            "交付标准：产出含「口径说明、计算明细、结论与风险提示」，数字可复核。"
        ),
        "domain.finance.sections": (
            "\n\n【body 的语义（金融财务四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按四段组织（一、业务背景与口径；二、核算明细与公式；"
            "三、财务表达规范与合规提示，引用下方「领域指令」；四、结论与复核清单）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
        "domain.game.name": "游戏设计",
        "domain.game.directives": (
            "【领域指令：游戏设计】\n"
            "术语与表达规范：玩法描述须含核心循环/目标/反馈；数值须给公式与基准曲线；"
            "剧情须写清触发条件与分支。\n"
            "约束补全规则：未指明平台时按移动端处理并标注（推断）；"
            "未指明类型时按用户描述就近归类并标注（推断）。\n"
            "交付标准：产出可直接进入策划案评审的设计文档片段，含反例与边界情况。"
        ),
        "domain.game.sections": (
            "\n\n【body 的语义（游戏设计四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按四段组织（一、设计目标与核心体验；二、玩法与数值设计；"
            "三、设计规范与平衡性约束，引用下方「领域指令」；四、验收标准与测试要点）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
        "domain.av.name": "音视频脚本",
        "domain.av.directives": (
            "【领域指令：音视频脚本】\n"
            "术语与表达规范：脚本须按「镜头/时长/画面/台词/音效」五列组织；"
            "口播稿须标注语速与停顿；分镜须写明景别与转场。\n"
            "约束补全规则：未指明时长时按 1 分钟口播处理并标注（推断）；"
            "未指明平台时按通用短视频处理并标注（推断）；"
            "原句中的硬约束（时长、平台、受众、口播风格、显式禁止项）"
            "与 {{变量占位符}} 必须逐字保留，不得改写、概括或删除。\n"
            "交付标准：产出可直接开拍的分镜脚本或可录制的口播稿。"
        ),
        "domain.av.sections": (
            "\n\n【body 的语义（音视频脚本四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按四段组织（一、主题与受众与时长；二、脚本正文（分镜表或口播稿）；"
            "三、制作规范与平台要求，引用下方「领域指令」；四、拍摄/录制清单）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
        "domain.visual.name": "视觉生成",
        "domain.visual.directives": (
            "【领域指令：视觉生成】\n"
            "术语与表达规范：提示词用层次化自然语言描述——主体特征、动作与互动、环境锚点、"
            "构图与视角、光线与时间、色彩与材质、氛围与情绪；不堆砌关键词标签；"
            "按目标工具（Midjourney/即梦/Sora/可灵等）的语法习惯组织，正文即最终可粘贴的提示词。\n"
            "约束补全规则：硬约束（画幅、比例、方向、尺寸、数量、标题与可读文字、镜头/媒介、"
            "输出格式、显式禁止项）必须逐字保留，不得改写、概括或删除；"
            "{{变量占位符}} 逐字保留，不改名不替换；画幅、比例、风格或目标工具未指明时先反问，"
            "无法反问则按 1:1 通用风格处理并标注（推断）。\n"
            "交付标准：正文为可直接粘贴的完整提示词；目标工具支持参数块/负面清单时按其语法附上；"
            "不产出代码路径或行号锚点。"
        ),
        "domain.visual.sections": (
            "\n\n【body 的语义（视觉生成四段式）】body 必须是可直接复制使用的指令正文，"
            "严格按四段组织（一、主题与用途与目标工具；二、提示词正文；"
            "三、视觉规格与硬约束清单（比例/画幅/文字/数量/排除项），引用下方「领域指令」；"
            "四、使用说明与可调参数建议）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
        "domain.visual.style.general": (
            "【视觉风格：通用】\n"
            "术语与表达规范：用 3–6 句连贯自然语言，按「主体特征→动作与互动→环境锚点→"
            "构图与视角→光线与时间→色彩与材质→氛围与情绪」分层组织；"
            "不堆砌关键词标签，不使用参数或权重语法。\n"
            "约束补全规则：硬约束（画幅、比例、方向、尺寸、数量、标题与可读文字、镜头/媒介、"
            "输出格式、显式禁止项）与 {{变量占位符}} 逐字保留；"
            "未指明画幅时按 1:1 处理并标注（推断）。\n"
            "交付标准：正文即完整可粘贴提示词；目标工具支持参数块/负面清单时按其语法附上。"
        ),
        "domain.visual.style.photography": (
            "【视觉风格：摄影向】\n"
            "术语与表达规范：用摄影语言描述——镜头（景别、景深、焦段感觉）、"
            "光线（方向、软硬、色温、时段）、构图（三分法、对称、引导线、负空间）、"
            "质感（颗粒、纹理、材质反光）；强调可视细节而非相机参数堆砌。\n"
            "约束补全规则：摄影化补充只增强镜头、光线与质感，"
            "不得覆盖、弱化或替代原始硬约束与 {{变量占位符}}；"
            "润色后无自然位置的约束保留在规格段。\n"
            "交付标准：主体清晰、光线明确、构图稳定的摄影级提示词。"
        ),
        "domain.visual.style.creative": (
            "【视觉风格：创意解构】\n"
            "术语与表达规范：把描述解构到核心意象，再以想象力重塑为奇幻视觉叙事；"
            "构建自洽的视觉语言而非依赖现成符号体系；"
            "升华后仍能辨识原始核心意象。\n"
            "约束补全规则：禁止空洞的宏大词汇堆砌与浅层概念替换；"
            "原始硬约束与 {{变量占位符}} 在重构中逐字保留。\n"
            "交付标准：独特、具体、可视的创意提示词，核心意象可追溯。"
        ),
        "domain.visual.style.chinese-model": (
            "【视觉风格：中文美学】\n"
            "术语与表达规范：以中文美学组织提示词——意境、留白、节奏与含蓄；"
            "可融入中式色彩与材质（如官绿、朱砂、宣纸、绢丝）；"
            "常见风格词汇：水墨、工笔、青绿山水、传统纹样。\n"
            "约束补全规则：中式美学强化只增强表达，不得覆盖原始硬约束与 {{变量占位符}}；"
            "文化元素须服务原始主题，不得喧宾夺主。\n"
            "交付标准：氛围与象征优先于技术参数的中文语境提示词。"
        ),
        "domain.visual.style.json-structured": (
            "【视觉风格：JSON 结构化】\n"
            "术语与表达规范：把描述改写为一个结构化提示词对象——键名与键值均用中文；"
            "字段覆盖场景、主体、环境、动作、构图、相机、光照、色彩、风格等维度，按需增删。\n"
            "约束补全规则：若输入已是结构化对象，沿用其字段层级与键语义，"
            "顶层键集合保持不变，只在原位补充细化；"
            "{{变量占位符}} 逐字保留在语义对应位置，不得吞掉或漂移。\n"
            "交付标准：提示词正文输出该结构化对象本身，对象外部不附加解释文字。"
        ),
        "domain.visual.style.video": (
            "【视觉风格：视频生成】\n"
            "术语与表达规范：按「画面描述→镜头语言→时长与节奏→镜头衔接→声音提示」组织；"
            "镜头语言用推、拉、摇、移、跟、手持、固定等；多镜头任务按镜头顺序编号，"
            "写明每镜内容与衔接方式（硬切/叠化/转场）；适配 Sora/即梦/可灵/Runway 语法。\n"
            "约束补全规则：时长未指明按 5 秒单镜头处理并标注（推断）；"
            "画幅、比例、镜头数、字幕文字等硬约束与 {{变量占位符}} 逐字保留。\n"
            "交付标准：正文即完整可粘贴的视频提示词；支持参数块的工具按其语法附上。"
        ),
        "domain.operations.name": "运营策划",
        "domain.operations.directives": (
            "【领域指令：运营策划】\n"
            "术语与表达规范：活动方案须含目标/人群/机制/时间线/风险预案；"
            "增长策略须区分拉新/促活/留存/转化并给出指标。\n"
            "约束补全规则：未指明预算与周期时按小成本单周活动处理并标注（推断）；"
            "玩法不得违反平台规则，须附合规自查点。\n"
            "交付标准：产出可直接排期执行的活动方案，含分工与复盘口径。"
        ),
        "domain.operations.sections": (
            "\n\n【body 的语义（运营策划四段式）】body 必须是可直接复制给执行 Agent 的指令正文，"
            "严格按四段组织（一、目标与人群与资源；二、活动机制与时间线；"
            "三、运营规范与合规红线，引用下方「领域指令」；四、分工、指标与复盘口径）。"
            "缺失信息以（推断）标注；禁止元叙述。"
        ),
    },
    "en": {
        "progress.retrieval": (
            "Analyzing this prompt; first retrieving related code from your project."
        ),
        "progress.symbols": "Symbol table ready: {total} symbols are matched.",
        "progress.candidates_trimmed": (
            "Matched {matched} related symbols; kept {kept} candidates by relevance (fixed cap)."
        ),
        "progress.candidates_all": (
            "Matched {matched} related symbols; all of them entered the candidates (cap not hit)."
        ),
        "progress.manual_required": (
            "Only {matched} symbols matched, which is not enough to locate the target "
            "automatically; please add a specific symbol name or file path to continue."
        ),
        "progress.target": (
            "Target selected: {name} ({location}); verifying the supporting facts."
        ),
        "progress.facts": "Fact checks finished: {passed} of {total} passed.",
        "progress.clarification": (
            "Found {count} information gaps; confirming them with you before continuing."
        ),
        "progress.answering": "Answering your follow-up question.",
        "progress.generation": "Generating the plan.",
        "common.list_sep": ", ",
        "clarify.manual_reason": "Not enough candidates ({matched} matched)",
        "clarify.manual_ask": (
            "Please specify the target symbol and file path (format: symbol@path)"
        ),
        "gate.red.no_target": "Target symbol not located",
        "gate.red.facts_failed": "Every applicable fact check failed",
        "gate.red.claims_undeclared": (
            "The plan declares no references, so the evidence chain cannot be verified"
        ),
        "gate.red.anchor_invalid": (
            "The plan contains {count} invalid anchor(s) (missing path or line out of range)"
        ),
        "gate.red.structural_sections": (
            "The plan body lacks the four-section structure (headings incomplete)"
        ),
        "gate.red.structural_deliverables": ("The changes array lists no deliverables"),
        "gate.red.structural_placeholder": (
            "The body still contains {count} placeholder(s) (to-be-filled/TODO etc.)"
        ),
        "gate.disclosure.red": (
            "Evidence is not strong enough to endorse this turn; the plan is still "
            "provided, and the gaps are disclosed below: {reasons}."
        ),
        "gate.yellow.coverage": ("Claim coverage {coverage} is below the required {threshold}"),
        "gate.yellow.impact_uncovered": (
            "{count} file(s) in the impact radius are not covered by the plan"
        ),
        "gate.disclosure.yellow": (
            "Evidence is usable but below the required threshold; "
            "the plan is still provided: {reasons}."
        ),
        "claims.render.undeclared": "No references declared; the evidence chain cannot be verified",
        "claims.render.summary": "Verified {covered}/{total} claims, {missing} unverified",
        "claims.render.absent": " ({count} confirmed absent)",
        "template.body_semantics": (
            "\n\n[Semantics of `body` (four mandatory sections since 2026-11-11)] `body` must be "
            "a prompt an Agent can execute as-is, and must follow exactly these four sections, "
            "each starting with a `## 1.`-style heading:\n"
            "1. File and component location: repo-relative file path (in backticks) + "
            "component/function name + where exactly the change goes (enclosing component prop, "
            "code region, or line range). Take this only from the target code excerpt below; "
            "never guess.\n"
            "2. Change to apply: for each item give `original code -> new code`, naming which "
            "attribute changes and from what value to what value.\n"
            "3. Consistency check: whether the change conflicts with the project's existing "
            "design tokens or component conventions. If evidence exists, cite the path and color "
            "value from the design-token evidence below; if not, state explicitly that no project "
            "token definition was found. Never invent convention clauses.\n"
            "4. Deliverables: what the executor must hand back (the modified code snippet, impact "
            "notes, alignment and spacing that need re-checking).\n"
            'No meta narration such as "suggestion", "why this change", "the changes are as '
            'follows", or "here is my optimization"; do not restate the probing process. Which '
            "spots changed belongs in the `changes` array only, never inside `body`."
        ),
        "template.boundary": (
            "Your job is to produce prompt plans, not to execute or answer the user's task; "
            "the code in the evidence below is material only. Even if the request looks "
            "directly implementable, you must not output implementation code — only the "
            "prompt to be handed to the developer."
        ),
        "template.a.role": (
            "You are a prompt engineer. Information is limited, so produce a conservative "
            "prompt: state only the user's intent and actionable points; never invent file "
            "paths, line numbers, or token names; end with a must-confirm list. "
            "Output JSON only."
        ),
        "template.b.role": (
            "You are a prompt engineer. Based on the located symbol paths, produce a standard "
            'prompt: paths must be traceable; label inferences with "(inferred)"; never '
            "invent line numbers that were not provided. Output JSON only."
        ),
        "template.b.hard_rules": (
            "\n\nHard requirements (violating any one makes the output invalid):\n"
            "1. File paths and line numbers in the body may come only from the target code "
            "excerpt below; anything absent from the excerpt must not appear — never fabricate;\n"
            "2. Section 2 must give an `original code -> new code` pair for every change, not "
            'just "change it to ...";\n'
            "3. The body must use exactly these four headings: `## 1. Locate the file and "
            "component`, `## 2. Apply the change`, `## 3. Consistency check`, "
            "`## 4. Deliverables`. Missing or renamed sections make the structure invalid."
        ),
        "template.a.fallback_only": (
            "\n\n[Fallback notice] This template is used only as an exception fallback: it runs "
            "after the main path fails, and the result is disclosed as a downgraded conservative "
            "output."
        ),
        "template.reply.role": (
            "You are a prompt engineer answering a follow-up question about plans already "
            "produced, not producing a new plan. Answer concisely and directly in the same "
            "language as the question; you may cite the previous plan's title and "
            "specific items as evidence. Do not output new prompt text, do not reorganize the "
            'plan, and never say "here is the optimized version". If the question requires '
            "changing the plan, tell the user to regenerate instead of editing it yourself. "
            "When you do not know, say so based on the evidence — never invent paths or line "
            "numbers. Output JSON only."
        ),
        "template.field.request": "user_request",
        "template.field.facts": "evidence_summary",
        "template.field.none_facts": "(none; never invent paths)",
        "template.field.clarifications": "clarifications",
        "template.field.conservative": "conservative_mode",
        "template.field.followup": "follow_up_question",
        "template.field.previous_variants": "previous_variants",
        "template.field.none_variants": "(none; no plan has been produced yet)",
        "template.field.ranking": "ranking_verdict",
        "template.field.none_ranking": "(not scored or not recommended last turn)",
        "template.field.none_facts_plain": "(none)",
        "template.field.history": "conversation_history",
        "template.field.none_history": "(first turn; no history)",
        "template.instruction_prefix": "Output JSON only: ",
        "template.claims_rules": (
            "claims rules: every file path, symbol name, line number, and style-token "
            "reference in the body must be declared one by one, and target must match the body "
            'text exactly; for kind=line use "path:line". If the body explicitly asserts that '
            'some reference does NOT exist (for example "no usable colour token was found"), '
            "use kind=absence and put the negated category in negates "
            "(file/symbol/token/line/test). Emit an empty array when there are no references; "
            "never fabricate."
        ),
        "template.field.domain": "domain_directives",
        "template.b.hard_rules_generic": (
            "\n\nHard requirements (violating any one makes the output invalid):\n"
            "1. Details in the body may only come from the evidence below; anything missing "
            "from it must be marked (inferred); never fabricate.\n"
            "2. The body must follow the four-section structure exactly; headings and section "
            'content follow "the semantics of body" below; a missing or renamed section is '
            "structurally invalid."
        ),
        "template.claims_rules_generic": (
            "claims rules: this domain does not rely on repository evidence, so no code "
            "assertions are needed — emit an empty array; the changes array must list the "
            "deliverables one by one, each corresponding to an executable output in the body."
        ),
        "template.field.memory": "project_memory",
        "template.field.excerpt": "target_code_excerpt (line|content)",
        "template.field.design_tokens": "design_token_evidence",
        "template.field.none_excerpt": "(no excerpt located; do not invent line numbers)",
        "template.field.none_design_tokens": "(no project design token definition found)",
        "template.sections.a": (
            "\n\nThe fallback template's four sections: section 1 states that no concrete file "
            'could be located; section 2 lists intent-level actions each marked "to confirm"; '
            'section 3 states "no token evidence"; section 4 becomes a must-confirm checklist.'
        ),
        "template.sections.b": (
            "\n\nThe standard template's four sections: section 1 must give the repo-relative file "
            "path (from the excerpt header); section 2 may mark unverified details with "
            '"(inferred)"; section 3 must say explicitly when no token evidence was found.'
        ),
        "domain.code.name": "Code Engineering",
        "domain.code.repo_required": (
            "The code domain requires a project path: choose the target project folder first."
        ),
        "domain.detected": "Domain detected: {name}.",
        "domain.fallback_notice": (
            'Could not determine the domain; handled as "Work Tasks". '
            "If that is wrong, rephrase and try again."
        ),
        "domain.work.name": "Work Tasks",
        "domain.life.name": "Daily Life",
        "domain.creative.name": "Creative Writing",
        "domain.work.directives": (
            "[Domain directives: work tasks]\n"
            "Terminology: reports/weekly updates must cover progress, data results, risks "
            "and asks; proposals/documents must state the audience and purpose first; data "
            "analysis must state the metric definitions and the basis of conclusions.\n"
            "Constraint completion: default to structured Markdown when no format is given; "
            'treat an unspecified time range as "this week" marked (inferred); every metric '
            "must cite its source, otherwise mark (to confirm).\n"
            "Delivery standard: output ready to paste, with explicit next actions; no "
            'meta narration such as "here is what I wrote for you".'
        ),
        "domain.work.sections": (
            "\n\n[Semantics of body (work-task four sections)] body must be an instruction "
            "ready to paste to the executing agent, organized in exactly four sections, "
            'each starting with the heading "## I." through "## IV.":\n'
            "I. Goal & context: what to do, for whom, in which scenario; mark missing "
            "details with (inferred).\n"
            "II. Task breakdown: split the request into ordered steps or a document "
            "skeleton, each step an executable action.\n"
            "III. Rules & constraints: professional expression and format norms of this "
            "scenario, citing the [Domain directives] below; never invent internal policies.\n"
            "IV. Delivery standard: deliverable list and acceptance criteria (paste-ready "
            "text, format and length, required data).\n"
            'No meta narration such as "suggestion" or "my plan is as follows"; what '
            "changed goes only into the changes array."
        ),
        "domain.life.directives": (
            "[Domain directives: daily life]\n"
            "Terminology: itineraries need a timeline with alternatives; shopping lists need "
            'items and a budget range; health/diet output must be marked "not professional '
            'advice" and refer medical questions to professionals.\n'
            "Constraint completion: assume one person and common budget tiers when budget/"
            "party size/time is unspecified, marked (inferred); every recommendation needs a "
            "reason and an alternative.\n"
            "Delivery standard: output an executable checklist or timetable; give budget "
            "ranges rather than exact amounts."
        ),
        "domain.life.sections": (
            "\n\n[Semantics of body (daily-life four sections)] body must be an instruction "
            "ready to paste to the executing agent, organized in exactly four sections, "
            'each starting with the heading "## I." through "## IV.":\n'
            "I. Scenario: what to arrange, when, for how many people; mark missing details "
            "with (inferred).\n"
            "II. Plan options: a primary plan plus alternatives, with trade-off reasons.\n"
            "III. Cautions: budget, timing, safety and compliance constraints, citing the "
            "[Domain directives] below.\n"
            "IV. Checklist: steps ready to follow (timetable / shopping list / to-dos).\n"
            'No meta narration such as "suggestion" or "my plan is as follows"; what '
            "changed goes only into the changes array."
        ),
        "domain.creative.directives": (
            "[Domain directives: creative writing]\n"
            "Terminology: copywriting distinguishes headline/subheading/body; scripts need "
            "scene and dialogue formatting; naming must give semantic rationale and a "
            "candidate list.\n"
            "Constraint completion: default to a general audience style when style/platform "
            "is unspecified, marked (inferred); give 2-3 differentiated directions rather "
            "than a single point.\n"
            "Delivery standard: paste-ready finished copy plus a one-sentence note of the "
            "creative idea; never deliver directions without finished copy."
        ),
        "domain.creative.sections": (
            "\n\n[Semantics of body (creative four sections)] body must be an instruction "
            "ready to paste to the executing agent, organized in exactly four sections, "
            'each starting with the heading "## I." through "## IV.":\n'
            "I. Creative positioning: theme, audience, platform and tone; mark missing "
            "details with (inferred).\n"
            "II. Finished copy: give the usable copy/story/script directly, organized per "
            "domain format.\n"
            "III. Style & taboos: tone, length, platform norms, citing the [Domain "
            "directives] below.\n"
            "IV. Alternatives & extensions: differentiated backup directions and future "
            "extension points.\n"
            'No meta narration such as "suggestion" or "my plan is as follows"; what '
            "changed goes only into the changes array."
        ),
        "domain.learning.name": "Learning & Education",
        "domain.learning.directives": (
            "[Domain directives: Learning & Education]\n"
            "Terminology: lesson plans must include objectives, key/difficult points and "
            "scheduling; explanations must progress from basics with examples.\n"
            "Completion: assume beginner level with (inferred) when unspecified; cite "
            "authoritative sources or mark as general knowledge.\n"
            "Delivery: usable handout/plan/problem set, each part with a self-check list."
        ),
        "domain.learning.sections": (
            "\n\n[Semantics of body (learning four sections)] body must be organized in "
            "exactly four sections (I. goals & learner profile; II. content breakdown & "
            "teaching path; III. teaching norms & common pitfalls, citing the [Domain "
            "directives] below; IV. delivery standard & self-check list). Mark missing "
            "details with (inferred); no meta narration."
        ),
        "domain.data.name": "Data Analysis",
        "domain.data.directives": (
            "[Domain directives: Data Analysis]\n"
            "Terminology: conclusions must bind to data scope (window/sample/dedup); "
            "metrics must state formulas; comparisons must state baseline and delta.\n"
            "Completion: assume user-provided data with (to confirm) when source is "
            "unspecified; distinguish correlation from causation.\n"
            "Delivery: output with scope, steps, chart suggestions, conclusions and "
            "limitations; numbers must be reproducible."
        ),
        "domain.data.sections": (
            "\n\n[Semantics of body (data four sections)] body must be organized in "
            "exactly four sections (I. goal & data scope; II. analysis steps & formulas; "
            "III. charting & presentation norms, citing the [Domain directives] below; "
            "IV. conclusions, limitations & review list). Mark missing details with "
            "(inferred); no meta narration."
        ),
        "domain.marketing.name": "Marketing Copy",
        "domain.marketing.directives": (
            "[Domain directives: Marketing Copy]\n"
            "Terminology: copy must state target audience and conversion goal; channel "
            "content must follow platform norms (format & length habits differ).\n"
            "Completion: default to generic long-form social copy with (inferred) when "
            "channel is unspecified; do not invent data beyond user input.\n"
            "Delivery: main copy + alternate headlines + channel adaptation notes, "
            "ready to publish."
        ),
        "domain.marketing.sections": (
            "\n\n[Semantics of body (marketing four sections)] body must be organized in "
            "exactly four sections (I. product/event positioning & audience; II. finished "
            "copy & channel variants; III. channel norms & compliance red lines, citing "
            "the [Domain directives] below; IV. publishing checklist & effect metrics). "
            "Mark missing details with (inferred); no meta narration."
        ),
        "domain.translation.name": "Translation & Localization",
        "domain.translation.directives": (
            "[Domain directives: Translation & Localization]\n"
            "Terminology: technical terms carry the original text on first occurrence; "
            "proper nouns stay in original with accepted translation; idiom over "
            "word-for-word.\n"
            "Completion: default target language is English with (inferred) when "
            "unspecified; culturally specific content needs localization notes.\n"
            "Delivery: full translation + glossary + translator notes (doubtful points)."
        ),
        "domain.translation.sections": (
            "\n\n[Semantics of body (translation four sections)] body must be organized "
            "in exactly four sections (I. goal & language pair; II. full translation; "
            "III. terminology & style norms, citing the [Domain directives] below; "
            "IV. glossary & translator notes). Mark missing details with (inferred); "
            "no meta narration."
        ),
        "domain.legal.name": "Legal & Contracts",
        "domain.legal.directives": (
            "[Domain directives: Legal & Contracts]\n"
            "Terminology: contract clauses must cover parties, subject, price, term, "
            "breach liability and dispute resolution; cited statutes must note "
            '"please verify the current effective version".\n'
            "Completion: mark jurisdiction as (inferred) and advise consulting local "
            "counsel; never issue definitive legal opinions — output is a draft.\n"
            "Delivery: clause text ready for review, each clause annotated with purpose."
        ),
        "domain.legal.sections": (
            "\n\n[Semantics of body (legal four sections)] body must be organized in "
            "exactly four sections (I. background & parties; II. clause text; III. legal "
            "drafting norms & risk notes, citing the [Domain directives] below; "
            "IV. signing & archive checklist). Mark missing details with (inferred); "
            "no meta narration."
        ),
        "domain.medical.name": "Health & Medical",
        "domain.medical.directives": (
            "[Domain directives: Health & Medical]\n"
            "Terminology: symptom descriptions must include location, duration, severity "
            "and triggers; all output must be marked "
            '"not medical advice — consult a licensed physician".\n'
            "Completion: assume adult with (inferred) when population is unspecified; "
            "never give dosage/prescriptions; only restate user-provided medication info.\n"
            "Delivery: visit-preparation material (symptom timeline, question list, "
            "organized records)."
        ),
        "domain.medical.sections": (
            "\n\n[Semantics of body (medical four sections)] body must be organized in "
            "exactly four sections (I. basics & symptom timeline; II. visit-preparation "
            "material; III. organizing norms & safety boundary, citing the [Domain "
            "directives] below; IV. questions for the physician). Mark missing details "
            "with (inferred); no meta narration."
        ),
        "domain.finance.name": "Finance & Accounting",
        "domain.finance.directives": (
            "[Domain directives: Finance & Accounting]\n"
            "Terminology: amounts must carry currency and unit; statements must note "
            "applicable accounting standards; calculations must show formulas and scope.\n"
            "Completion: default to calendar month/year with (inferred) when period is "
            "unspecified; investment output must carry a not-investment-advice notice.\n"
            "Delivery: scope, calculation detail, conclusions and risk notes; numbers "
            "must be verifiable."
        ),
        "domain.finance.sections": (
            "\n\n[Semantics of body (finance four sections)] body must be organized in "
            "exactly four sections (I. context & scope; II. calculation detail & "
            "formulas; III. financial norms & compliance notes, citing the [Domain "
            "directives] below; IV. conclusions & review checklist). Mark missing "
            "details with (inferred); no meta narration."
        ),
        "domain.game.name": "Game Design",
        "domain.game.directives": (
            "[Domain directives: Game Design]\n"
            "Terminology: gameplay must cover core loop, goals and feedback; numbers "
            "must give formulas and baseline curves; narrative must state triggers and "
            "branches.\n"
            "Completion: default to mobile with (inferred) when platform is unspecified; "
            "classify genre from the description with (inferred).\n"
            "Delivery: design-doc fragment ready for review, with counterexamples and "
            "edge cases."
        ),
        "domain.game.sections": (
            "\n\n[Semantics of body (game four sections)] body must be organized in "
            "exactly four sections (I. design goal & core experience; II. gameplay & "
            "numeric design; III. design norms & balance constraints, citing the [Domain "
            "directives] below; IV. acceptance standard & test points). Mark missing "
            "details with (inferred); no meta narration."
        ),
        "domain.av.name": "Audio & Video Script",
        "domain.av.directives": (
            "[Domain directives: Audio & Video Script]\n"
            "Terminology: scripts must use five columns (shot/duration/visual/line/"
            "sfx); voiceover must mark pace and pauses; storyboards must state framing "
            "and transitions.\n"
            "Completion: default to a 1-minute voiceover with (inferred) when duration "
            "is unspecified; default to generic short-video with (inferred) when "
            "platform is unspecified; hard constraints in the original sentence "
            "(duration, platform, audience, delivery style, explicit exclusions) and "
            "{{variable placeholders}} must be preserved verbatim.\n"
            "Delivery: storyboard ready to shoot or voiceover script ready to record."
        ),
        "domain.av.sections": (
            "\n\n[Semantics of body (av four sections)] body must be organized in "
            "exactly four sections (I. theme, audience & duration; II. script body "
            "(storyboard table or voiceover draft); III. production norms & platform "
            "requirements, citing the [Domain directives] below; IV. shooting/recording "
            "checklist). Mark missing details with (inferred); no meta narration."
        ),
        "domain.visual.name": "Visual Generation",
        "domain.visual.directives": (
            "[Domain directives: Visual Generation]\n"
            "Terminology: prompts use layered natural language — subject traits, "
            "actions & interactions, environmental anchors, composition & angle, "
            "light & time, color & texture, mood & atmosphere; no keyword stacking; "
            "follow the target tool's grammar (Midjourney/Jimeng/Sora/Kling etc.); "
            "body is the final paste-ready prompt.\n"
            "Completion: hard constraints (aspect ratio, orientation, size, count, "
            "title & readable text, lens/medium, output format, explicit exclusions) "
            "must be preserved verbatim — no rewording, summarizing or removal; "
            "{{variable placeholders}} kept verbatim; ask when aspect ratio, style "
            "or target tool is unspecified, otherwise default to 1:1 generic with "
            "(inferred).\n"
            "Delivery: body is a complete paste-ready prompt; append parameter "
            "blocks/negative lists per target tool grammar; no code paths or line "
            "anchors."
        ),
        "domain.visual.sections": (
            "\n\n[Semantics of body (visual four sections)] body must be organized in "
            "exactly four sections (I. theme, purpose & target tool; II. prompt body; "
            "III. visual specs & hard-constraint list (ratio/frame/text/count/"
            "exclusions), citing the [Domain directives] below; IV. usage notes & "
            "tunable parameters). Mark missing details with (inferred); no meta "
            "narration."
        ),
        "domain.visual.style.general": (
            "[Visual style: General]\n"
            "Terminology: 3–6 coherent natural-language sentences, layered as "
            "subject traits → actions & interactions → environmental anchors → "
            "composition & angle → light & time → color & texture → mood; no keyword "
            "stacking, no parameter or weight syntax.\n"
            "Completion: hard constraints (frame, ratio, orientation, size, count, "
            "title & readable text, lens/medium, output format, explicit exclusions) "
            "and {{variable placeholders}} preserved verbatim; default to 1:1 with "
            "(inferred) when the frame is unspecified.\n"
            "Delivery: body is the complete paste-ready prompt; append parameter "
            "blocks/negative lists per target tool grammar."
        ),
        "domain.visual.style.photography": (
            "[Visual style: Photography]\n"
            "Terminology: photographic language — lens (shot size, depth of field, "
            "focal feel), light (direction, hardness, color temperature, time of "
            "day), composition (rule of thirds, symmetry, leading lines, negative "
            "space), texture (grain, surfaces, material reflections); visible detail "
            "over camera-spec stacking.\n"
            "Completion: photographic additions only enhance lens, light and "
            "texture; never override original hard constraints or {{variable "
            "placeholders}}; keep orphaned constraints in the specs section.\n"
            "Delivery: a photography-grade prompt with a clear subject, explicit "
            "light and stable composition."
        ),
        "domain.visual.style.creative": (
            "[Visual style: Creative deconstruction]\n"
            "Terminology: deconstruct the description to its core imagery, then "
            "reimagine it as a fantastical visual narrative; build a self-consistent "
            "visual language instead of stock symbolism; the core imagery stays "
            "recognizable after sublimation.\n"
            "Completion: no hollow grandiose word stacking or shallow concept "
            "swaps; original hard constraints and {{variable placeholders}} preserved "
            "verbatim through reconstruction.\n"
            "Delivery: a unique, concrete, visualizable creative prompt with a "
            "traceable core."
        ),
        "domain.visual.style.chinese-model": (
            "[Visual style: Chinese aesthetics]\n"
            "Terminology: organize prompts with Chinese aesthetics — mood (yijing), "
            "negative space, rhythm and subtlety; may blend Chinese colors and "
            "materials (official green, cinnabar, xuan paper, silk); common style "
            "vocabulary: ink wash, gongbi, blue-green landscape, traditional "
            "patterns.\n"
            "Completion: aesthetic reinforcement only enhances expression; never "
            "override original hard constraints or {{variable placeholders}}; "
            "cultural elements serve the original theme.\n"
            "Delivery: a Chinese-context prompt where mood and symbolism outrank "
            "technical parameters."
        ),
        "domain.visual.style.json-structured": (
            "[Visual style: JSON structured]\n"
            "Terminology: rewrite the description into one structured prompt object "
            "— keys and values in Chinese; fields cover scene, subject, environment, "
            "action, composition, camera, lighting, color, style etc., added or "
            "removed as needed.\n"
            "Completion: if the input is already a structured object, keep its "
            "field hierarchy and key semantics, leave the top-level key set "
            "unchanged and refine in place; {{variable placeholders}} stay verbatim "
            "at their semantic positions.\n"
            "Delivery: the prompt body outputs the structured object itself with no "
            "explanatory text outside it."
        ),
        "domain.visual.style.video": (
            "[Visual style: Video generation]\n"
            "Terminology: organize as scene description → camera language → "
            "duration & pacing → shot transitions → sound cues; camera moves use "
            "push, pull, pan, track, follow, handheld, static; number shots in "
            "order with per-shot content and transition type (cut/dissolve); adapt "
            "to Sora/Jimeng/Kling/Runway grammar.\n"
            "Completion: default to a 5-second single shot with (inferred) when "
            "duration is unspecified; hard constraints (frame, ratio, shot count, "
            "caption text) and {{variable placeholders}} preserved verbatim.\n"
            "Delivery: body is the complete paste-ready video prompt; append "
            "parameter blocks per tool grammar."
        ),
        "domain.operations.name": "Operations Planning",
        "domain.operations.directives": (
            "[Domain directives: Operations Planning]\n"
            "Terminology: campaign plans must include goal, audience, mechanism, "
            "timeline and risk fallback; growth strategies must separate acquisition/"
            "activation/retention/conversion with metrics.\n"
            "Completion: default to a low-cost one-week campaign with (inferred) when "
            "budget/cycle is unspecified; mechanics must pass platform-rule compliance "
            "checkpoints.\n"
            "Delivery: campaign plan ready to schedule, with ownership and review "
            "criteria."
        ),
        "domain.operations.sections": (
            "\n\n[Semantics of body (operations four sections)] body must be organized "
            "in exactly four sections (I. goal, audience & resources; II. campaign "
            "mechanism & timeline; III. operations norms & compliance red lines, citing "
            "the [Domain directives] below; IV. ownership, metrics & review criteria). "
            "Mark missing details with (inferred); no meta narration."
        ),
    },
}


def resolve_locale(raw: str | None) -> Locale:
    """``Accept-Language`` → :data:`Locale`。

    取首个语言标签（忽略 ``q=`` 权重），``en*`` 视为英文，其余（含空值、垃圾值）
    一律回落 ``zh-CN``——未知输入不应导致报错，也不应把界面变成第三种语言。
    """
    if not raw:
        return DEFAULT_LOCALE
    first = raw.split(",", 1)[0].split(";", 1)[0].strip().lower()
    return "en" if first.startswith("en") else DEFAULT_LOCALE


def tr(key: str, locale: Locale = DEFAULT_LOCALE, **params: object) -> str:
    """查表并插值；缺键或插值参数不匹配时返回模板原文（不抛异常）。"""
    table = MESSAGES.get(locale, MESSAGES[DEFAULT_LOCALE])
    template = table.get(key)
    if template is None:
        template = MESSAGES[DEFAULT_LOCALE].get(key)
    if template is None:
        return key
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template
