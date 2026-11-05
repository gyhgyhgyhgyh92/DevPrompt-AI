"""F-001 统一业务入口（双形态唯一，MUST-07/10）。业务判定只在此层与 domain/。"""

from __future__ import annotations

import asyncio
import dataclasses
import difflib
import json
import logging
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from devprompt_ai.common.cost import take_llm_tokens
from devprompt_ai.common.hashing import sha256_hex
from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.common.process import ProcessError
from devprompt_ai.common.secrets import mask_secret
from devprompt_ai.config import MODEL_KEY_MAP, AppConfig
from devprompt_ai.domain.agent.action import (
    AgentAction,
    AgentBudget,
    AgentStep,
    StepOutcome,
)
from devprompt_ai.domain.agent.anchor import (
    anchor_from_payload,
    anchor_to_payload,
    extract_anchor,
    merge_followup,
    render_anchor,
)
from devprompt_ai.domain.agent.convergence import evaluate_convergence
from devprompt_ai.domain.agent.memory import MAX_INHERITED_VARIANTS, TurnMemory
from devprompt_ai.domain.agent.ports import ActionPlanner
from devprompt_ai.domain.agent.sensorium import SensoriumInput, compute_sensorium
from devprompt_ai.domain.context import (
    ContextBudget,
    ContextPayload,
    TurnInput,
    TurnSummary,
    build_context,
    summary_from_turn,
)
from devprompt_ai.domain.decision.followup import (
    GuardrailState,
    UnknownItem,
    UnknownOption,
    answered_headers,
    build_unknowns,
    lint_questions,
)
from devprompt_ai.domain.decision.port import DecisionPort, FactProbeOutput, VariantScore
from devprompt_ai.domain.delivery import DeliveryInput, DeliveryVerdict, evaluate_delivery
from devprompt_ai.domain.errors import (
    CatalogFetchError,
    ConfigurationError,
    DevPromptError,
    StateError,
)
from devprompt_ai.domain.generate.anchors import Anchor, extract_anchors, verify_anchors
from devprompt_ai.domain.generate.claims import CLAIM_COVERAGE_MIN, ClaimReport
from devprompt_ai.domain.generate.ports import (
    GeneratePort,
    GenerationContext,
    Level,
    VariantDraft,
)
from devprompt_ai.domain.generate.variants import plan_levels, resolve_level
from devprompt_ai.domain.hooks.builtin import FactsSummaryHook, summarize_facts
from devprompt_ai.domain.hooks.pipeline import HookPipeline
from devprompt_ai.domain.hooks.types import HookContext
from devprompt_ai.domain.model_catalog import (
    ModelCatalogFetcher,
    ModelCatalogItem,
    effective_context_window,
    mark_stale_models,
    merge_catalog,
    static_catalog,
)
from devprompt_ai.domain.model_spec import (
    providers_projection,
    resolve_api_mode,
    resolve_provider_key,
)
from devprompt_ai.domain.models import (
    Candidate,
    FactResult,
    FlowSession,
    Page,
    ProjectNoteStore,
    SessionStore,
    SessionSummary,
    Symbol,
    TurnRecord,
    TurnStore,
)
from devprompt_ai.domain.progress import (
    ProgressEvent,
    ProgressSink,
    answering_text,
    candidates_text,
    clarification_text,
    facts_text,
    generation_text,
    level_text,
    manual_required_text,
    recommendation_text,
    retrieval_text,
    scoring_text,
    single_variant_text,
    symbols_text,
    target_text,
)
from devprompt_ai.domain.ranking.recommend import decide_mark
from devprompt_ai.domain.ranking.score import normalize_fit, weighted_total
from devprompt_ai.domain.retrieval.candidates import MAX_CANDIDATES, build_candidates
from devprompt_ai.domain.retrieval.facts import is_evidence_complete, verify_facts
from devprompt_ai.domain.retrieval.locate import locate_symbol
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader
from devprompt_ai.harness.guardrails import validate_claims
from devprompt_ai.harness.llm import LLMGenerator, last_usage
from devprompt_ai.harness.process import LocalCommandRunner, LocalFileReader, SymbolTableProvider
from devprompt_ai.harness.trace import TracingReader, TracingRunner
from devprompt_ai.memory.model_catalog_store import read_model_catalog, write_model_catalog
from devprompt_ai.memory.project_note_store import normalize_key
from devprompt_ai.memory.settings_store import (
    read_model_registry,
    write_model_registry,
    write_model_settings,
    write_process_settings,
)
from devprompt_ai.memory.turn_store import TurnConflictError
from devprompt_ai.observability.logging import emit, emit_error, emit_warning, set_telemetry
from devprompt_ai.state import FlowState, hop, start_turn, transition

logger = logging.getLogger("devprompt.flow")

Preference = dict[str, float]
SnapshotStatus = Literal["ask", "done", "guardrail", "running", "aborted"]

#: 上一轮方案正文的注入上限（字符）。三套全文可能上万字，只带可定位的骨架。
PREVIOUS_VARIANTS_LIMIT: int = 2000


def _render_previous_variants(variants: Sequence[VariantDraft]) -> str:
    """把上一轮方案压成一段供迭代轮引用；超限截断并标注省略号，不静默丢弃。"""
    if not variants:
        return ""
    text = "\n\n".join(f"【{v.level} 档】{v.title}\n{v.body}" for v in variants)
    if len(text) <= PREVIOUS_VARIANTS_LIMIT:
        return text
    return text[: PREVIOUS_VARIANTS_LIMIT - 1] + "…"


def _render_ranking(ranking: object, details: object = None) -> str:
    """把推荐判定压成一段可解释文本（2026-11-05）。

    除被选中档位的明细外，还带各档 fit/total（2026-11-05 补）——否则模型能解释
    「为什么选 B」，却答不出「C 差多少」，落选原因仍然说不清。
    """
    if not isinstance(ranking, dict) or not ranking.get("variant"):
        return ""

    def _num(source: object, key: str) -> str:
        if not isinstance(source, dict):
            return "未知"
        value = source.get(key)
        if isinstance(value, int | float):
            return f"{float(value):.2f}"
        return "未知"

    parts = [
        f"推荐档位 {ranking['variant']}",
        f"是否标记推荐 {'是' if ranking.get('marked') else '否'}",
        f"与次优差距 {_num(ranking, 'gap')}",
        f"置信度 {_num(ranking, 'confidence')}",
        f"适配度 {_num(ranking, 'fit')}",
        f"综合分 {_num(ranking, 'total')}",
    ]
    reason = str(ranking.get("reason", "")).strip()
    if reason:
        parts.append(f"判定理由 {reason}")
    if isinstance(details, dict) and details:
        rows = [
            f"{level} 适配度 {_num(details[level], 'fit')} 综合分 {_num(details[level], 'total')}"
            for level in sorted(details)
        ]
        if rows:
            parts.append("各档明细 " + "、".join(rows))
    return "；".join(parts)


_RANK_CACHE_TTL_SECONDS: float = 30.0 * 60.0
"""组件排序缓存 TTL（MUST-14：决策结果 30 分钟；SHOULD-04 惰性淘汰）。"""

_RANK_CACHE: dict[tuple[str, str, str, str], tuple[float, list[int]]] = {}
"""rank_components 结果缓存（模块级，MUST-14）。

键 = (项目绝对路径, 原句 sha256, 阈值配置 hash, 候选集摘要)——键不含原句明文。
第四段是 2026-11-04 补的：此前只有前三段，代码改动导致候选集变化后 30 分钟内
仍会命中旧 order，唯一保护是越界检查（只防越界，防不了错位）。
值 = (过期时刻 monotonic, 候选索引顺序)。禁存原句与决策原始响应。
"""


def _session_locale(session: FlowSession) -> Locale:
    """会话语言（2026-11-06）：创建会话时由 Accept-Language 写入，历史轮沿用当轮值。"""
    return "en" if session.data.get("locale") == "en" else DEFAULT_LOCALE


async def _notify(session: FlowSession, progress: ProgressSink | None, text: str) -> None:
    """推送一条思考文案（带当前阶段）。进度是尽力而为：失败绝不影响业务流程。"""
    if progress is None:
        return
    try:
        await progress.emit(ProgressEvent(text=text, phase=session.state))
    except Exception:
        logger.debug("progress.emit_failed", exc_info=True)


@dataclass(frozen=True, slots=True)
class RankingView:
    """F-403/F-404 加权推荐视图：字段与 RecommendationResult/加权结果一一对应。

    fit/pref/total 均为 variant 所指档位（最高总分档）的加权明细。
    """

    variant: str
    gap: float
    confidence: float
    marked: bool
    reason: str
    fit: float
    total: float


# 旧会话（2026-10-21 偏好记忆移除前）的 ranking 带已废弃的 pref 字段。
# 重建时按字段白名单过滤，否则 RankingView(**data) 抛 TypeError，历史会话整体 500。
_RANKING_KEYS = frozenset(f.name for f in dataclasses.fields(RankingView))


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """F-805 成本明细：单次优化 token 用量（LLM 实际用量）。

    llm_tokens 为 SDK 实际用量；total_tokens 即 llm_tokens 合计
    （2026-10-15 起决策层为单一 LLM 实现，用量同源）。
    """

    llm_tokens: int
    total_tokens: int
    llm_source: str


@dataclass(frozen=True, slots=True)
class DeliveryGateView:
    """交付门结果（2026-11-05）：前端据此渲染门状态与披露文案。

    ``tone`` 由领域层给出（ok / warn / error），前端只按它选样式（MUST-33）。
    """

    status: str
    tone: str = "ok"
    reasons: tuple[str, ...] = ()
    can_mark_c: bool = True
    can_mark_recommend: bool = True
    disclosure: str = ""


@dataclass(slots=True)
class FlowSnapshot:
    """表现层快照：CLI/Web 只渲染它（MUST-10）。"""

    session_id: str
    status: SnapshotStatus
    state: str
    questions: list[UnknownItem] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)
    variants: list[VariantDraft] = field(default_factory=list)
    ranking: RankingView | None = None
    target: Symbol | None = None  # 上下文面板（设计 §1.2）：目标定位 symbol@path:line
    facts: list[FactResult] = field(default_factory=list)  # 取证事实只读透出
    cost: CostBreakdown | None = None  # F-805：token 用量明细（LLM）
    message: str = ""
    current_turn_id: str | None = None
    #: agentic 进度（2026-11-04，additive）：本轮已执行动作数与最近一个动作名。
    #: 循环期间 status 为 "running"，前端据此渲染时间线而不是干等进度条。
    agent_step: int | None = None
    agent_action: str | None = None
    agent_elapsed_ms: int | None = None
    #: 交付时证据已过期（2026-11-05）：agentic 跳过 RETRIEVING 直接交付，
    #: 期间代码被改动。只披露不阻断——让用户知道方案基于旧证据。
    evidence_stale: bool = False
    #: 纯回答轮的正文（2026-11-05）：与 message 区分——message 是系统提示文案。
    reply_text: str = ""
    #: 交付证据门结果（2026-11-05）：只披露质量标记，不阻断交付。
    delivery_gate: DeliveryGateView | None = None
    """本轮归属（2026-11-04）：前端据此决定该轮进历史列表还是当前对话区。

    此前前端用「轮次列表末位」推断当前轮，导致新一轮提交瞬间把上一轮从历史里过滤掉
    （现象：第二轮开始时第一轮正文消失）。归属改由服务端给出，构造见 ``_begin_turn``。
    """


#: 用户表达方向性分歧的信号词（启发式，不调 LLM）：命中则本轮重新给三套。
#: shortcut: 只覆盖常见说法，未命中时沿用上一轮选定方向（省 token），需要更准可换 LLM 判定。
_DIRECTION_CONFLICT_WORDS: tuple[str, ...] = (
    "推翻",
    "不要按",
    "换个方向",
    "换成另一种",
    "重新考虑",
    "走激进",
    "保守一点",
    "别用刚才",
)


def _gate_view(raw: object) -> DeliveryGateView | None:
    """把 ``session.data["delivery_gate"]`` 还原成快照视图；畸形数据按「无门」处理。"""
    if not isinstance(raw, dict):
        return None
    raw_reasons = raw.get("reasons")
    return DeliveryGateView(
        status=str(raw.get("status", "")),
        tone=str(raw.get("tone", "ok")),
        reasons=(
            tuple(str(item) for item in raw_reasons)
            if isinstance(raw_reasons, (list, tuple))
            else ()
        ),
        can_mark_c=bool(raw.get("can_mark_c", True)),
        can_mark_recommend=bool(raw.get("can_mark_recommend", True)),
        disclosure=str(raw.get("disclosure", "")),
    )


def _preferred_level(session: FlowSession) -> Literal["A", "B", "C"] | None:
    """上一轮选定的档位（非 A/B/C 的脏数据一律忽略）。"""
    value = str(session.data.get("preferred_level", ""))
    if value == "A":
        return "A"
    if value == "B":
        return "B"
    if value == "C":
        return "C"
    return None


def _unknown_from(raw: dict[str, Any]) -> UnknownItem:
    """会话里存的未知项（dict，options 已被 asdict 展开）→ domain 对象。"""
    return UnknownItem(
        key=str(raw.get("key", "")),
        reason=str(raw.get("reason", "")),
        best_guess=str(raw.get("best_guess", "")),
        ask=str(raw.get("ask", "")),
        header=str(raw.get("header", "")),
        options=tuple(
            UnknownOption(
                label=str(option.get("label", "")), description=str(option.get("description", ""))
            )
            for option in raw.get("options", [])
            if isinstance(option, dict)
        ),
        multi_select=bool(raw.get("multi_select", False)),
    )


def _catalog_item_view(item: ModelCatalogItem) -> dict[str, Any]:
    """目录条目 → 契约视图（tiers 转 list；字段名与 `ModelCatalogItem` 契约一致）。"""
    return {
        "model_id": item.model_id,
        "label": item.label,
        "max_context_length": item.max_context_length,
        "context_window_tiers": list(item.context_window_tiers),
        "reasoning_efforts": list(item.reasoning_efforts),
        "default_effort": item.default_effort,
        "source": item.source,
        "is_stale": item.is_stale,
    }


class ForgeService:
    def __init__(
        self,
        *,
        cfg: AppConfig,
        decider: DecisionPort,
        sessions: SessionStore,
        runner: CommandRunner,
        reader: FileReader,
        generator: GeneratePort,
        symbols_provider: SymbolTableProvider,
        catalog_fetcher: ModelCatalogFetcher | None = None,
        symbols_override: list[Symbol] | None = None,
        turns: TurnStore | None = None,
        notes: ProjectNoteStore | None = None,
    ) -> None:
        self._cfg = cfg
        self._decider = decider
        self._sessions = sessions
        #: 多轮 turn 存储；None 时跳过双写（旧测试零改动）
        self._turns = turns
        #: L2 项目记忆；None 时不注入也不记录
        self._notes = notes
        self._runner = runner
        self._reader = reader
        self._generator = generator
        self._symbols_provider = symbols_provider
        self._catalog_fetcher = catalog_fetcher
        self._symbols_override = symbols_override
        #: agentic 调度端口：decider 未实现 next_action 时（旧 mock / 测试桩）为 None，
        #: run_agent_loop 随即退化为固定流程，既有调用方零改动。
        self._planner: ActionPlanner | None = (
            decider if isinstance(decider, ActionPlanner) else None
        )
        #: 横切 hook 管线（2026-11-04）：当前只挂取证摘要。它在生成与打分两处
        #: 被重复计算，是唯一「接入即有收益」的插入点；其余横切点保持内联，
        #: 避免为架构一致性付出回归风险。
        self._hooks = HookPipeline(
            [FactsSummaryHook()],
            on_result=lambda run: emit(
                "hook.ran",
                hook=run.name,
                outcome=run.outcome,
                duration_ms=run.duration_ms,
            ),
        )

    # ------------------------------------------------------------------
    # 模型目录（2026-10-17 动态模型目录）
    # ------------------------------------------------------------------

    def provider_catalog_target(
        self, provider_id: str, *, with_key: bool = False
    ) -> tuple[str, str, str]:
        """按供应商 id 取出拉取模型目录所需的 provider / base_url / api_key。

        2026-10-18 供应商中心化重构：目录挂在**供应商**（端点+密钥）而非条目上——
        刚配好、还没勾选任何模型的供应商也必须能刷新（多选流程的第一步）。

        **api_key 只从 settings.json（0600）读、当场返回给调用方**，不写库、不进日志
        （MUST-19）。供应商不存在时抛 :class:`StateError`（非法引用，明确拒绝而非静默）。
        """
        for record in read_model_registry()["providers"]:
            if str(record.get("id", "")) != provider_id:
                continue
            provider = str(record.get("provider", ""))
            base_url = str(record.get("base_url", ""))
            if not base_url.strip():
                raise ConfigurationError(
                    f"供应商 {provider_id} 未填写接口地址，无法拉取模型列表",
                    context={"provider_id": provider_id, "provider": provider},
                )
            return provider, base_url, (str(record.get("api_key", "")) if with_key else "")
        raise StateError(f"供应商不存在：{provider_id}", context={"provider_id": provider_id})

    def _catalog_key(self, provider: str, base_url: str) -> tuple[str, str]:
        """目录缓存键 = (规范 provider key, 端点)。同一厂商换端点即另一份缓存。"""
        return resolve_provider_key(provider), base_url.strip()

    def _configured_model_ids(self, provider: str) -> list[str]:
        """该厂商下用户已配置的 model_id（用于标注「不在当前列表」）。"""
        registry = read_model_registry()
        return [
            str(entry.get("model_id", ""))
            for entry in registry["models"]
            if resolve_provider_key(str(entry.get("provider", "")))
            == resolve_provider_key(provider)
        ]

    async def read_model_catalog(
        self, provider: str, base_url: str, *, request_id: str
    ) -> dict[str, Any]:
        """读模型目录（落库快照；无记录则回落静态表）。

        **不联网**——读的是上次刷新结果。联网拉取是 :meth:`refresh_model_catalog`。
        """
        provider_key, url = self._catalog_key(provider, base_url)
        items, fetched_at = await asyncio.to_thread(read_model_catalog, provider_key, url)
        if not items:
            items = static_catalog(provider)
        items = mark_stale_models(items, self._configured_model_ids(provider), provider=provider)
        return {
            "provider": provider_key,
            "base_url": url,
            "fetched_at": fetched_at,
            "models": [_catalog_item_view(item) for item in items],
            "warning": None,
        }

    async def refresh_model_catalog(
        self, provider: str, base_url: str, api_key: str, *, request_id: str
    ) -> dict[str, Any]:
        """刷新模型目录：现场拉取 → 落库 → 返回合并结果。

        **拉取失败不清空**：返回上次落库的快照 + ``warning`` 说明失败原因
        （用户裁定：限流不该让已配模型失效）。快照也没有时回落静态表。
        """
        provider_key, url = self._catalog_key(provider, base_url)
        warning: str | None = None
        items: list[ModelCatalogItem] = []
        fetched_at: str | None = None

        if self._catalog_fetcher is None:
            warning = "当前构建未接入模型目录拉取器（catalog_fetcher 未注入）"
        else:
            try:
                remote = await self._catalog_fetcher.fetch(
                    base_url=url, api_key=api_key, timeout=self._cfg.llm_timeout
                )
                merged = merge_catalog(
                    remote, provider=provider, static_items=static_catalog(provider)
                )
                if merged:
                    items = merged
                    fetched_at = await asyncio.to_thread(
                        write_model_catalog, provider_key, url, merged
                    )
                    emit(
                        "model_catalog.refreshed",
                        provider=provider_key,
                        count=len(merged),
                        request_id=request_id,
                    )
                else:
                    warning = "该端点未返回任何可用模型，已保留上次结果"
            except CatalogFetchError as exc:
                warning = str(exc)
                emit_error(
                    "model_catalog.refresh_failed", provider=provider_key, request_id=request_id
                )

        if not items:
            cached, cached_at = await asyncio.to_thread(read_model_catalog, provider_key, url)
            items, fetched_at = cached, cached_at
        if not items:
            items = static_catalog(provider)
            fetched_at = None

        items = mark_stale_models(items, self._configured_model_ids(provider), provider=provider)
        return {
            "provider": provider_key,
            "base_url": url,
            "fetched_at": fetched_at,
            "models": [_catalog_item_view(item) for item in items],
            "warning": warning,
        }

    def effective_window(
        self, provider: str, model_id: str, selected_tier: int | None
    ) -> int | None:
        """生效窗口（动态优先）；读落库快照，不联网。

        供 ``_registry_view`` 与激活条目回填共用，确保「界面显示的档位」与
        「告警实际用的窗口」永远来自同一条回落链（MUST-08 单一来源）。
        """
        base_url = ""
        for entry in read_model_registry()["models"]:
            if resolve_provider_key(str(entry.get("provider", ""))) == resolve_provider_key(
                provider
            ):
                base_url = str(entry.get("base_url", ""))
                break
        items, _ = read_model_catalog(*self._catalog_key(provider, base_url))
        return effective_context_window(provider, model_id, selected_tier, items)

    def _traced(
        self,
        progress: ProgressSink | None,
        root: str,
        phase: Callable[[], str] | None = None,
    ) -> tuple[CommandRunner, FileReader]:
        """按请求包装观测层：真实 rg / 读文件会上报成动作卡片。

        ``progress`` 缺省时返回原实例（旧调用方零改动）；包装器不挂单例状态，
        并发请求各持一份，不会串台。
        """
        if progress is None:
            return self._runner, self._reader
        return (
            TracingRunner(self._runner, progress, root, phase),
            TracingReader(self._reader, progress, root, phase),
        )

    async def optimize(
        self,
        user_id: str,
        project_root: str,
        sentence: str,
        *,
        request_id: str,
        progress: ProgressSink | None = None,
        session_id: str | None = None,
        base_turn_id: str = "",
        locale: Locale = DEFAULT_LOCALE,
    ) -> FlowSnapshot:
        """F-001：创建/恢复会话，执行阶段一至二（检索+探针），路由 ask/done。

        ``progress`` 为可选的思考过程出口（流式端点传入）；缺省 None 时旧调用方零改动。
        ``session_id`` 非空表示**在同一会话开启新一轮**（多轮，2026-10-20）。
        ``base_turn_id`` 非空表示**以某一历史轮为基线**新开一轮（2026-11-05）。
        """
        session = await start_turn(self._sessions, user_id, session_id)
        try:
            # 多轮：本轮可以只给原句，项目路径沿用它所在会话的既有值
            project_root = project_root or str(session.data.get("project_root", ""))
            if not project_root:
                raise DevPromptError("项目路径不能为空", code=2001)
            # 上一轮的结论与完备度（决定本轮给几套；data 随后会被整体重置）
            previous_summary: dict[str, Any] = {}
            if self._turns is not None:
                records = await self._turns.list_for_session(session.session_id)
                if records and isinstance(records[-1].summary, dict):
                    previous_summary = records[-1].summary
            # 轮次序号跨轮累积（session.data 会被重建，故先取出再写回）
            previous_index = int(session.data.get("turn_index", -1))
            # 多轮继承（2026-11-04）：不再整体丢弃，方案正文/澄清/取证经 TurnMemory 带入。
            # 原句为空时沿用上一轮目标——这就是「不带新原句的追问」入口。
            inherited = TurnMemory.from_payload(session.data.get("turn_memory"))
            memory = inherited.inherit_for_next_turn(sentence)
            if base_turn_id:
                memory = await self._inherit_from_base_turn(user_id, memory, base_turn_id)
            if not memory.sentence:
                raise DevPromptError("原句不能为空（当前会话也没有可沿用的目标）", code=1001)
            # 目标锚点（2026-11-05）：已有则追加合并（不重写 objective），无则按本轮原句新建。
            # 旧会话没有这个键，等价于「没有可继承的锚点」，不影响既有流程。
            next_index = previous_index + 1
            previous_anchor = anchor_from_payload(session.data.get("turn_anchor"))
            anchor = (
                extract_anchor(memory.sentence, next_index)
                if previous_anchor is None
                else merge_followup(previous_anchor, memory.sentence, turn_index=next_index)
            )
            session.data = {
                "sentence": memory.sentence,
                "project_root": project_root,
                "last_request_id": request_id,
                # 会话语言（2026-11-06）：由 Accept-Language 解析后随会话保留，历史轮沿用。
                "locale": locale,
                "clarifications": dict(memory.clarifications),
                "rounds": 0,
                "cost_tokens": 0,  # 总 token（护栏判定用，MUST-26 成本预算）
                "cost_llm_tokens": 0,  # F-805：LLM 实际用量
                "started_at": time.time(),  # flow.completed 耗时基准（T6-9）
                "turn_index": previous_index,
                "preferred_level": str(previous_summary.get("decision", "")),
                "prev_facts_complete": previous_summary.get("facts_complete"),
                "turn_memory": memory.to_payload(),
                "turn_anchor": anchor_to_payload(anchor),
            }
            # 继承的方案与取证直接进本轮 data：agentic 循环据此判断能否跳过检索
            if memory.variants:
                session.data["variants"] = [v.model_dump() for v in memory.variants]
            if memory.facts:
                session.data["facts"] = [
                    {"key": f.key, "passed": f.passed, "evidence": f.evidence} for f in memory.facts
                ]
                session.data["facts_mtime_digest"] = memory.facts_mtime_digest
            if memory.target is not None:
                session.data["target"] = dict(memory.target)
            await self._begin_turn(session)
            if self._planner is None:
                # 旧调用方 / 测试桩未实现 next_action：保持线性编排（零回归）
                return await self._optimize_linear(
                    session,
                    sentence,
                    project_root,
                    request_id=request_id,
                    progress=progress,
                )
            return await self.run_agent_loop(session, request_id=request_id, progress=progress)
        except asyncio.CancelledError:
            # 客户端断流：CancelledError 属 BaseException，下面的 except Exception 抓不到
            await self._abort_quietly(session)
            raise
        except Exception:
            await self._abort_quietly(session)
            raise

    async def _inherit_from_base_turn(
        self, user_id: str, memory: TurnMemory, base_turn_id: str
    ) -> TurnMemory:
        """以某一历史轮为基线：取该轮的取证与方案作为本轮起点。

        **历史轮一条不少**（turn 表 append-only，MUST-32）：所谓「回滚」= 以旧轮为基线新开一轮，
        不删历史。取证的 mtime 指纹没有落库，故继承的取证因「缺指纹即失效」判 stale，
        本轮会重新取证；方案正文与澄清作为上下文起点沿用。
        """
        record = await self.load_turn(user_id, base_turn_id)
        facts = tuple(FactResult(**item) for item in record.facts if isinstance(item, dict))
        variants = tuple(VariantDraft(**item) for item in record.output if isinstance(item, dict))
        return TurnMemory(
            sentence=memory.sentence,
            facts=facts,
            facts_mtime_digest="",
            variants=variants[:MAX_INHERITED_VARIANTS],
            clarifications=dict(memory.clarifications),
            target=memory.target,
        )

    async def ask_followup(
        self,
        user_id: str,
        session_id: str,
        answers: dict[str, str],
        *,
        request_id: str,
        progress: ProgressSink | None = None,
    ) -> FlowSnapshot:
        """F-204：批量答复 → 重新研判 → ask/guardrail/done（progress 供流式端点推送过程）。"""
        session = await self._require(user_id, session_id, {FlowState.ASKING, FlowState.CONFIRMING})
        try:
            session.data.setdefault("clarifications", {}).update(answers)
            session.data["last_request_id"] = request_id
            session.data["rounds"] = int(session.data.get("rounds", 0)) + 1
            await hop(session, FlowState.CONFIRMING, self._sessions)
            return await self._reprobe(session, progress=progress)
        except Exception:
            await self._abort_quietly(session)
            raise

    async def resume(self, user_id: str, session_id: str, *, request_id: str) -> FlowSnapshot:
        """--session 恢复入口：只读加载既有会话并重建快照，不做任何状态转移。

        4H 偏差：计划称「service 无需改动」，但 CLI 层不得直读会话存储（只消费快照），
        故以最小只读方法提供恢复路径。

        星型拓扑（2026-11-04）：覆盖除 ABORTED 外的全部状态。SSE 的 1s 轮询也走本方法，
        agentic 循环期间必须能读到 running 快照——否则进度流会在执行中段被当成错误断流。
        ABORTED 刻意不在集合内：routes 靠它的异常上下文输出扩展 status "aborted"。
        """
        session = await self._require(
            user_id,
            session_id,
            {
                FlowState.INIT,
                FlowState.AGENTIC,
                FlowState.RETRIEVING,
                FlowState.PROBING,
                FlowState.ASKING,
                FlowState.CONFIRMING,
                FlowState.GENERATING,
                FlowState.RANKING,
                FlowState.DONE,
            },
        )
        state = FlowState(session.state)
        if state is FlowState.DONE:
            return self._snapshot(session, "done")
        if state is FlowState.CONFIRMING and session.data.get("guardrail"):
            return self._snapshot(session, "guardrail")
        if state is FlowState.ASKING:
            return self._snapshot(session, "ask")
        return self._snapshot(session, "running")

    async def escape(self, user_id: str, session_id: str, *, request_id: str) -> FlowSnapshot:
        """MUST-26 ②：用户逃生「直接生成」→ 保守版。

        GENERATING 转移统一由 _generate_and_finish 执行（冻结状态机无 GENERATING→GENERATING 边，
        此处不得预转移，否则必抛 6001）。
        """
        session = await self._require(user_id, session_id, {FlowState.ASKING, FlowState.CONFIRMING})
        try:
            emit(
                "followup.escaped",
                rounds=session.data.get("rounds", 0),
                request_id=request_id,
            )
            session.data["level"] = "A"
            session.data["conservative"] = True
            return await self._generate_and_finish(session)
        except Exception:
            await self._abort_quietly(session)
            raise

    async def guardrail_confirm(
        self, user_id: str, session_id: str, proceed: bool, *, request_id: str
    ) -> FlowSnapshot:
        """MUST-26 ③：软护栏裁决——继续追问（清零）或直接生成。"""
        session = await self._require(user_id, session_id, {FlowState.CONFIRMING})
        try:
            if proceed:
                session.data["rounds"] = 0
                await hop(session, FlowState.ASKING, self._sessions)
                await self._finish_turn(session)
                return self._snapshot(session, "ask")
            session.data["level"] = "A"
            session.data["conservative"] = True
            return await self._generate_and_finish(session)
        except Exception:
            await self._abort_quietly(session)
            raise

    # ------------------------------------------------------------------
    # Agentic 循环（2026-11-04 星型拓扑）
    # ------------------------------------------------------------------

    async def _act_retrieve(
        self,
        session: FlowSession,
        sentence: str,
        project_root: str,
        *,
        request_id: str,
        progress: ProgressSink | None = None,
    ) -> bool:
        """检索 → 排序 → 定位 → 取证，写入 candidates / target / facts。

        返回 False 表示候选不足已转 ASKING，调用方直接返回快照即可。
        """
        await hop(session, FlowState.RETRIEVING, self._sessions)
        emit("flow.started", flow_id=session.session_id, request_id=request_id)

        symbols = self._symbols_override
        digest = ""
        if symbols is None:
            table = await self._symbols_provider.get(project_root)
            symbols = table.symbols
            digest = table.cache_key

        # 多轮复用（2026-11-04）：已有取证且指纹未变 → 跳过 ripgrep 与定位。
        # 指纹（符号表缓存键 = root + 全量 mtime 摘要）变了就重取，避免拿旧行号当证据。
        existing_facts = session.data.get("facts") or []
        existing_digest = str(session.data.get("facts_mtime_digest", ""))
        if existing_facts and existing_digest:
            if existing_digest != digest:
                emit("evidence.stale_reprobe", request_id=request_id)
            elif session.data.get("target"):
                emit("evidence.reused", count=len(existing_facts), request_id=request_id)
                passed = sum(1 for f in existing_facts if f.get("passed"))
                await _notify(
                    session,
                    progress,
                    facts_text(passed, len(existing_facts), _session_locale(session)),
                )
                return True

        await _notify(session, progress, retrieval_text(_session_locale(session)))
        await _notify(session, progress, symbols_text(len(symbols), _session_locale(session)))
        result = build_candidates(sentence, symbols)
        await _notify(
            session,
            progress,
            candidates_text(result.total_matched, len(result.candidates), _session_locale(session)),
        )
        session.data["candidates"] = [
            {"name": c.name, "path": c.path, "score": c.score, "source": c.source}
            for c in result.candidates
        ]

        if result.manual_required:
            # slots dataclass 无 __dict__，序列化必须走 asdict（计划 §6.2 注意事项）
            item = UnknownItem(
                key="manual_target",
                reason=tr(
                    "clarify.manual_reason",
                    _session_locale(session),
                    matched=result.total_matched,
                ),
                best_guess="",
                ask=tr("clarify.manual_ask", _session_locale(session)),
            )
            session.data["unknowns"] = [dataclasses.asdict(item)]
            session.data["level"] = "A"
            await _notify(
                session,
                progress,
                manual_required_text(result.total_matched, _session_locale(session)),
            )
            await hop(session, FlowState.ASKING, self._sessions)
            await self._finish_turn(session)
            return False

        top = await self._rank_top(session, result.candidates)
        symbol = Symbol(name=top.name, path=top.path, line=top.line, kind="function")
        runner, reader = self._traced(progress, project_root, lambda: session.state)
        location = await locate_symbol(symbol, runner, reader, root=project_root)
        await _notify(
            session,
            progress,
            target_text(top.name, top.path, location.definition_line, _session_locale(session)),
        )
        facts = await verify_facts(location, sentence, runner, reader, root=project_root)
        # 只统计适用项：对后端项目报「3/7 通过」是误导，真实分母是 4
        applicable = [f for f in facts if f.applicable]
        await _notify(
            session,
            progress,
            facts_text(
                sum(1 for f in applicable if f.passed),
                len(applicable),
                _session_locale(session),
            ),
        )
        session.data["facts"] = [
            {
                "key": f.key,
                "passed": f.passed,
                "evidence": f.evidence,
                "applicable": f.applicable,
            }
            for f in facts
        ]
        session.data["target"] = {"name": top.name, "path": top.path, "line": top.line}
        self._validate_inherited_clarifications(session, request_id)
        session.data["facts_mtime_digest"] = digest
        await self._refresh_facts_summary(session)
        return True

    async def _check_evidence_freshness(
        self, session: FlowSession, *, request_id: str, stage: str
    ) -> None:
        """生成/交付前校验证据新鲜度（2026-11-05 真实冒烟发现）。

        stale 检查原本只在 ``_act_retrieve`` 里，而 agentic 允许跳过 RETRIEVING
        直接生成或交付——改了代码却基于旧证据产出，且全程无声。这里只做标记与
        披露，不强制重取证：重取会打断流程、成本也高；宁可标注过期，不可静默过期。

        :param stage: ``generate`` 或 ``deliver``，进事件字段便于归因是哪一步发现的
        """
        digest_before = str(session.data.get("facts_mtime_digest", ""))
        if not digest_before or not session.data.get("facts"):
            return
        table = await self._symbols_provider.get(str(session.data.get("project_root", "")))
        if table.cache_key == digest_before:
            return
        session.data["evidence_stale"] = True
        emit(
            "evidence.stale_on_deliver",
            request_id=request_id,
            stage=stage,
            digest_before=digest_before,
            digest_now=table.cache_key,
        )

    async def _refresh_facts_summary(self, session: FlowSession) -> None:
        """after_retrieval hook：摘要算一次写进会话，生成与打分直接读。

        失败或跳过时不影响主流程：调用方仍会回退到 ``_summarize_facts`` 现算。
        """
        merged = await self._hooks.run(
            "after_retrieval",
            HookContext(
                phase="after_retrieval",
                session_state=session.state,
                data=session.data,
            ),
        )
        if merged:
            session.data.update(merged)

    async def _optimize_linear(
        self,
        session: FlowSession,
        sentence: str,
        project_root: str,
        *,
        request_id: str,
        progress: ProgressSink | None = None,
    ) -> FlowSnapshot:
        """固定流水线（无 planner 时的回落路径）：检索 → 研判 → 生成 → 打分 → 交付。"""
        ok = await self._act_retrieve(
            session, sentence, project_root, request_id=request_id, progress=progress
        )
        if not ok:
            return self._snapshot(session, "ask")
        await hop(session, FlowState.PROBING, self._sessions)
        return await self._probe_and_route(session, request_id=request_id, progress=progress)

    async def run_agent_loop(
        self, session: FlowSession, *, request_id: str, progress: ProgressSink | None = None
    ) -> FlowSnapshot:
        """AGENTIC 循环：取动作 → 执行 → 记录步骤 → 收敛检测 → 回到决策。

        终止四条路径：模型主动 deliver/abort、需要用户答复（转 ASKING）、
        收敛熔断（L3 且已有 L2 警告）、步数预算耗尽。
        """
        planner = self._planner
        if planner is None:
            raise DevPromptError("agentic 调度端口未装配，无法进入循环", code=9001, context={})

        await hop(session, FlowState.AGENTIC, self._sessions)
        steps: list[AgentStep] = []
        budget = AgentBudget()
        warned = False

        while True:
            decision = await planner.next_action(
                sentence=str(session.data.get("sentence", "")),
                facts=[FactResult(**f) for f in session.data.get("facts", [])],
                steps=tuple(steps),
                variant_count=len(session.data.get("variants", []) or []),
                clarifications=dict(session.data.get("clarifications", {})),
                correction=str(session.data.get("hook_correction", "")),
            )
            action = AgentAction(decision.action)
            started = time.monotonic()
            terminal = await self._execute_action(
                action, session, request_id=request_id, progress=progress
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            steps.append(
                AgentStep(
                    index=len(steps),
                    action=action,
                    outcome=StepOutcome.OK,
                    duration_ms=duration_ms,
                    facts_passed=sum(1 for f in session.data.get("facts", []) if f.get("passed")),
                    decided_by_evidence=decision.confidence_source == "measured",
                    note=decision.reason[:120],
                )
            )
            self._persist_steps(session, steps)
            emit(
                "agent.step",
                action=action.value,
                index=len(steps),
                duration_ms=duration_ms,
                request_id=request_id,
            )
            self._record_sensorium(session, steps, budget, request_id)
            if terminal is not None:
                return terminal
            # 外环监督（2026-11-05）：每完成一步先过 post_tool，再回巢。
            # hook 只能建议，终止由这里决定——领域层不碰状态机（MUST-07）。
            hook_outcome = await self._hooks.run_phase(
                "post_tool",
                HookContext(
                    phase="post_tool",
                    session_state=session.state,
                    data=session.data,
                ),
            )
            if hook_outcome.data:
                session.data.update(hook_outcome.data)
            if hook_outcome.verdict == "halt":
                emit(
                    "agent.hook_halt",
                    reason=hook_outcome.reason,
                    action=action.value,
                    request_id=request_id,
                )
                await self._act_abort(session, reason=hook_outcome.reason or "hook_halt")
                return self._snapshot(session, "aborted")
            if hook_outcome.verdict == "correct":
                session.data["hook_correction"] = hook_outcome.reason
            elif session.data.get("hook_correction"):
                # 纠偏只作用于紧接的下一轮决策，用过即清，避免长期污染 prompt
                session.data.pop("hook_correction", None)
            # 回巢：执行态只能经 AGENTIC 再进下一个执行态（星型拓扑不变量）
            await hop(session, FlowState.AGENTIC, self._sessions)
            if budget.is_exhausted(steps):
                await self._act_abort(session, reason="budget_exhausted")
                return self._snapshot(session, "aborted")
            verdict = evaluate_convergence(steps, warned_at_l2=warned)
            if verdict.should_abort:
                await self._act_abort(session, reason=verdict.reason)
                return self._snapshot(session, "aborted")
            if verdict.level >= 2:
                warned = True
                await _notify(session, progress, verdict.reason)

    async def _execute_action(
        self,
        action: AgentAction,
        session: FlowSession,
        *,
        request_id: str,
        progress: ProgressSink | None = None,
    ) -> FlowSnapshot | None:
        """执行一个动作。返回非 None 表示本轮就地结束（等用户 / 交付 / 放弃）。"""
        if action is AgentAction.RETRIEVE:
            # 已定位且取证新鲜时 _act_retrieve 内部直接复用，不会重跑 ripgrep
            ok = await self._act_retrieve(
                session,
                str(session.data.get("sentence", "")),
                str(session.data.get("project_root", "")),
                request_id=request_id,
                progress=progress,
            )
            return None if ok else self._snapshot(session, "ask")

        if action in (AgentAction.PROBE, AgentAction.ASK):
            has_unknowns = await self._act_probe(session, request_id=request_id, progress=progress)
            if action is AgentAction.ASK and has_unknowns:
                await hop(session, FlowState.ASKING, self._sessions)
                await self._finish_turn(session)
                return self._snapshot(session, "ask")
            return None  # probe 只研判，问不问由下一步决定

        if action is AgentAction.GENERATE:
            # agentic 允许跳过 RETRIEVING/PROBE 直接生成：先查证据新鲜度（改了代码
            # 仍用旧证据会产出错误行号），再补研判（档位/追问/推荐全依赖它）。
            await self._check_evidence_freshness(session, request_id=request_id, stage="generate")
            if "facts_complete" not in session.data:
                await self._act_probe(session, request_id=request_id, progress=progress)
            await self._act_generate(session, progress=progress)
            return None

        if action is AgentAction.RANK:
            variants = [VariantDraft(**item) for item in session.data.get("variants", [])]
            if len(variants) < 2:
                return None  # MUST-28：单套不打分，也不计算 d
            await self._act_rank(session, variants, progress=progress)
            return None

        if action is AgentAction.REPLY:
            # 回答里也可能引用行号，过期同样要披露
            await self._check_evidence_freshness(session, request_id=request_id, stage="reply")
            return await self._act_reply(session, progress=progress)

        if action is AgentAction.DELIVER:
            await self._check_evidence_freshness(session, request_id=request_id, stage="deliver")
            return await self._act_deliver(session, progress=progress)

        await self._act_abort(session, reason="模型放弃本轮")
        return self._snapshot(session, "aborted")

    def _persist_steps(self, session: FlowSession, steps: list[AgentStep]) -> None:
        """把动作序列写进 session.data（随 payload 落库，供快照与排障读取）。"""
        session.data["agent_steps"] = [
            {
                "index": step.index,
                "action": step.action.value,
                "outcome": step.outcome.value,
                "duration_ms": step.duration_ms,
                "facts_passed": step.facts_passed,
                "note": step.note,
            }
            for step in steps
        ]

    def _record_sensorium(
        self,
        session: FlowSession,
        steps: Sequence[AgentStep],
        budget: AgentBudget,
        request_id: str,
    ) -> None:
        """六维状态观测（shadow）：只落库与发事件，**不参与熔断判定**。

        关闭态不存在——它本来就是观测层，参与决策前不需要开关；等真实数据证明
        六维与熔断结果一致，再由 `convergence` 主动消费。
        """
        claim_report = session.data.get("claim_report")
        coverage = (
            float(claim_report["coverage"])
            if isinstance(claim_report, dict) and "coverage" in claim_report
            else None
        )
        snapshot = compute_sensorium(
            SensoriumInput(
                steps=tuple(steps),
                max_steps=budget.max_steps,
                cost_tokens=int(session.data.get("cost_tokens", 0)),
                cost_budget=int(self._cfg.followup_cost_budget),
                claim_coverage=coverage,
                notes_hit=int(session.data.get("notes_hit", 0)),
                turn_index=int(session.data.get("turn_index", 0)),
            )
        )
        session.data["sensorium"] = snapshot.as_payload()
        emit("agent.sensorium", score=snapshot.score, request_id=request_id)

    @staticmethod
    def _account_llm_usage(session: FlowSession, usage: dict[str, int | None] | None) -> None:
        """累加本轮 token 用量；缓存命中单独记账。

        供应商未返回缓存命中信息时**不写该键**——0 与「没有缓存」含义不同，不虚报。
        """
        if not usage:
            return
        session.data["cost_tokens"] = int(session.data.get("cost_tokens", 0)) + int(
            usage.get("total_tokens") or 0
        )
        cached = usage.get("cached_tokens")
        if cached is not None:
            session.data["cost_cached_tokens"] = int(
                session.data.get("cost_cached_tokens", 0)
            ) + int(cached)

    async def _abort_quietly(self, session: FlowSession) -> None:
        """失败兜底（6G 遗留①）：异常路径置 ABORTED，避免死会话（如 PROBING）残留污染历史。"""
        try:
            await transition(session, FlowState.ABORTED, self._sessions)
        except Exception:
            logger.exception("state.abort_failed", extra={"session_id": session.session_id})

    async def list_history(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> Page[SessionSummary]:
        """GET /history 转正（T6-11）：脱敏会话摘要（无原句明文，MUST-19）。

        分页：取 ``limit+1`` 条探测是否还有下一页，不额外做 COUNT 查询。
        """
        rows = await self._sessions.list_recent(user_id, limit=limit + 1, offset=offset)
        return Page(
            items=tuple(rows[:limit]),
            has_more=len(rows) > limit,
            limit=limit,
            offset=offset,
        )

    async def list_turns(
        self, user_id: str, session_id: str, *, limit: int = 20, offset: int = 0
    ) -> Page[TurnRecord]:
        """会话的轮次（按 turn_index 升序）；归属不符抛 6003。

        分页：``offset`` 从最新一轮往回数（前端「加载更早」）。
        """
        await self._load_owned(user_id, session_id)
        if self._turns is None:
            return Page(items=(), has_more=False, limit=limit, offset=offset)
        rows = await self._turns.list_for_session(session_id, limit=limit + 1, offset=offset)
        return Page(
            items=tuple(rows[:limit]),
            has_more=len(rows) > limit,
            limit=limit,
            offset=offset,
        )

    async def load_turn(self, user_id: str, turn_id: str) -> TurnRecord:
        """单轮全文（懒加载用）；不存在或非本人抛 6003。"""
        record = None if self._turns is None else await self._turns.load(turn_id)
        if record is None:
            raise StateError("轮次不存在", code=6003, context={"turn_id": turn_id})
        await self._load_owned(user_id, record.session_id)
        return record

    async def rename_session(self, user_id: str, session_id: str, title: str) -> None:
        """PATCH /history/{session_id} 重命名：写 custom_title（截断 ≤80）。

        CAS 冲突（乐观锁 MUST-11）重试一次；仍失败抛 6003。
        """
        clean = title.strip()[:80]
        session = await self._load_owned(user_id, session_id)
        session.data["custom_title"] = clean
        if not await self._sessions.save(session):
            session = await self._load_owned(user_id, session_id)  # 重新加载取新版本
            session.data["custom_title"] = clean
            if not await self._sessions.save(session):
                raise StateError(
                    "会话版本冲突，拒绝写入（乐观锁）",
                    code=6003,
                    context={"session_id": session_id},
                )

    async def pin_session(self, user_id: str, session_id: str, pinned: bool) -> None:
        """PATCH /history/{session_id} 置顶：写 pinned（布尔）；CAS 冲突重试一次后抛 6003。"""
        value = bool(pinned)
        session = await self._load_owned(user_id, session_id)
        session.data["pinned"] = value
        if not await self._sessions.save(session):
            session = await self._load_owned(user_id, session_id)
            session.data["pinned"] = value
            if not await self._sessions.save(session):
                raise StateError(
                    "会话版本冲突，拒绝写入（乐观锁）",
                    code=6003,
                    context={"session_id": session_id},
                )

    async def delete_session(self, user_id: str, session_id: str) -> None:
        """DELETE /history/{session_id}：归属校验后物理删除。"""
        await self._load_owned(user_id, session_id)
        await self._sessions.delete(session_id)

    async def delete_project_sessions(self, user_id: str, project_root: str) -> int:
        """DELETE /history?project_root=：删除该项目下全部会话记录（磁盘文件不动），返回条数。"""
        target = project_root.strip()
        if target == "":
            raise DevPromptError("缺少必填参数：project_root", code=1001)
        return await self._sessions.delete_by_project(user_id, target)

    def _registry_view(self) -> list[dict[str, Any]]:
        """注册表脱敏视图（F-604 多模型）：api_key 恒脱敏；is_active 由激活位比对得出。

        2026-09-17 模型管理迁移：增 `capabilities` 只读字段，
        供设置中心渲染能力徽标与参数编辑器。两者已在读侧归一化，此处只做脱敏与透出。
        """
        registry = read_model_registry()
        active_id = registry["active_model_id"]
        views: list[dict[str, Any]] = []
        for entry in registry["models"]:
            entry_id = str(entry.get("id", ""))
            capabilities = entry.get("capabilities")
            views.append(
                {
                    "id": entry_id,
                    "provider_id": str(entry.get("provider_id", "")),
                    "provider": str(entry.get("provider", "")),
                    "model_id": str(entry.get("model_id", "")),
                    "is_active": entry_id == active_id,
                    "capabilities": dict(capabilities) if isinstance(capabilities, dict) else {},
                    "api_mode": str(entry.get("api_mode", "") or ""),
                    "reasoning_effort": str(entry.get("reasoning_effort", "") or ""),
                    "max_context_length": entry.get("max_context_length"),
                }
            )
        return views

    @staticmethod
    def _provider_configs_view() -> list[dict[str, Any]]:
        """供应商配置脱敏视图（2026-10-18 供应商中心化）：api_key 恒脱敏（MUST-19）。"""
        return [
            {
                "id": str(record.get("id", "")),
                "provider": str(record.get("provider", "")),
                "base_url": str(record.get("base_url", "")),
                "api_key_masked": mask_secret(str(record.get("api_key", ""))),
            }
            for record in read_model_registry()["providers"]
        ]

    @staticmethod
    def _merge_provider_configs(
        incoming: list[dict[str, Any]], existing: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """供应商**权威列表**归并：id 缺省生成（p- + uuid）；api_key 空则沿用旧值。

        绝不做深合并——否则用户删掉的供应商会被「礼貌地」保留回来。

        密钥回落两级：①同 id 旧记录；②**同 (provider, base_url) 的旧记录**。
        第二级是安全网：前端会为新供应商自行生成 id，一旦 id 对不上而密钥又没填，
        只靠①会把密钥静默清空——而同一端点的凭据本就是同一份。
        """
        by_id = {str(e.get("id")): e for e in existing if e.get("id")}
        # 同端点索引：安全网，见 docstring 第二级回落
        by_endpoint = {
            (str(e.get("provider") or "").strip().lower(), str(e.get("base_url") or "").strip()): e
            for e in existing
        }
        merged: list[dict[str, Any]] = []
        for raw in incoming:
            record_id = str(raw.get("id") or "").strip() or f"p-{uuid.uuid4().hex[:8]}"
            provider = str(raw.get("provider") or "").strip()
            base_url = str(raw.get("base_url") or "").strip()
            old = by_id.get(record_id) or by_endpoint.get((provider.lower(), base_url))
            api_key = raw.get("api_key")
            # 空值/None = 沿用同 id 旧值：前端只有脱敏值，回传空串是常态
            if api_key in (None, ""):
                api_key = str((old or {}).get("api_key", ""))
            merged.append(
                {
                    "id": record_id,
                    "provider": provider,
                    "base_url": base_url,
                    "api_key": str(api_key or ""),
                }
            )
        return merged

    @staticmethod
    def _merge_registry_entries(
        incoming: list[dict[str, Any]],
        existing: list[dict[str, Any]],
        provider_configs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """整表替换解析：id 缺省则生成（m- + uuid）。

        2026-10-18 供应商中心化：条目经 ``provider_id`` 引用供应商，端点与密钥
        从供应商记录解析后展平进条目——**镜像逻辑与 AppConfig 取值路径因此零改动**。
        ``provider_id`` 指向不存在的供应商时该条目直接跳过（级联删除的兜底，
        正常路径由 :meth:`_validate_registry_entries` 先拦下并整单拒绝）。

        绝不做深合并，否则用户删除的参数会被「礼貌地」保留回来。
        """
        by_id = {str(e.get("id")): e for e in existing if e.get("id")}
        by_provider_id = {str(p.get("id")): p for p in provider_configs}
        merged: list[dict[str, Any]] = []
        for raw in incoming:
            entry_id = str(raw.get("id") or "").strip() or f"m-{uuid.uuid4().hex[:8]}"
            old = by_id.get(entry_id, {})
            record = by_provider_id.get(str(raw.get("provider_id") or "").strip())
            if record is None:
                continue
            provider = str(record.get("provider") or "").strip()
            model_id = str(raw.get("model_id") or "").strip()

            # api_mode：整体替换（None=沿用），并按 provider 的 supported_api_modes 收敛
            mode_in = raw.get("api_mode")
            mode_source = old.get("api_mode", "") if mode_in is None else mode_in
            api_mode = resolve_api_mode(provider, str(mode_source or ""))
            # 以下两者：空值 = 沿用旧值 / 不下发
            effort_in = raw.get("reasoning_effort")
            effort_source = old.get("reasoning_effort", "") if effort_in is None else effort_in
            effort = effort_source if isinstance(effort_source, str) else ""
            window_in = raw.get("max_context_length")
            window_source = old.get("max_context_length") if window_in is None else window_in
            window = window_source if isinstance(window_source, int) and window_source > 0 else None

            merged.append(
                {
                    "id": entry_id,
                    "provider_id": str(record.get("id", "")),
                    "provider": provider,
                    "base_url": str(record.get("base_url") or "").strip(),
                    "api_key": str(record.get("api_key") or ""),
                    "model_id": model_id,
                    "api_mode": api_mode,
                    "reasoning_effort": effort,
                    "max_context_length": window,
                }
            )
        return merged

    async def get_settings(self) -> dict[str, Any]:
        """F-604 读设置（T6-11）：有效配置视图（env 已并入）；api_key 恒脱敏，候选上限锁定只读。

        2026-10-18 供应商中心化重构：`provider_configs` 段是**用户自己配置的供应商**
        （端点 + 密钥，一个端点一份，密钥只脱敏回显）；`providers` 段仍是静态厂商目录
        （只读，下拉与档位的数据源）。两段同名易混，故前者带 `_configs` 后缀。
        复用本端点下发而非新增路径——契约仍 13 路径 / 16 操作。
        """
        cfg = self._cfg
        return {
            "models": self._registry_view(),
            "provider_configs": self._provider_configs_view(),
            "providers": providers_projection(),
            "model_service": {
                "provider": cfg.llm_provider,
                "base_url": cfg.llm_base_url,
                "api_key_masked": mask_secret(cfg.llm_api_key),
                "model_id": cfg.llm_model,
                "timeout": cfg.llm_timeout,
                "temperature": cfg.llm_temperature,
                "max_tokens": cfg.llm_max_tokens,
            },
            "process": {
                "followup_soft_round_guard": cfg.followup_soft_round_guard,
                "followup_cost_budget": cfg.followup_cost_budget,
                "telemetry": cfg.telemetry,
            },
            "locked": {"candidate_limit": MAX_CANDIDATES},  # MUST-09 宪法常量，只读下发
        }

    @staticmethod
    def _validate_registry_entries(merged: list[dict[str, Any]]) -> list[str]:
        """写盘前校验注册表条目。返回问题描述列表（空 = 通过）。

        N-5 为什么要这一步：`_merge_registry_entries` 已做到「先算清再一次性写」，
        但它对**内容合法性**不设防——一个 `model_id` 为空的条目会被完整写入并可能成为
        激活项，用户得到的是「已保存」却根本调不通。宁可整单拒绝，也不要半成品。
        """
        problems: list[str] = []
        for index, entry in enumerate(merged):
            name = str(entry.get("model_id") or entry.get("id") or f"第 {index + 1} 项")
            if not str(entry.get("model_id", "")).strip():
                problems.append(f"{name}：缺少模型标识（model_id）")
            if not str(entry.get("base_url", "")).strip():
                problems.append(f"{name}：缺少服务地址（base_url）")
            api_key = entry.get("api_key", "")
            if api_key is not None and not isinstance(api_key, str):
                problems.append(f"{name}：api_key 必须是字符串")
        return problems

    async def update_settings(
        self, update: dict[str, Any], *, request_id: str = ""
    ) -> dict[str, Any]:
        """PUT /settings（T6-11 + 多模型注册表 F-604）：模型段写设置文件（0600）、流程段写表并应用。

        多模型注册表：``models`` 整表替换（api_key 空=沿用同 id 旧值）；``active_model_id`` 切换后
        把该条目**整体镜像**写入 model_service（provider/base_url/api_key/model_id）——AppConfig 与
        llm.py 取值路径零改动，密钥仍只落 0600 文件（MUST-19）。显式 model_service 段仍受支持。
        api_key 语义：空值/None = 保持不变；仅显式新值落盘（明文只进设置文件，不进库不进日志）。

        N-5 两阶段：先算清并校验全部条目 → 无误才单次原子写。任一条目不合法即整单拒绝，
        **不触碰存储**，避免留下「已保存但调不通」的半成品。
        N-6 部分失败可见：`skipped` 非空（如激活位指向不存在的条目）不报错但记事件与 context。
        """
        model_in: dict[str, Any] = dict(update.get("model_service") or {})
        process_in: dict[str, Any] = dict(update.get("process") or {})
        providers_in = update.get("provider_configs")
        models_in = update.get("models")
        active_in = update.get("active_model_id")
        skipped: list[str] = []
        registry = read_model_registry()
        # 供应商段为权威列表：未出现的记录删除，其下条目随 models 整表替换一并消失
        provider_configs = (
            self._merge_provider_configs([dict(p) for p in providers_in], registry["providers"])
            if providers_in is not None
            else registry["providers"]
        )

        # 注册表处理先于显式 model_service 段（后者若给同键可覆盖镜像值）
        if models_in is not None or active_in not in (None, "") or providers_in is not None:
            merged = (
                self._merge_registry_entries(
                    [dict(m) for m in models_in], registry["models"], provider_configs
                )
                if models_in is not None
                else registry["models"]
            )
            problems = self._validate_registry_entries(merged)
            if problems:
                raise ConfigurationError(
                    "模型注册表校验未通过，未写入任何改动：\n"
                    + "\n".join(f"  - {p}" for p in problems),
                    context={"problems": problems},
                )
            active_id = str(active_in).strip() if active_in not in (None, "") else ""
            if active_id and not any(str(e.get("id")) == active_id for e in merged):
                skipped.append("激活位指向不存在的条目，已保持原激活项")
                active_id = ""  # 激活位指向不存在条目：忽略该切换
            await asyncio.to_thread(
                write_model_registry,
                merged,
                active_id or None,
                provider_configs if providers_in is not None else None,
            )
            if skipped:
                emit(
                    "settings.updated",
                    skipped=len(skipped),
                    reasons=skipped,
                    request_id=request_id,
                )
            active_entry = next((e for e in merged if str(e.get("id")) == active_id), None)
            if active_entry is not None:
                mirror = {
                    "provider": str(active_entry.get("provider", "")),
                    "base_url": str(active_entry.get("base_url", "")),
                    "api_key": str(active_entry.get("api_key", "")),
                    "model_id": str(active_entry.get("model_id", "")),
                    # 该条目的参数覆盖（已按 provider 清洗）——让每模型参数真正生效
                    "llm_params": {},
                    # 该条目的 API 形态——让协议分流真正生效
                    "api_mode": str(active_entry.get("api_mode", "") or ""),
                    # 条目级上下文窗口：条目选中档位优先，其次回落到动态目录 / 静态表
                    # （dynamic 优先口径；仅告警不截断，F-918/MUST-25）
                    "max_context_length": self.effective_window(
                        str(active_entry.get("provider", "")),
                        str(active_entry.get("model_id", "")),
                        active_entry.get("max_context_length")
                        if isinstance(active_entry.get("max_context_length"), int)
                        else None,
                    )
                    or 0,
                }
                # reasoning_effort 并入 llm_params——这样 extra_body_params() 能读到它，
                # 无需 AppConfig 再加一个专用字段（KISS）。
                entry_effort = str(active_entry.get("reasoning_effort", "") or "")
                if entry_effort:
                    current = mirror.get("llm_params")
                    merged_params: dict[str, Any] = (
                        dict(current) if isinstance(current, dict) else {}
                    )
                    merged_params["reasoning_effort"] = entry_effort
                    mirror["llm_params"] = merged_params
                await asyncio.to_thread(write_model_settings, mirror)
                for src_key, value in mirror.items():
                    setattr(self._cfg, MODEL_KEY_MAP[src_key], value)

        api_key = model_in.pop("api_key", None)
        if api_key:  # 非空才替换（空值/None = 不变）
            model_in["api_key"] = api_key
        model_write = {k: v for k, v in model_in.items() if v is not None}
        process_write = {k: v for k, v in process_in.items() if v is not None}
        if model_write:
            await asyncio.to_thread(write_model_settings, model_write)
        if process_write:
            await asyncio.to_thread(write_process_settings, process_write)
        for src_key, value in model_write.items():
            setattr(self._cfg, MODEL_KEY_MAP[src_key], value)
        for key, value in process_write.items():
            setattr(self._cfg, key, value)
        self._cfg.validate()
        set_telemetry(self._cfg.telemetry)
        settings = await self.get_settings()
        if skipped:
            # N-6：响应契约不变（不加字段），但把「跳过了什么」放进 context 供日志/测试检索
            settings["skipped"] = skipped
        return settings

    async def scan_project(self, project_root: str) -> dict[str, Any]:
        """F-101 只读统计（Web /project/scan 薄透传）：符号总数/文件数/类别分布。

        2026-10-20：异常转成带码的 DevPromptError（2001/2004）。此前裸抛 → 500 →
        前端只能猜测「路径不存在」，真实原因（工具失败）被掩盖。
        """
        if not await asyncio.to_thread(Path(project_root).is_dir):
            raise DevPromptError("项目路径不存在或不是目录", code=2001)
        try:
            table = await self._symbols_provider.get(project_root)
        except ProcessError as exc:
            raise DevPromptError("扫描失败：ctags 执行异常", code=2004) from exc
        files: set[str] = set()
        kind_counts: dict[str, int] = {}
        for s in table.symbols:
            files.add(s.path)
            kind_counts[s.kind] = kind_counts.get(s.kind, 0) + 1
        ranked = dict(sorted(kind_counts.items(), key=lambda kv: (-kv[1], kv[0])))
        return {
            "total_symbols": len(table.symbols),
            "total_files": len(files),
            "kind_counts": ranked,
        }

    async def _edited_similarity(self, session_id: str, edited_text: str, variant: str) -> float:
        """编辑相似度：difflib.SequenceMatcher.ratio（标准库，MUST-04）。

        以会话内被采纳档位的方案正文为基准（采纳必须绑定档位，variant 恒非空）；
        档位缺失时会话/方案按 0 相似度处理（无法核对编辑来源 → 编辑距离占比 1.0
        → 零方向信号，不误更新偏好）。
        """
        session = await self._sessions.load(session_id)
        original = ""
        if session is not None:
            items = [v for v in session.data.get("variants", []) if isinstance(v, dict)]
            chosen = next((v for v in items if v.get("level") == variant), None)
            if chosen is None and items:
                chosen = items[0]
            if chosen is not None:
                original = str(chosen.get("body", ""))
        return difflib.SequenceMatcher(None, original, edited_text).ratio()

    def _observe_probe(self, probe: FactProbeOutput, request_id: str) -> None:
        """记录任务类型与提问形态合规。

        只发码与计数，**不含模型原文**（MUST-19）；不合规不阻断流程——
        用户 2026-10-20 裁定「原样展示，仅告警」。
        """
        emit(
            "followup.task_kind",
            task_kind=probe.task_kind,
            questions=len(probe.questions),
            request_id=request_id,
        )
        issues = lint_questions(probe.questions)
        if issues:
            emit_warning("followup.question_lint", issues=issues, request_id=request_id)

    def _suppress_ask(self, probe: FactProbeOutput, facts: Sequence[FactResult]) -> bool:
        """信息充足即不再提问（2026-11-03）：执行类 + 七项取证全过时丢弃模型给的 questions。

        判据只看取证结果：``overall_confidence`` 在工具调用路径上是 no_data（2026-11-04，
        此前被强制成 0.0），拿它当闸门等于永不生效。设计类（``task_kind='design'``）
        保留 MUST-26 的五类深挖，不抑制。
        """
        return probe.task_kind != "design" and is_evidence_complete(facts)

    def _track_ask_adoption(self, session: FlowSession, unknowns: Sequence[UnknownItem]) -> None:
        """追问采纳测量（2026-11-04）：统计本轮问出的未知项与既往重复的比例。

        - 只存 key 的 hash，不存问题原文（MUST-19）；
        - 首轮（rounds == 0）不计算重复率，避免把首问当成未采纳；
        - 同一问题在追问轮被重复问出 → ``followup.expect_unmet``，据此评估提问纪律。
        """
        if not unknowns:
            return
        previous: list[str] = list(session.data.get("asked_keys", []) or [])
        current = [sha256_hex(u.key)[:16] for u in unknowns]
        repeated = len(set(current) & set(previous))
        rounds = int(session.data.get("rounds", 0))
        if repeated > 0 and rounds > 0:
            emit(
                "followup.expect_unmet",
                repeated=repeated,
                total=len(current),
                request_id=session.data.get("last_request_id", ""),
            )
        # 累计去重并限长：只留最近 20 个，防止长会话无界增长
        session.data["asked_keys"] = list(dict.fromkeys(current + previous))[:20]

    def _validate_inherited_clarifications(self, session: FlowSession, request_id: str) -> None:
        """跨轮澄清的归属校验：目标变了就作废上一轮的答案。

        上一轮答的「改列表页」只对同一个目标成立；目标换掉后继续沿用，会把
        无关约束带进本轮 prompt（答案直接进生成上下文），反而污染输出。
        作废时只记澄清键的 hash，不记问题原文（MUST-19）。
        """
        clarifications = session.data.get("clarifications") or {}
        if not clarifications:
            return
        previous = session.data.get("turn_memory")
        previous_target = previous.get("target") if isinstance(previous, dict) else None
        current = session.data.get("target")
        if not isinstance(previous_target, dict) or not isinstance(current, dict):
            return
        same = previous_target.get("name") == current.get("name") and previous_target.get(
            "path"
        ) == current.get("path")
        if same:
            return
        session.data["clarifications"] = {}
        session.data["clarifications_invalidated"] = len(clarifications)
        emit(
            "followup.clarifications_invalidated",
            count=len(clarifications),
            keys=[sha256_hex(str(key))[:16] for key in clarifications],
            request_id=request_id,
        )

    async def _act_probe(
        self,
        session: FlowSession,
        *,
        request_id: str,
        progress: ProgressSink | None = None,
        answered: dict[str, str] | None = None,
    ) -> bool:
        """研判取证结果，写入 unknowns / facts_complete / level，返回「是否有未决问题」。

        只做研判、不做路由：转不转 ASKING 由调用方决定——agentic 循环据此回 AGENTIC，
        线性路径直接进 ASKING。两条路径共用这一份研判逻辑（MUST-10 单一实现）。
        """
        facts = [FactResult(**f) for f in session.data.get("facts", [])]
        probe = await self._decider.probe_facts(session.data["sentence"], facts, answered=answered)
        self._observe_probe(probe, request_id)
        if probe.ask_call_id:
            # AskUserQuestion 的 call_id：只落审计信息，不含原句（MUST-19）
            session.data["pending_tool_call"] = probe.ask_call_id
        confidence = probe.overall_confidence
        measured = probe.confidence_source == "measured" and confidence is not None
        session.data["probe_confidence"] = confidence
        session.data["confidence_source"] = probe.confidence_source
        unknowns = build_unknowns(
            probe,
            facts,
            clarifications=session.data.get("clarifications"),
            answered_header_set=answered_headers(
                session.data.get("clarifications", {}), session.data.get("unknowns", [])
            ),
        )
        if unknowns and self._suppress_ask(probe, facts):
            # 审计只记数量与原因码，不记问题原文（MUST-19）
            emit(
                "followup.question_suppressed",
                reason="evidence_complete",
                count=len(unknowns),
                request_id=request_id,
            )
            session.data["suppressed_questions"] = len(unknowns)
            unknowns = []
        session.data["unknowns"] = [dataclasses.asdict(u) for u in unknowns]
        self._track_ask_adoption(session, unknowns)
        # 2026-11-04：模型未给判断（no_data）不再等同于「置信度 0」。
        # 七项全过且无待答问题时按完备处理；确有未决项仍停在低档（那是真的未知）。
        evidence_ok = is_evidence_complete(facts)
        facts_complete = evidence_ok and (
            (measured and confidence is not None and confidence >= self._cfg.fact_probe_threshold)
            or (not measured and not unknowns)
        )
        has_symbol = bool(session.data.get("target"))
        session.data["facts_complete"] = facts_complete
        session.data["level"] = resolve_level(has_symbol=has_symbol, facts_complete=facts_complete)
        await _notify(
            session,
            progress,
            level_text(str(session.data["level"]), confidence, _session_locale(session)),
        )
        if unknowns:
            await _notify(
                session,
                progress,
                clarification_text(len(unknowns), _session_locale(session)),
            )
        return bool(unknowns)

    async def _probe_and_route(
        self,
        session: FlowSession,
        *,
        request_id: str,
        progress: ProgressSink | None = None,
    ) -> FlowSnapshot:
        has_unknowns = await self._act_probe(session, request_id=request_id, progress=progress)
        if has_unknowns:
            await hop(session, FlowState.ASKING, self._sessions)
            await self._finish_turn(session)
            return self._snapshot(session, "ask")
        return await self._generate_and_finish(session, progress=progress)

    async def _reprobe(
        self, session: FlowSession, *, progress: ProgressSink | None = None
    ) -> FlowSnapshot:
        """F-204：答复后重新研判（取证结果不变，clarifications 已更新）。"""
        await _notify(session, progress, "正在根据你的答复重新研判…")
        request_id = str(session.data.get("last_request_id", ""))
        has_unknowns = await self._act_probe(
            session,
            request_id=request_id,
            progress=progress,
            answered=dict(session.data.get("clarifications", {})),
        )
        guard = GuardrailState(
            rounds=int(session.data.get("rounds", 0)),
            cost_tokens=int(session.data.get("cost_tokens", 0)),
        )
        if guard.should_trigger(self._cfg):
            emit(
                "followup.guardrail",
                rounds=guard.rounds,
                cost_tokens=guard.cost_tokens,
                request_id=request_id,
            )
            await self._finish_turn(session)
            return self._snapshot(session, "guardrail")  # 停在 CONFIRMING 等裁决（6002 语义）
        if has_unknowns:
            await hop(session, FlowState.ASKING, self._sessions)
            await self._finish_turn(session)
            return self._snapshot(session, "ask")
        return await self._generate_and_finish(session, progress=progress)

    async def _generation_context(
        self, session: FlowSession, *, level: Level | None = None
    ) -> GenerationContext:
        """装配生成/回答共用的上下文（2026-11-05 抽出，避免两处漂移）。

        回答「为什么选 B」所依赖的 ``previous_variants`` 与 ``history_block``
        与生成完全同源，因此不另建上下文类型。
        """
        context_payload = await self._assemble_context(session)
        return GenerationContext(
            sentence=session.data["sentence"],
            project_root=session.data["project_root"],
            level=level or session.data.get("level", "A"),
            facts_summary=session.data.get("facts_summary", _summarize_facts(session)),
            clarifications=session.data.get("clarifications", {}),
            conservative=bool(session.data.get("conservative", False)),
            history_block=context_payload.history_block,
            memory_block=context_payload.memory_block,
            # 迭代轮要让模型看到上一轮原文，否则「把 B 档第 2 条改成 X」无法定位
            previous_variants=_render_previous_variants(
                TurnMemory.from_payload(session.data.get("turn_memory")).variants
            ),
            # 上一轮推荐判定：回答「为什么选 B」的唯一依据来源
            ranking_summary=_render_ranking(
                session.data.get("ranking"), session.data.get("ranking_details")
            ),
        )

    async def _act_generate(
        self, session: FlowSession, *, progress: ProgressSink | None = None
    ) -> list[VariantDraft]:
        """生成方案并写入 ``session.data["variants"]``。

        只做生成，不做交付判定——是否打分、是否收尾由调用方决定
        （线性路径串联，agentic 循环由模型选下一步）。
        """
        await hop(session, FlowState.GENERATING, self._sessions)
        ctx = await self._generation_context(session)
        levels = plan_levels(
            ctx.level,
            max_versions=3 if self._should_offer_three(session) else 1,
            preferred=_preferred_level(session),
        )
        await _notify(session, progress, generation_text(levels, _session_locale(session)))
        # U-7：记下期望套数，交付门据实际产出披露「本次仅 N 套」（模型可只给子集）。
        session.data["expected_variant_count"] = len(levels)
        multi = await self._generator.generate_variants(ctx, levels)
        self._account_llm_usage(session, last_usage())
        # slots dataclass 无 __dict__，序列化必须走 model_dump（计划 §6.2 注意事项）
        session.data["variants"] = [v.model_dump() for v in multi.variants]
        self._audit_claims(session, multi.variants)
        return list(multi.variants)

    def _audit_claims(self, session: FlowSession, variants: Sequence[VariantDraft]) -> None:
        """C 档断言对账（2026-11-04）：覆盖率不足则降档并留痕，不重新生成。

        只改本轮可输出档位，不改各套自身的 level 字段——那等于篡改模型原文。
        缺口经 ``claim_report.summary`` 如实披露（MUST-27 的诚实原则）。
        """
        facts = [FactResult(**f) for f in session.data.get("facts", [])]
        reports = [validate_claims(v, facts) for v in variants]
        total = sum(r.total for r in reports)
        covered = sum(r.covered for r in reports)
        uncovered = tuple(item for r in reports for item in r.uncovered)
        report = ClaimReport(
            total=total,
            covered=covered,
            uncovered=uncovered,
            coverage=(covered / total) if total else 0.0,
            undeclared=(total == 0),
        )
        session.data["claim_report"] = {
            "total": report.total,
            "covered": report.covered,
            "uncovered": list(report.uncovered),
            "coverage": report.coverage,
            "undeclared": report.undeclared,
            "summary": report.render(),
        }
        if session.data.get("level") != "C":
            return
        if report.undeclared:
            # 一条引用都没声明：默认只披露（灰度），claim_strict 打开后才降档。
            # 不声明不等于没有引用，这是对账唯一可被绕过的口子。
            if not self._cfg.claim_strict:
                return
            session.data["level"] = "B"
            emit(
                "evidence.claim_undeclared",
                request_id=session.data.get("last_request_id", ""),
            )
            return
        if report.coverage >= CLAIM_COVERAGE_MIN:
            return
        session.data["level"] = "B"
        emit(
            "evidence.claim_uncovered",
            total=report.total,
            covered=report.covered,
            request_id=session.data.get("last_request_id", ""),
        )

    async def _act_rank(
        self,
        session: FlowSession,
        variants: list[VariantDraft],
        *,
        progress: ProgressSink | None = None,
    ) -> RankingView | None:
        """对多套方案打分并写入 ``session.data["ranking"]``。"""
        await transition(session, FlowState.RANKING, self._sessions)
        await _notify(session, progress, scoring_text(_session_locale(session)))
        ranking = await self._rank_and_mark(session, variants)
        session.data["ranking"] = dataclasses.asdict(ranking) if ranking is not None else None
        if ranking is not None:
            await _notify(
                session,
                progress,
                recommendation_text(
                    ranking.marked,
                    ranking.variant,
                    ranking.gap,
                    ranking.reason,
                    _session_locale(session),
                ),
            )
        return ranking

    async def _act_reply(
        self, session: FlowSession, *, progress: ProgressSink | None = None
    ) -> FlowSnapshot:
        """纯回答（2026-11-05）：只产出文字，不写 variants、不改档位与取证。

        与 ``_act_deliver`` 的区别：deliver 交付方案并结算推荐，reply 只回答，
        因此不触发 ``recommendation.skipped`` 这类方案侧事件。
        """
        await hop(session, FlowState.GENERATING, self._sessions)
        ctx = await self._generation_context(session)
        await _notify(session, progress, answering_text(_session_locale(session)))
        text = await self._generator.answer(ctx)
        self._account_llm_usage(session, last_usage())
        session.data["reply_text"] = text
        if FlowState(session.state) is not FlowState.DONE:
            await transition(session, FlowState.DONE, self._sessions)
        self._emit_completed(
            session, variants=len(session.data.get("variants", []) or []), marked=None
        )
        await self._finish_turn(session)
        return self._snapshot(session, "done")

    async def _act_deliver(
        self, session: FlowSession, *, progress: ProgressSink | None = None
    ) -> FlowSnapshot:
        """交付：过证据门 → 转 DONE 并回填产出。单套按 MUST-28 跳过推荐判定。

        门禁只降质量标记（C 档 / 推荐），**不阻断交付**：RED 时方案照常返回，
        只是不标推荐并附披露文案（MUST-27：不标记必须给具体原因）。
        """
        variants = list(session.data.get("variants", []) or [])
        ranking_data = session.data.get("ranking")
        marked: bool | None = None
        if isinstance(ranking_data, dict) and "marked" in ranking_data:
            marked = bool(ranking_data["marked"])
        if len(variants) < 2:
            # MUST-28：单套（仅 A 档）跳过打分与推荐，ranking=None，不计算 d
            emit(
                "recommendation.skipped",
                reason="single-variant",
                gap=None,
                confidence=None,
                request_id=session.data.get("last_request_id", ""),
            )
            await _notify(session, progress, single_variant_text(_session_locale(session)))

        await self._verify_c_anchors(session)
        verdict = self._evaluate_delivery_gate(session, len(variants), marked)
        session.data["delivery_gate"] = {
            "status": verdict.status,
            "tone": verdict.tone,
            "reasons": list(verdict.reasons),
            "can_mark_c": verdict.can_mark_c,
            "can_mark_recommend": verdict.can_mark_recommend,
            "disclosure": verdict.disclosure,
        }
        if not verdict.can_mark_c and session.data.get("level") == "C":
            # 与 _audit_claims 同一规则：只改本轮可输出档位，不动方案正文
            session.data["level"] = "B"
        if verdict.can_mark_recommend is False and marked:
            marked = False
            if isinstance(ranking_data, dict):
                ranking_data["marked"] = False
                ranking_data["reason"] = verdict.disclosure
        if verdict.disclosure:
            emit(
                "delivery.gate",
                status=verdict.status,
                reason="；".join(verdict.reasons),
                request_id=session.data.get("last_request_id", ""),
            )
            await _notify(session, progress, verdict.disclosure)

        if FlowState(session.state) is not FlowState.DONE:
            await transition(session, FlowState.DONE, self._sessions)
        self._emit_completed(session, variants=len(variants), marked=marked)
        await self._finish_turn(session)
        return self._snapshot(session, "done")

    async def _verify_c_anchors(self, session: FlowSession) -> None:
        """U-2：C 档正文锚点后端校验——明确无效则降 B 并披露，判不清不降档。"""
        if session.data.get("level") != "C":
            return
        variants = [v for v in session.data.get("variants", []) if isinstance(v, dict)]
        body = next((str(v.get("body", "")) for v in variants if v.get("level") == "C"), "")
        anchors = extract_anchors(body)
        if not anchors:
            return
        root = str(session.data.get("project_root", ""))
        verdicts: list[tuple[Anchor, bool | None]] = [
            (anchor, await self._probe_anchor(root, anchor)) for anchor in anchors
        ]
        report = verify_anchors(verdicts)
        session.data["anchor_report"] = {
            "total": report.total,
            "invalid": list(report.invalid),
        }
        if report.invalid:
            emit(
                "evidence.anchor_invalid",
                total=report.total,
                invalid=len(report.invalid),
                request_id=session.data.get("last_request_id", ""),
            )

    async def _probe_anchor(self, root: str, anchor: Anchor) -> bool | None:
        """单锚点核验：False=明确无效；None=判不清（保守不降档）。路径为仓库相对形态。"""
        rel = anchor.path.replace("\\", "/")
        full = f"{root}/{rel}" if root else rel
        try:
            if not await self._reader.exists(full):
                return False
            text = await self._reader.read(full)
        except Exception:  # noqa: BLE001 - 读取失败属判不清，保守不降档
            return None
        return 1 <= anchor.line <= len(text.splitlines())

    def _evaluate_delivery_gate(
        self, session: FlowSession, variant_count: int, marked: bool | None
    ) -> DeliveryVerdict:
        """把会话里的证据字段喂给领域判定（这里只做取值与类型归一，不做判定）。"""
        facts = [FactResult(**item) for item in session.data.get("facts", [])]
        claim_report = session.data.get("claim_report")
        coverage: float | None = None
        undeclared = False
        if isinstance(claim_report, dict):
            raw = claim_report.get("coverage")
            coverage = float(raw) if isinstance(raw, (int, float)) else None
            undeclared = bool(claim_report.get("undeclared", False))
        if undeclared:
            # 未声明时 coverage 恒 0，与「声明了但没取证」是两件事：
            # 灰度关闭（claim_strict=False）时整条不参与门禁，保持改造前行为。
            coverage = None
            undeclared = self._cfg.claim_strict
        ranking_data = session.data.get("ranking")
        reason = str(ranking_data.get("reason", "")) if isinstance(ranking_data, dict) else ""
        expected = session.data.get("expected_variant_count")
        anchor_report = session.data.get("anchor_report")
        anchor_invalid = (
            len(anchor_report.get("invalid", [])) if isinstance(anchor_report, dict) else 0
        )
        return evaluate_delivery(
            DeliveryInput(
                has_target=bool(session.data.get("target")),
                facts=facts,
                claim_coverage=coverage,
                claims_undeclared=undeclared,
                variant_count=variant_count,
                expected_variant_count=int(expected)
                if isinstance(expected, (int, float))
                else None,
                anchor_invalid_count=anchor_invalid,
                recommend_marked=marked,
                recommend_reason=reason,
            )
        )

    async def _act_abort(self, session: FlowSession, *, reason: str) -> None:
        """放弃本轮：转 ABORTED 并回填产出。已终态时不再转移。"""
        emit(
            "agent.loop_terminated",
            reason=reason,
            request_id=session.data.get("last_request_id", ""),
        )
        if FlowState(session.state) not in (FlowState.DONE, FlowState.ABORTED):
            await transition(session, FlowState.ABORTED, self._sessions)
        await self._finish_turn(session)

    async def _generate_and_finish(
        self, session: FlowSession, *, progress: ProgressSink | None = None
    ) -> FlowSnapshot:
        """线性路径：GENERATING→(RANKING)→DONE，与 agentic 循环共用同一批动作方法。"""
        variants = await self._act_generate(session, progress=progress)
        if len(variants) >= 2:
            await self._act_rank(session, variants, progress=progress)
        return await self._act_deliver(session, progress=progress)

    def _should_offer_three(self, session: FlowSession) -> bool:
        """三套只在「方向未定」时给（2026-10-20）：首轮 / 信息不完备 / 用户表达分歧。"""
        if int(session.data.get("turn_index", 0)) <= 0:
            return True
        if not bool(session.data.get("facts_complete", False)):
            return True
        if session.data.get("prev_facts_complete") is True and not session.data.get(
            "facts_complete", False
        ):
            return True  # 事实前提失效：上一轮完备、本轮不完备 → 重新展开
        sentence = str(session.data.get("sentence", ""))
        return any(word in sentence for word in _DIRECTION_CONFLICT_WORDS)

    async def _assemble_context(self, session: FlowSession) -> ContextPayload:
        """装配多轮上下文（纯函数在 domain/context）：历史摘要 + 偏好投影。

        L2 项目记忆在下一片接入；这里先传空笔记，保证分层与预算逻辑可独立回归。
        """
        summaries: list[TurnSummary] = []
        if self._turns is not None:
            for record in await self._turns.list_for_session(session.session_id):
                if record.state not in {"DONE", "ASKING"}:
                    continue
                summary = record.summary if isinstance(record.summary, dict) else {}
                summaries.append(
                    TurnSummary(
                        turn_id=record.turn_id,
                        turn_index=record.turn_index,
                        target=str(summary.get("target", "")),
                        conclusion=str(summary.get("conclusion", "")),
                        open_items=tuple(str(item) for item in summary.get("open", []) or []),
                        decision=str(summary.get("decision", "")),
                        rejected=tuple(str(item) for item in summary.get("rejected", []) or []),
                        reply=str(summary.get("reply", "")),
                    )
                )
        target_data = session.data.get("target")
        anchor = anchor_from_payload(session.data.get("turn_anchor"))
        current = TurnInput(
            sentence=str(session.data.get("sentence", "")),
            facts=tuple(
                f"{item.get('key')}={'通过' if item.get('passed') else '未通过'}"
                for item in session.data.get("facts", [])
                if isinstance(item, dict)
            ),
            clarifications=dict(session.data.get("clarifications", {})),
            target=str(target_data.get("name", "")) if isinstance(target_data, dict) else "",
            anchor=render_anchor(anchor) if anchor is not None else "",
        )
        notes: list[str] = []
        if self._notes is not None:
            target_path = str(target_data.get("path", "")) if isinstance(target_data, dict) else ""
            found = await self._notes.search(
                str(session.data.get("project_root", "")),
                target_key=normalize_key(current.target, target_path) if current.target else "",
            )
            notes = [note.render() for note in found]
            # 供六维状态感知的「熟悉度」维度读取（shadow 观测，不影响行为）
            session.data["notes_hit"] = len(notes)
        return build_context(
            summaries,
            current,
            notes=notes,
            budget=ContextBudget(total=self._cfg.max_state_tokens),
        )

    async def _begin_turn(self, session: FlowSession) -> None:
        """占位抢锁：同一 (session_id, turn_index) 只允许一个 turn 在跑（MUST-15）。

        在 LLM 调用之前 INSERT：并发或重复提交在数据库层被拒（6001），
        既不浪费一次生成，也不依赖前端防抖。
        """
        if self._turns is None:
            return
        index = int(session.data.get("turn_index", -1)) + 1
        turn_id = uuid.uuid4().hex
        try:
            await self._turns.append(
                TurnRecord(
                    turn_id=turn_id,
                    session_id=session.session_id,
                    turn_index=index,
                    state=FlowState.INIT.value,
                    input=str(session.data.get("sentence", "")),
                )
            )
        except TurnConflictError as exc:
            raise StateError(
                "该轮次已存在（重复提交或并发请求）",
                code=6001,
                context={"session_id": session.session_id, "turn_index": index},
            ) from exc
        except Exception:  # noqa: BLE001 - 存储故障不阻断主流程（与 feedback 降级一致）
            logger.warning("turn.begin_failed", exc_info=True)
            return
        session.data["turn_index"] = index
        session.data["current_turn_id"] = turn_id

    async def rollback_to_turn(
        self, user_id: str, session_id: str, turn_id: str, *, request_id: str = ""
    ) -> FlowSnapshot:
        """撤销到第 N 轮：物理删除其后轮次，会话回到第 N 轮完成时的状态（2026-11-05）。

        语义（用户裁定）：**保留 1..N、删除 N+1..M**——「回到这一轮结束时的样子」，
        而非「回到这一轮开始前」。历史轮从 append-only 变为「显式撤销可删」（MUST-32 修订）。

        三条已知边界（如实披露，不做静默弥补）：
        - 仅终态（DONE/ABORTED）可撤销：进行中的轮次正在被写，删了会产生半行；
        - L2 project_notes 不回退：项目级长期沉淀、无轮次归属，强删会误删其他会话的记忆；
        - 目标定位不继承：turn 表未存定位结构（summary 只有符号名），下一轮重新检索。
        """
        session = await self._load_owned(user_id, session_id)
        if FlowState(session.state) not in (FlowState.DONE, FlowState.ABORTED):
            raise DevPromptError("会话进行中，暂不能撤销", code=6001)

        record = await self.load_turn(user_id, turn_id)
        if record.session_id != session_id:
            raise DevPromptError("轮次不属于该会话", code=1001)

        deleted = (
            0
            if self._turns is None
            else await self._turns.delete_after(session_id, record.turn_index)
        )

        # 以第 N 轮产出重建会话数据：等同「该轮刚结束、下一轮还没开始」。
        # target 不从 summary 重建（那里只有符号名没有 path）——宁可下轮多一次检索。
        facts = tuple(FactResult(**item) for item in record.facts if isinstance(item, dict))
        variants = tuple(VariantDraft(**item) for item in record.output if isinstance(item, dict))
        memory = TurnMemory(
            sentence=record.input,
            facts=facts,
            variants=variants[:MAX_INHERITED_VARIANTS],
            clarifications=dict(record.clarifications),
        )
        previous_summary = dict(record.summary) if isinstance(record.summary, dict) else {}
        session.data = {
            "sentence": record.input,
            "project_root": str(session.data.get("project_root", "")),
            "turn_index": record.turn_index,
            "turn_memory": memory.to_payload(),
            # turn_anchor 是跨轮追加演进的派生数据，不随撤销回退（被删轮次的 scope 残留）。
            "turn_anchor": session.data.get("turn_anchor"),
            "preferred_level": str(previous_summary.get("decision", "")),
            "prev_facts_complete": previous_summary.get("facts_complete"),
            "cost_tokens": 0,
            "cost_llm_tokens": 0,
            "rounds": 0,
        }
        if memory.variants:
            session.data["variants"] = [v.model_dump() for v in memory.variants]
        if memory.facts:
            session.data["facts"] = [
                {"key": f.key, "passed": f.passed, "evidence": f.evidence} for f in memory.facts
            ]
        await self._sessions.save(session)
        emit(
            "session.rolled_back",
            session_id=session_id,
            kept_turns=record.turn_index + 1,
            deleted_turns=deleted,
            request_id=request_id,
        )
        return self._snapshot(session, "done")

    def _remember_turn(self, session: FlowSession) -> None:
        """把本轮可继承状态写入 ``session.data["turn_memory"]``（下一轮的起点）。

        只带方案正文、取证结论与代码指纹；不带原句以外的过程数据（步骤、候选、成本）。
        """
        facts: list[FactResult] = []
        for item in session.data.get("facts", []):
            if isinstance(item, dict):
                try:
                    facts.append(FactResult(**item))
                except TypeError:
                    continue
        variants: list[VariantDraft] = []
        for item in session.data.get("variants", []):
            if isinstance(item, dict):
                try:
                    variants.append(VariantDraft(**item))
                except (TypeError, ValueError):
                    continue
        target_data = session.data.get("target")
        memory = TurnMemory(
            sentence=str(session.data.get("sentence", "")),
            facts=tuple(facts),
            facts_mtime_digest=str(session.data.get("facts_mtime_digest", "")),
            variants=tuple(variants),
            clarifications=dict(session.data.get("clarifications", {})),
            target=dict(target_data) if isinstance(target_data, dict) else None,
        )
        session.data["turn_memory"] = memory.to_payload()

    async def _finish_turn(self, session: FlowSession) -> None:
        """回填本轮产出（DONE / ASK 各一次）；失败只警告，不阻断流程。"""
        # 继承状态必须先落库：它在 session.data 里，不 save 就只活在内存
        self._remember_turn(session)
        try:
            if not await self._sessions.save(session):
                logger.warning("turn.memory_conflict", extra={"session_id": session.session_id})
        except Exception:  # noqa: BLE001 - 继承状态落库失败不阻断本轮收尾
            logger.warning("turn.memory_save_failed", exc_info=True)
        if self._turns is None:
            return
        turn_id = str(session.data.get("current_turn_id", ""))
        if not turn_id:
            return
        try:
            # 入账必须在落库前：usage.llm_tokens 取自会话累计器，晚一步就恒为 0。
            self._account_usage(session)
            await self._turns.finish(
                turn_id,
                state=session.state,
                facts=[dict(item) for item in session.data.get("facts", [])],
                clarifications=dict(session.data.get("clarifications", {})),
                output=[dict(item) for item in session.data.get("variants", [])],
                summary=summary_from_turn(session.data),
                usage={"llm_tokens": int(session.data.get("cost_llm_tokens", 0))},
            )
        except Exception:  # noqa: BLE001 - 回填是旁路，读路径仍有 payload 兜底
            logger.warning("turn.finish_failed", exc_info=True)
        if self._notes is not None:
            try:
                await self._notes.record_from_session(
                    str(session.data.get("project_root", "")), session.data
                )
            except Exception:  # noqa: BLE001 - 记忆写入失败不阻断生成
                logger.warning("notes.record_failed", exc_info=True)

    def _emit_completed(self, session: FlowSession, *, variants: int, marked: bool | None) -> None:
        """flow.completed（T6-9）：耗时 = 会话起点至生成收尾（跨反问轮次的真实全程）。"""
        started_at = float(session.data.get("started_at", 0.0))
        elapsed_ms = int((time.time() - started_at) * 1000) if started_at else None
        emit(
            "flow.completed",
            flow_id=session.session_id,
            variants=variants,
            marked=marked,
            elapsed_ms=elapsed_ms,
            request_id=session.data.get("last_request_id", ""),
        )

    async def _rank_and_mark(
        self, session: FlowSession, variants: list[VariantDraft]
    ) -> RankingView | None:
        """F-401~404 RANKING 态编排：score_prompts → 归一化 → 匹配度 → 加权总分 → 判定。

        决策层任何异常（LLM 故障/输出缺档位）→ 诚实降级 ranking=None 不阻断流程
        （宁缺勿假，比崩溃好）；不缓存三套方案正文与决策原始响应（MUST-14）。
        """
        request_id = session.data.get("last_request_id", "")
        try:
            context = str(session.data.get("facts_summary") or _summarize_facts(session))
            scores = await self._decider.score_prompts(
                context, [(v.level, v.body) for v in variants]
            )
            by_level = {s.variant: s for s in scores.scores}
            entries: list[tuple[VariantScore, float]] = []
            details: dict[str, tuple[float, float]] = {}
            for v in variants:
                score = by_level[v.level]
                fit = normalize_fit(score.score)
                # 2026-10-21：偏好记忆移除，总分 = 纯适配度（MUST-27 已同步修订）
                total = weighted_total(fit)
                entries.append((score, total))
                details[v.level] = (fit, total)
            rec = decide_mark(entries)
        except Exception:
            emit_error(
                "recommendation.skipped",
                reason="score-failed",
                gap=None,
                confidence=None,
                request_id=request_id,
            )
            return None
        top_fit, top_total = details[rec.variant]
        # 逐档明细（2026-11-05）：回答「为什么没选 C」需要各档实际分数，
        # 而 RankingView 只装得下被选中的那一档。
        session.data["ranking_details"] = {
            level: {"fit": fit, "total": total} for level, (fit, total) in details.items()
        }
        emit(
            "recommendation.made" if rec.marked else "recommendation.skipped",
            gap=rec.gap,
            confidence=rec.confidence,
            marked=rec.marked,
            variant=rec.variant,
            reason=rec.reason,
            request_id=request_id,
        )
        return RankingView(
            variant=rec.variant,
            gap=rec.gap,
            confidence=rec.confidence,
            marked=rec.marked,
            reason=rec.reason,
            fit=top_fit,
            total=top_total,
        )

    async def _rank_top(self, session: FlowSession, candidates: list[Candidate]) -> Candidate:
        """RETRIEVING 段组件排序（MUST-09 顺序：候选 ≤25 已压好，此处只排序取 top1）。

        命中缓存（同项目+同原句+同阈值配置）则不调决策层；失败/空序降级回
        candidates[0]（排序失败不阻断检索主链）；失败结果不缓存（避免 30 分钟固化降级）。
        """
        sentence = str(session.data["sentence"])
        project_root = str(session.data["project_root"])
        request_id = session.data.get("last_request_id", "")
        key = (
            project_root,
            sha256_hex(sentence),
            _threshold_hash(self._cfg),
            _candidates_hash(candidates),
        )
        now = time.monotonic()
        cached = _RANK_CACHE.get(key)
        if cached is not None:
            expires_at, order = cached
            if now <= expires_at and order and order[0] < len(candidates):
                emit("cache.hit", request_id=request_id, candidates=len(candidates))
                return candidates[order[0]]
            _RANK_CACHE.pop(key, None)  # 过期惰性淘汰（SHOULD-04）
        emit("cache.miss", request_id=request_id, candidates=len(candidates))
        try:
            out = await self._decider.rank_components(sentence, candidates)
        except Exception:
            logger.exception(
                "ranking.rank_failed",
                extra={"reason": "decider-failed", "request_id": request_id},
            )
            return candidates[0]
        _RANK_CACHE[key] = (now + _RANK_CACHE_TTL_SECONDS, list(out.order))
        if out.order and out.order[0] < len(candidates):
            return candidates[out.order[0]]
        return candidates[0]

    def _account_usage(self, session: FlowSession) -> None:
        """F-805：把本请求内已发生的外部模型调用用量并入会话（取用后累计器清零）。

        在快照组装时调用：此刻本请求的全部 LLM 调用均已完成，一次取用即全量入账；
        只读路径（resume）无新调用，累计器为零，不产生副作用。
        """
        llm_tokens = take_llm_tokens()
        if llm_tokens:
            session.data["cost_llm_tokens"] = (
                int(session.data.get("cost_llm_tokens", 0)) + llm_tokens
            )

    def _snapshot(self, session: FlowSession, status: SnapshotStatus) -> FlowSnapshot:
        self._account_usage(session)
        llm_tokens = int(session.data.get("cost_llm_tokens", 0))
        cost = CostBreakdown(
            llm_tokens=llm_tokens,
            total_tokens=llm_tokens,
            llm_source="actual" if llm_tokens > 0 else "no_call",
        )
        questions = [_unknown_from(raw) for raw in session.data.get("unknowns", [])]
        ranking_data = session.data.get("ranking")
        target_data = session.data.get("target")
        target = (
            Symbol(
                name=str(target_data["name"]),
                path=str(target_data["path"]),
                line=int(target_data.get("line", 0)),
                kind="function",
            )
            if isinstance(target_data, dict)
            else None
        )
        facts = [FactResult(**f) for f in session.data.get("facts", [])]
        turn_id = session.data.get("current_turn_id")
        agent_steps = session.data.get("agent_steps") or []
        last_step = agent_steps[-1] if agent_steps else None
        started_at = float(session.data.get("started_at", 0.0))
        return FlowSnapshot(
            session_id=session.session_id,
            status=status,
            state=session.state,
            questions=questions,
            cleared=sorted(session.data.get("clarifications", {}).keys()),
            variants=[VariantDraft(**v) for v in session.data.get("variants", [])],
            ranking=(
                RankingView(**{k: v for k, v in ranking_data.items() if k in _RANKING_KEYS})
                if isinstance(ranking_data, dict)
                else None
            ),
            target=target,
            facts=facts,
            cost=cost,
            current_turn_id=str(turn_id) if turn_id else None,
            agent_step=len(agent_steps) if agent_steps else None,
            agent_action=str(last_step.get("action")) if isinstance(last_step, dict) else None,
            agent_elapsed_ms=(
                int((time.time() - started_at) * 1000)
                if started_at and status == "running"
                else None
            ),
            evidence_stale=bool(session.data.get("evidence_stale")),
            reply_text=str(session.data.get("reply_text", "")),
            delivery_gate=_gate_view(session.data.get("delivery_gate")),
        )

    async def _load_owned(self, user_id: str, session_id: str) -> FlowSession:
        """归属校验（不限定状态，区别于 _require）：不存在/非本人抛 6003。"""
        session = await self._sessions.load(session_id)
        if session is None or session.user_id != user_id:
            raise StateError("流程 ID 不存在", code=6003, context={"session_id": session_id})
        return session

    async def _require(self, user_id: str, session_id: str, allowed: set[FlowState]) -> FlowSession:
        session = await self._sessions.load(session_id)
        if session is None or session.user_id != user_id:
            # M-3：会话不存在属**显式操作**失败（用户点了侧栏条目），必须 4xx 且文案可操作——
            # 不能降级为空快照，否则前端会误判为「会话无内容」而非「会话已失效」。
            raise StateError(
                "会话不存在或已过期，请从历史列表重新选择",
                code=6003,
                context={"session_id": session_id},
            )
        if FlowState(session.state) not in allowed:
            raise StateError(
                f"当前状态 {session.state} 不允许该操作",
                code=6001,
                context={"session_id": session_id, "state": session.state},
            )
        return session


def _summarize_facts(session: FlowSession) -> str:
    """兜底路径：hook 未跑（旧测试桩 / 跳过）时现算，逻辑与 after_retrieval hook 共用。"""
    return summarize_facts(session.data)


def _candidates_hash(candidates: Sequence[Candidate]) -> str:
    """候选集摘要（MUST-14 第四段键）：代码改动导致候选变化时旧排序必须失效。

    候选已被 MUST-09 压到 ≤25 条，O(n) 无性能成本；只用名称+路径，不含代码正文。
    """
    payload = "\n".join(f"{c.name}@{c.path}" for c in candidates)
    return sha256_hex(payload)[:16]


def _threshold_hash(cfg: AppConfig) -> str:
    """MUST-14 缓存键影响因子：排序/推荐阈值配置的 json 序列化 sha256。

    阈值调整 → hash 变化 → 缓存失效，杜绝读到旧阈值下的排序结果；
    仅摘要入键，不落原句明文（MUST-14 禁缓存项）。
    """
    payload = json.dumps(
        {
            "prefer_hard_threshold": cfg.prefer_hard_threshold,
            "prefer_soft_threshold": cfg.prefer_soft_threshold,
            "prefer_min_confidence": cfg.prefer_min_confidence,
            "prefer_low_confidence": cfg.prefer_low_confidence,
        },
        sort_keys=True,
    )
    return sha256_hex(payload)


async def build_default(cfg: AppConfig) -> ForgeService:
    """默认组装（CLI/开发态；Web 复用同一函数，MUST-10）。"""
    from devprompt_ai.decision.fallback import create_decider
    from devprompt_ai.harness.models_client import OpenAIModelsFetcher
    from devprompt_ai.memory.project_note_store import SQLiteProjectNoteStore
    from devprompt_ai.memory.session_store import SQLiteSessionStore
    from devprompt_ai.memory.startup_safety_check import run_startup_safety_check
    from devprompt_ai.memory.turn_store import SQLiteTurnStore

    # N-1 启动自愈：必须在任何 Manager 打开库之前跑，坏行隔离才有意义
    run_startup_safety_check(cfg.db_path)

    sessions = SQLiteSessionStore(cfg.db_path)
    await sessions.init_schema()
    return ForgeService(
        cfg=cfg,
        decider=create_decider(cfg),
        sessions=sessions,
        runner=LocalCommandRunner(),
        reader=LocalFileReader(),
        generator=LLMGenerator(cfg),
        symbols_provider=SymbolTableProvider(LocalCommandRunner()),
        catalog_fetcher=OpenAIModelsFetcher(),
        turns=SQLiteTurnStore(cfg.db_path),
        notes=SQLiteProjectNoteStore(cfg.db_path),
    )
