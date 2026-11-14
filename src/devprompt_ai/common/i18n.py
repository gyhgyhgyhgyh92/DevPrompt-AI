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
