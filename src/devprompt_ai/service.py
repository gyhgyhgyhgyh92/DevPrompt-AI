"""F-001 统一业务入口（双形态唯一，MUST-07/10）。业务判定只在此层与 domain/。"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import difflib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import ValidationError

if TYPE_CHECKING:
    from devprompt_ai.domain.agent.work_order import WorkOrder
    from devprompt_ai.memory.token_ledger import SQLiteTokenLedger

from devprompt_ai.common.cost import take_llm_usage
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
from devprompt_ai.domain.agent.finish_gates import FinishDecision, GateInput, evaluate_finish
from devprompt_ai.domain.agent.memory import MAX_INHERITED_VARIANTS, TurnMemory
from devprompt_ai.domain.agent.phase_convergence import PhaseClass, evaluate_phase
from devprompt_ai.domain.agent.ports import ActionPlanner
from devprompt_ai.domain.agent.sensorium import (
    SensoriumInput,
    compute_sensorium,
    derive_strategy,
)
from devprompt_ai.domain.agent.stop_reason import StopReason, snapshot_stop_reason
from devprompt_ai.domain.context import (
    ContextBudget,
    ContextPayload,
    TurnInput,
    TurnSummary,
    build_context,
    summary_from_turn,
)
from devprompt_ai.domain.context.build_context import compose_history
from devprompt_ai.domain.context.compact_policy import CacheKind
from devprompt_ai.domain.context.compactor import plan_compaction
from devprompt_ai.domain.context.prompt_layers import assert_append_only, render_delta
from devprompt_ai.domain.context.task_contract import (
    ContractStatus,
    TaskContract,
    render_tail_anchor,
)
from devprompt_ai.domain.context.tokens import estimate_tokens as estimate_ctx_tokens
from devprompt_ai.domain.decision.followup import (
    GuardrailState,
    UnknownItem,
    UnknownOption,
    answered_headers,
    build_unknowns,
    lint_questions,
)
from devprompt_ai.domain.decision.port import DecisionPort, FactProbeOutput
from devprompt_ai.domain.delivery import DeliveryInput, DeliveryVerdict, evaluate_delivery
from devprompt_ai.domain.delivery.attribution import Attribution
from devprompt_ai.domain.delivery.structural import check_structural
from devprompt_ai.domain.domains import (
    KNOWN_DOMAIN_IDS,
    DomainId,
    DomainPack,
    DomainVerdict,
    get_pack,
)
from devprompt_ai.domain.domains.rules import match_by_keyword
from devprompt_ai.domain.errors import (
    CatalogFetchError,
    ConfigurationError,
    DevPromptError,
    GenerationError,
    StateError,
)
from devprompt_ai.domain.generate.anchors import Anchor, extract_anchors, verify_anchors
from devprompt_ai.domain.generate.claims import CLAIM_COVERAGE_MIN
from devprompt_ai.domain.generate.ports import (
    GeneratePort,
    GenerationContext,
    VariantDraft,
)
from devprompt_ai.domain.hooks.builtin import DetectorHook, FactsSummaryHook, summarize_facts
from devprompt_ai.domain.hooks.pipeline import HookPipeline
from devprompt_ai.domain.hooks.types import HookContext
from devprompt_ai.domain.model.tuning import resolve_effort
from devprompt_ai.domain.model_catalog import (
    ModelCatalogFetcher,
    ModelCatalogItem,
    effective_context_window,
    mark_stale_models,
    merge_catalog,
    static_catalog,
)
from devprompt_ai.domain.model_spec import (
    model_meta_of,
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
from devprompt_ai.domain.obs.contract.trace import to_plain
from devprompt_ai.domain.progress import (
    ProgressEvent,
    ProgressSink,
    answering_text,
    candidates_text,
    clarification_text,
    facts_text,
    generation_text,
    manual_required_text,
    retrieval_text,
    symbols_text,
    target_text,
)
from devprompt_ai.domain.retrieval.candidates import (
    MAX_CANDIDATES,
    build_candidates,
    reorder_by_lexicon,
)
from devprompt_ai.domain.retrieval.facts import (
    is_evidence_complete,
    is_probe_complete,
    verify_facts,
)
from devprompt_ai.domain.retrieval.locate import locate_symbol
from devprompt_ai.domain.retrieval.paths import safe_join
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader, SymbolProvider
from devprompt_ai.harness.guardrails import validate_claims
from devprompt_ai.harness.llm import LLMGenerator, reset_generation_sink, set_generation_sink
from devprompt_ai.harness.overflow import is_context_overflow
from devprompt_ai.harness.process import LocalCommandRunner, LocalFileReader, SymbolTableProvider
from devprompt_ai.harness.repo_indexer import impact_for, index_project
from devprompt_ai.harness.summarize import summarize_history
from devprompt_ai.harness.trace import TracingReader, TracingRunner
from devprompt_ai.memory.model_catalog_store import read_model_catalog, write_model_catalog
from devprompt_ai.memory.project_note_store import normalize_key
from devprompt_ai.memory.repo_index import SQLiteRepoIndex
from devprompt_ai.memory.settings_store import (
    read_model_registry,
    write_model_registry,
    write_model_settings,
    write_process_settings,
)
from devprompt_ai.memory.turn_store import TurnConflictError
from devprompt_ai.observability.logging import emit, emit_error, emit_warning, set_telemetry
from devprompt_ai.runtime.coordinator import DelegationCoordinator
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
    text = "\n\n".join(f"{v.title}\n{v.body}" for v in variants)
    if len(text) <= PREVIOUS_VARIANTS_LIMIT:
        return text
    return text[: PREVIOUS_VARIANTS_LIMIT - 1] + "…"


_RANK_CACHE_TTL_SECONDS: float = 30.0 * 60.0
"""组件排序缓存 TTL（MUST-14：决策结果 30 分钟；SHOULD-04 惰性淘汰）。"""

_RANK_CACHE: dict[tuple[str, str, str, str], tuple[float, list[int]]] = {}
"""rank_components 结果缓存（模块级，MUST-14）。

键 = (项目绝对路径, 原句 sha256, 阈值配置 hash, 候选集摘要)——键不含原句明文。
第四段是 2026-11-04 补的：此前只有前三段，代码改动导致候选集变化后 30 分钟内
仍会命中旧 order，唯一保护是越界检查（只防越界，防不了错位）。
值 = (过期时刻 monotonic, 候选索引顺序)。禁存原句与决策原始响应。
"""


def reset_run_cache() -> None:
    """清空进程内决策缓存（Replay 必须从干净状态执行）。

    回放断言的是「同一输入产生同一条执行链」；若命中运行期缓存，决策调用会被
    跳过、节点流与录制不一致（2026-11-12 集成测试实测）。清空只造成一次缓存
    未命中，不影响任何业务语义。
    """
    _RANK_CACHE.clear()


_OBS_SETTING_KEYS: dict[str, str] = {
    "trace_enabled": "obs_trace_enabled",
    "trace_retention_days": "obs_trace_retention_days",
    "metrics_enabled": "obs_metrics_enabled",
    "replay_enabled": "obs_replay_enabled",
}
"""PUT /settings observability 段键 → AppConfig 字段（持久化键直接用字段名）。

2026-11-12：三模块各自独立启停。持久化进 app_settings 表（与流程段同表），
由 config 的本地设置源在重启后读回；运行期则同步到 ``ObsModules`` 即时生效。
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
    disclosure: str = ""


@dataclass(slots=True)
class FlowSnapshot:
    """表现层快照：CLI/Web 只渲染它（MUST-10）。"""

    session_id: str
    status: SnapshotStatus
    state: str
    questions: list[UnknownItem] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)
    #: 唯一方案（2026-11-11 单套输出）：未生成为 None。
    variant: VariantDraft | None = None
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
    #: 领域路由结论（2026-11-14 领域包）：{domain, source, confidence}，旧会话为 None
    domain: dict[str, Any] | None = None
    """本轮归属（2026-11-04）：前端据此决定该轮进历史列表还是当前对话区。

    此前前端用「轮次列表末位」推断当前轮，导致新一轮提交瞬间把上一轮从历史里过滤掉
    （现象：第二轮开始时第一轮正文消失）。归属改由服务端给出，构造见 ``_begin_turn``。
    """


# 方向分歧检测已抽到 domain/decision/direction.py（2026-11-07）：纯函数 + 可测词表。


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
        disclosure=str(raw.get("disclosure", "")),
    )


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
        symbols_provider: SymbolProvider,
        catalog_fetcher: ModelCatalogFetcher | None = None,
        symbols_override: list[Symbol] | None = None,
        turns: TurnStore | None = None,
        notes: ProjectNoteStore | None = None,
        token_ledger: SQLiteTokenLedger | None = None,
        trace: Any | None = None,
    ) -> None:
        self._cfg = cfg
        self._decider = decider
        #: Trace 采集器（2026-11-12）：默认空实现，测试/关闭模块零改动
        if trace is None:
            from devprompt_ai.harness.obs.trace_collector import NullTraceCollector

            trace = NullTraceCollector()
        self._trace = trace
        #: 可观测性模块集合（trace/metrics/replay services），由 build_default 注入
        self.obs: Any = None
        # 运行时层组装存储时需要 db_path 等配置；暴露只读属性，避免跨层摸私有字段。
        # （属性定义在类体末尾，见 `config`。）
        self._sessions = sessions
        #: 多轮 turn 存储；None 时跳过双写（旧测试零改动）
        self._turns = turns
        #: L2 项目记忆；None 时不注入也不记录
        self._notes = notes
        #: H5 token 账本；None 时不落账（旧测试零改动）
        self._token_ledger = token_ledger
        #: 阶段7 周期 checkpoint 出口：runtime 装配时注入（写 run_events），None 时跳过
        self.checkpoint_sink: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
        #: 阶段9 委派调度：分池信号量 + 文件占位 + 去重（服务级实例，跨会话共享容量）
        self._coordinator = DelegationCoordinator()
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
            [FactsSummaryHook(), DetectorHook()],
            on_result=lambda run: emit(
                "hook.ran",
                hook=run.name,
                outcome=run.outcome,
                duration_ms=run.duration_ms,
            ),
        )
        #: 领域分类器（2026-11-14 领域包）：确定性词表未命中时的一次 LLM 分类。
        #: 函数内 import：保持模块导入轻量（与上方 trace 同款惯例）。
        from devprompt_ai.decision.domains import DomainClassifier

        self._domain_classifier = DomainClassifier(cfg)

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
        governance = self._cfg.tool_output_governance
        return (
            TracingRunner(self._runner, progress, root, phase, governance=governance),
            TracingReader(self._reader, progress, root, phase, governance=governance),
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
        create_session: bool = False,
        domain_override: str | None = None,
        style: str | None = None,
        images: list[str] | None = None,
    ) -> FlowSnapshot:
        """F-001：创建/恢复会话，执行阶段一至二（检索+探针），路由 ask/done。

        ``progress`` 为可选的思考过程出口（流式端点传入）；缺省 None 时旧调用方零改动。
        ``session_id`` 非空表示**在同一会话开启新一轮**（多轮，2026-10-20）。
        ``base_turn_id`` 非空表示**以某一历史轮为基线**新开一轮（2026-11-05）。
        ``create_session`` 仅 /runs 使用：按前端预生成的 session_id 建容器（D-04）。
        ``domain_override`` 非空表示用户显式指定领域（2026-11-14 领域包）。
        ``style``/``images`` 仅 visual 域消费（2026-11-14 多模态）：None=沿用上一轮值。
        """
        session = await start_turn(
            self._sessions, user_id, session_id, create_missing=create_session
        )
        try:
            # 多轮：本轮可以只给原句，项目路径沿用它所在会话的既有值
            project_root = project_root or str(session.data.get("project_root", ""))
            # 上一轮的结论与完备度（决定本轮给几套；data 随后会被整体重置）
            previous_summary: dict[str, Any] = {}
            if self._turns is not None:
                records = await self._turns.list_for_session(session.session_id)
                if records and isinstance(records[-1].summary, dict):
                    previous_summary = records[-1].summary
            # 轮次序号跨轮累积（session.data 会被重建，故先取出再写回）
            previous_index = int(session.data.get("turn_index", -1))
            # 档位变化观测：data 每轮重建，先带走上一轮窗口/预算再写回（2026-11-10）
            previous_context_window = int(session.data.get("context_window", 0) or 0)
            previous_state_budget = int(session.data.get("state_budget", 0) or 0)
            current_context_window = self._cfg.runtime_window()
            current_state_budget = self._cfg.runtime_state_budget()
            # 多轮继承（2026-11-04）：不再整体丢弃，方案正文/澄清/取证经 TurnMemory 带入。
            # 原句为空时沿用上一轮目标——这就是「不带新原句的追问」入口。
            inherited = TurnMemory.from_payload(session.data.get("turn_memory"))
            # 上一轮原句必须在 inherit_for_next_turn 之前取出：该函数会把 sentence
            # 换成本轮原句（原句为空才沿用上一轮），之后就拿不到上一轮内容了。
            # 锚点选取依赖它区分「这个按钮」与「编辑按钮」两类指代（2026-11-12）。
            previous_sentence = inherited.sentence
            memory = inherited.inherit_for_next_turn(sentence)
            if base_turn_id:
                memory = await self._inherit_from_base_turn(user_id, memory, base_turn_id)
            if not memory.sentence:
                raise DevPromptError("原句不能为空（当前会话也没有可沿用的目标）", code=1001)
            # 领域路由（2026-11-14）：继承值在 data 重建前取出；带项目路径强制 code 包，
            # 通用包允许空路径——2001 由「包是否依赖仓库」决定而非一律拒绝。
            verdict = await self._route_domain(
                project_root, memory.sentence, session.data.get("domain"), domain_override
            )
            if get_pack(verdict.domain).needs_repo and not project_root:
                raise DevPromptError(tr("domain.code.repo_required", locale), code=2001)
            # 目标锚点（2026-11-05）：已有则追加合并（不重写 objective），无则按本轮原句新建。
            # 旧会话没有这个键，等价于「没有可继承的锚点」，不影响既有流程。
            next_index = previous_index + 1
            previous_anchor = anchor_from_payload(session.data.get("turn_anchor"))
            # B1–B4 增量基线：data 每轮重建，跨轮对比必须显式带走上一轮的层快照
            previous_layers = session.data.get("prompt_layers")
            # MUST-11c 检测面：历史前缀比对基线同样要跨轮携带
            previous_turn_indexes = session.data.get("context_turn_indexes")
            anchor = (
                extract_anchor(memory.sentence, next_index)
                if previous_anchor is None
                else merge_followup(previous_anchor, memory.sentence, turn_index=next_index)
            )
            session.data = {
                "sentence": memory.sentence,
                "project_root": project_root,
                "domain": verdict.model_dump(),
                # 多模态（2026-11-14）：风格与参考图随请求传入，追问轮沿用上一轮值
                "style": (
                    style if style is not None else str(session.data.get("style", ""))
                ),
                "images": (
                    list(images)
                    if images is not None
                    else [str(x) for x in session.data.get("images") or []]
                ),
                "last_request_id": request_id,
                # 会话语言（2026-11-06）：由 Accept-Language 解析后随会话保留，历史轮沿用。
                "locale": locale,
                "clarifications": dict(memory.clarifications),
                "rounds": 0,
                "cost_tokens": 0,  # 总 token（护栏判定用，MUST-26 成本预算）
                "cost_llm_tokens": 0,  # F-805：LLM 实际用量
                "started_at": time.time(),  # flow.completed 耗时基准（T6-9）
                "turn_index": previous_index,
                "context_window": current_context_window,
                "state_budget": current_state_budget,
                "prev_facts_complete": previous_summary.get("facts_complete"),
                "turn_memory": memory.to_payload(),
                "turn_anchor": anchor_to_payload(anchor),
                "prompt_layers": previous_layers if isinstance(previous_layers, dict) else {},
                "context_turn_indexes": (
                    previous_turn_indexes if isinstance(previous_turn_indexes, list) else []
                ),
            }
            # 领域披露（2026-11-14）：通用域在时间线报「已识别领域」；兜底路由额外披露
            if verdict.domain != "code":
                pack = get_pack(verdict.domain)
                await _notify(
                    session,
                    progress,
                    tr("domain.detected", locale, name=tr(pack.name_key, locale)),
                )
                if verdict.source == "fallback":
                    await _notify(session, progress, tr("domain.fallback_notice", locale))
            # 继承的方案与取证直接进本轮 data：agentic 循环据此判断能否跳过检索
            if previous_context_window and previous_context_window != current_context_window:
                emit(
                    "context.tier_changed",
                    from_window=previous_context_window,
                    to_window=current_context_window,
                    from_state_budget=previous_state_budget,
                    to_state_budget=current_state_budget,
                    request_id=request_id,
                )
            if memory.variants:
                # 单套输出（2026-11-11）：继承最近一套作为上一轮方案起点。
                session.data["variant"] = memory.variants[-1].model_dump()
            if memory.facts:
                session.data["facts"] = [
                    {"key": f.key, "passed": f.passed, "evidence": f.evidence} for f in memory.facts
                ]
                session.data["facts_mtime_digest"] = memory.facts_mtime_digest
            if memory.target is not None:
                session.data["target"] = dict(memory.target)
                # 2026-11-11：继承 target 时必须一并刷新「代码片段 + 设计令牌」。
                # 本轮若跳过检索（取证未变时调度层会直接 generate），生成层拿不到这两路
                # 证据，只能写「未取证到代码片段」，定位段与一致性检查段整段空转。
                # 2026-11-12：本轮句与上一轮句分开传，由 locate 内部决定是否合并
                # （本轮只命中泛化词时改用上一轮上下文，避免锚到无关按钮）。
                await self._refresh_inherited_evidence(
                    session,
                    project_root,
                    sentence=memory.sentence,
                    previous_sentence=previous_sentence,
                    progress=progress,
                )
            await self._begin_turn(session)
            await self._start_trace(session, request_id)
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
        finally:
            await self._end_trace(session)

    async def _route_domain(
        self,
        project_root: str,
        sentence: str,
        previous: Any,
        override: str | None,
    ) -> DomainVerdict:
        """两级领域路由：override > project > keyword > 会话继承 > LLM > 兜底。

        确定性手段先行（零 LLM 成本，MUST-04）；继承优先级低于词表——同一会话的
        连续性让位给本轮的显式领域词。LLM 分类失败回退兜底包，不阻塞主链。
        """
        if override:
            if override not in KNOWN_DOMAIN_IDS:
                raise DevPromptError(f"未知领域：{override}", code=1002)
            return DomainVerdict(domain=cast(DomainId, override), source="override", confidence=1.0)
        if project_root:
            return DomainVerdict(domain="code", source="project", confidence=1.0)
        hit = match_by_keyword(sentence)
        if hit is not None:
            return DomainVerdict(domain=hit[0], source="keyword", confidence=hit[1])
        if isinstance(previous, dict):
            try:
                inherited = DomainVerdict.model_validate(previous)
            except ValidationError:
                emit_warning("domain.inherit_invalid")
                inherited = None
            if inherited is not None:
                return inherited
        return await self._domain_classifier.classify(sentence)

    @staticmethod
    def _domain_id(session: FlowSession) -> str:
        """本轮领域 id；旧会话无 domain 键时视为 code（零回归）。"""
        data = session.data.get("domain")
        return str(data.get("domain", "code")) if isinstance(data, dict) else "code"

    def _domain_pack(self, session: FlowSession) -> DomainPack:
        """本轮领域包（动作白名单/断言 kinds 的来源）。"""
        return get_pack(self._domain_id(session))

    async def _start_trace(self, session: FlowSession, request_id: str) -> None:
        """开启本轮 Trace（每次请求一个 segment；同一 turn 的追问是独立 segment）。"""
        target = session.data.get("target")
        await self._trace.start_turn(
            session_id=session.session_id,
            turn_id=str(session.data.get("current_turn_id", "") or "turn"),
            turn_index=int(session.data.get("turn_index", 0) or 0),
            sentence=str(session.data.get("sentence", "")),
            project_root=str(session.data.get("project_root", "")),
            inherited_target=str(target.get("path", "")) if isinstance(target, dict) else "",
            clarifications=dict(session.data.get("clarifications", {})),
            run_id=request_id,
            request_id=request_id,
            session_data=dict(session.data),
        )

    async def _end_trace(self, session: FlowSession) -> None:
        """结束 Trace；快照与状态全量落库，失败不影响业务。"""
        try:
            snapshot = to_plain(
                self._snapshot(session, "done" if session.state == FlowState.DONE.value else "ask")
            )
        except Exception:  # noqa: BLE001 - 快照构造失败时仍以空快照收尾
            snapshot = {}
        status = "failed" if session.state == FlowState.ABORTED.value else "ok"
        try:
            await self._trace.end_turn(state=session.state, status=status, snapshot=snapshot)
        except Exception:  # noqa: BLE001 - 观测失败不阻断业务
            logger.warning("trace.end_failed", exc_info=True)

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
        await self._start_trace(session, request_id)
        try:
            session.data.setdefault("clarifications", {}).update(answers)
            session.data["last_request_id"] = request_id
            session.data["rounds"] = int(session.data.get("rounds", 0)) + 1
            await hop(session, FlowState.CONFIRMING, self._sessions)
            return await self._reprobe(session, progress=progress)
        except Exception:
            await self._abort_quietly(session)
            raise
        finally:
            await self._end_trace(session)

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
        # I1–I3：对 ≤25 条候选做 BM25+RRF+路径权重二次排序（只调序不减候选，MUST-09）
        result = dataclasses.replace(
            result, candidates=reorder_by_lexicon(result.candidates, sentence)
        )
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
        location = await locate_symbol(symbol, runner, reader, root=project_root, sentence=sentence)
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
        # 四段式方案的两路证据（2026-11-11）：目标代码片段与设计令牌。
        # 只走生成层，不进 facts_summary —— 后者同时被研判与打分消费（MUST-09）。
        session.data["target_excerpt"] = location.excerpt
        session.data["design_tokens"] = list(location.token_hits)
        # ⑤ 影响半径：作为取证证据进入本轮 data（失败只记日志，不影响主流程）
        await self._attach_impact(session, project_root=project_root, request_id=request_id)
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
        """固定流水线（无 planner 时的回落路径）：检索 → 研判 → 生成 → 打分 → 交付。

        通用域（2026-11-14 领域包）无仓库可检索，直接生成交付（研判由生成层的
        反问机制承担，与 agentic 路径一致）。
        """
        if self._domain_id(session) != "code":
            return await self._generate_and_finish(session, progress=progress)
        ok = await self._trace_span(
            "retrieve",
            {"sentence": sentence, "project_root": project_root},
            self._act_retrieve(
                session, sentence, project_root, request_id=request_id, progress=progress
            ),
        )
        if not ok:
            return self._snapshot(session, "ask")
        await hop(session, FlowState.PROBING, self._sessions)
        snapshot: FlowSnapshot = await self._trace_span(
            "probe_and_route",
            {"state": session.state},
            self._probe_and_route(session, request_id=request_id, progress=progress),
        )
        return snapshot

    async def _trace_span(self, name: str, input_data: dict[str, Any], call: Any) -> Any:
        """包裹一次线性流水线动作，保证非 agentic 路径也有 action.start/end。"""
        started = time.monotonic()
        event_id = await self._trace.record("action.start", name, input=input_data)
        self._trace.set_action_parent(event_id)
        try:
            result = await call
        except Exception as exc:
            await self._trace.record(
                "action.end",
                name,
                output={},
                status="failed",
                error={"type": type(exc).__name__, "message": str(exc)},
                attributes={"duration_ms": int((time.monotonic() - started) * 1000)},
                parent_id=event_id,
            )
            raise
        else:
            await self._trace.record(
                "action.end",
                name,
                output={"result": str(result)[:200]},
                attributes={"duration_ms": int((time.monotonic() - started) * 1000)},
                parent_id=event_id,
            )
            return result
        finally:
            self._trace.reset_action_parent()

    async def _refresh_inherited_evidence(
        self,
        session: FlowSession,
        project_root: str,
        *,
        sentence: str,
        previous_sentence: str = "",
        progress: ProgressSink | None = None,
    ) -> None:
        """继承 target 时刷新目标代码片段与设计令牌（2026-11-11）。

        为什么必须在轮次开始时做：取证未变时调度层会直接 generate 而不 retrieve，
        片段与令牌就不会落进 ``session.data``；生成层于是只能写「未取证到代码片段」，
        四段式里的定位段与一致性检查段全部空转（实测 R2/R3 三轮均如此）。

        失败只记日志：这是证据增强项，不得阻断本轮。
        """
        raw = session.data.get("target")
        if not isinstance(raw, dict) or not raw.get("path"):
            return
        # MUST-20：继承来的目标路径先过越界校验，不安全则本轮不做证据刷新。
        if not safe_join(project_root, str(raw["path"])):
            logger.info("evidence.unsafe_target_path", extra={"what": "inherited_target"})
            return
        try:
            runner, reader = self._traced(progress, project_root, lambda: session.state)
            location = await locate_symbol(
                Symbol(
                    name=str(raw.get("name", "")),
                    path=str(raw["path"]),
                    line=int(raw.get("line", 0) or 0),
                    kind="function",
                ),
                runner,
                reader,
                root=project_root,
                sentence=sentence,
                previous_sentence=previous_sentence,
            )
        except Exception:  # noqa: BLE001 - 增强项失败不阻断主流程
            logger.info("evidence.inherited_refresh_failed", extra={"what": "locate"})
            return
        session.data["target_excerpt"] = location.excerpt
        session.data["design_tokens"] = list(location.token_hits)

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

        while True:
            variant_now = session.data.get("variant")
            variants_total = 1 if isinstance(variant_now, dict) else 0
            generated_now = int(session.data.get("generated_variant_count", 0) or 0)
            decision = await planner.next_action(
                sentence=str(session.data.get("sentence", "")),
                facts=[FactResult(**f) for f in session.data.get("facts", [])],
                steps=tuple(steps),
                variant_count=variants_total,
                clarifications=dict(session.data.get("clarifications", {})),
                correction=str(session.data.get("hook_correction", "")),
                # 2026-11-11：区分「本轮已生成」与「只有上一轮继承来的旧方案」。
                # 不区分时调度层会看到「已生成 2 套」而直接 deliver，把第二轮的新指令
                # 整个跳过（实测 R2/R3 正文与 R1 逐字相同、tokens=0）。
                inherited_variant_count=max(0, variants_total - generated_now),
                # 领域包（2026-11-14）：菜单只列本领域允许的动作（通用域无检索类动作）
                allowed_actions=tuple(self._domain_pack(session).allowed_actions),
            )
            action = AgentAction(decision.action)
            # 白名单兜底（2026-11-14）：模型越权选了本领域不允许的动作（或输出非法枚举），
            # 一律降级为 generate 继续推进——通用域没有仓库证据，检索类动作必然空转。
            if action not in self._domain_pack(session).allowed_actions:
                emit_warning(
                    "agent.action_filtered",
                    action=decision.action,
                    domain=self._domain_id(session),
                )
                action = AgentAction.GENERATE
            if action is AgentAction.DELEGATE and decision.delegation_orders:
                # K6 多波来源：决策层草案先落会话，_act_delegate 据此构造工单列表
                session.data["delegation_orders"] = [
                    item.model_dump() for item in decision.delegation_orders
                ][:8]
            started = time.monotonic()
            terminal = await self._execute_action(
                action, session, request_id=request_id, progress=progress
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            steps.append(
                AgentStep(
                    index=len(steps),
                    action=action,
                    outcome=self._step_outcome(action, session),
                    duration_ms=duration_ms,
                    facts_passed=sum(1 for f in session.data.get("facts", []) if f.get("passed")),
                    decided_by_evidence=decision.confidence_source == "measured",
                    note=decision.reason[:120],
                )
            )
            self._persist_steps(session, steps)
            # 阶段7 周期 checkpoint：每 5 步把执行进度落 run_events（进程崩溃可归因到步）。
            if len(steps) % 5 == 0:
                await self._emit_checkpoint(session, steps, action, request_id)
            emit(
                "agent.step",
                action=action.value,
                index=len(steps),
                duration_ms=duration_ms,
                request_id=request_id,
            )
            self._record_sensorium(session, steps, budget, request_id)
            if terminal is not None:
                # 终止原因结构化（A1）：交付/等用户/放弃三种收尾各自可归因。
                session.data["stop_reason"] = snapshot_stop_reason(
                    terminal.status, terminal.state
                ).value
                emit(
                    "agent.loop_terminated",
                    reason=session.data["stop_reason"],
                    request_id=request_id,
                )
                return terminal
            if self._is_wedged(steps):
                # A4：连续同动作且无新事实 → 判原地打转，先于收敛熔断收尾。
                session.data["stop_reason"] = StopReason.WEDGED_LOOP.value
                await self._act_abort(session, reason="wedged_loop")
                return self._snapshot(session, "aborted")
            # 外环监督（2026-11-05）：每完成一步先过 post_tool，再回巢。
            # hook 只能建议，终止由这里决定——领域层不碰状态机（MUST-07）。
            # steps 单独注入：DetectorHook（E9–E10）读的是实时步骤序列，不落会话。
            hook_outcome = await self._hooks.run_phase(
                "post_tool",
                HookContext(
                    phase="post_tool",
                    session_state=session.state,
                    data={**session.data, "steps": tuple(steps)},
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
                session.data["stop_reason"] = StopReason.CONVERGENCE_ABORT.value
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
                session.data["stop_reason"] = StopReason.MAX_TURNS.value
                await self._act_abort(session, reason="budget_exhausted")
                return self._snapshot(session, "aborted")
            # 2026-11-07：收敛改为相位感知（七信号 + 双门槛 + 反向证据），
            # 旧的连续三判据保留在 convergence.py 供单测与降级参考。
            verdict = evaluate_phase(
                steps,
                phase=self._phase_for(steps),
                context_window=int(getattr(self._cfg, "context_window_tokens", 1_000_000)),
                turn=len(steps),
                reasoning_active=bool(steps) and steps[-1].action is AgentAction.REPLY,
            )
            if verdict.should_abort:
                session.data["stop_reason"] = StopReason.CONVERGENCE_ABORT.value
                await self._act_abort(session, reason=verdict.reason)
                return self._snapshot(session, "aborted")
            if verdict.level >= 2:
                await _notify(session, progress, verdict.reason)

    async def _execute_action(
        self,
        action: AgentAction,
        session: FlowSession,
        *,
        request_id: str,
        progress: ProgressSink | None = None,
    ) -> FlowSnapshot | None:
        """执行一个动作并记录 Trace（action.start/end 包裹完整输入输出）。"""
        started = time.monotonic()
        event_id = await self._trace.record(
            "action.start",
            action.value,
            input={
                "action": action.value,
                "state": session.state,
                "target": session.data.get("target"),
                "facts_passed": sum(
                    1 for item in session.data.get("facts", []) if item.get("passed") is True
                ),
                "turn_index": session.data.get("turn_index"),
            },
        )
        self._trace.set_action_parent(event_id)
        try:
            snapshot = await self._execute_action_inner(
                action, session, request_id=request_id, progress=progress
            )
        except Exception as exc:
            await self._trace.record(
                "action.end",
                action.value,
                output={"state": session.state, "status": "raised"},
                status="failed",
                error={"type": type(exc).__name__, "message": str(exc)},
                attributes={"duration_ms": int((time.monotonic() - started) * 1000)},
                parent_id=event_id,
            )
            raise
        else:
            await self._trace.record(
                "action.end",
                action.value,
                output={
                    "state": session.state,
                    "status": snapshot.status if snapshot is not None else "continue",
                    "target": session.data.get("target"),
                    "facts_passed": sum(
                        1 for item in session.data.get("facts", []) if item.get("passed") is True
                    ),
                },
                attributes={"duration_ms": int((time.monotonic() - started) * 1000)},
                parent_id=event_id,
            )
            return snapshot
        finally:
            self._trace.reset_action_parent()

    async def _execute_action_inner(
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
            if has_unknowns:
                # 研判出未决项就必然反问（2026-11-15）：此前只有 planner 主动选 ask 才进
                # ASKING，实测出现过「有 2 条缺口却直接生成、清单静态写进方案」的路径。
                await hop(session, FlowState.ASKING, self._sessions)
                await self._finish_turn(session)
                return self._snapshot(session, "ask")
            return None  # 无未决项：交给下一轮调度决定继续取证还是生成

        if action is AgentAction.GENERATE:
            # agentic 允许跳过 RETRIEVING/PROBE 直接生成：先查证据新鲜度（改了代码
            # 仍用旧证据会产出错误行号），再补研判（档位/追问/推荐全依赖它）。
            await self._check_evidence_freshness(session, request_id=request_id, stage="generate")
            if "facts_complete" not in session.data:
                await self._act_probe(session, request_id=request_id, progress=progress)
            await self._act_generate(session, progress=progress)
            return None

        if action is AgentAction.REPLY:
            # 回答里也可能引用行号，过期同样要披露
            await self._check_evidence_freshness(session, request_id=request_id, stage="reply")
            return await self._act_reply(session, progress=progress)

        if action is AgentAction.DELEGATE:
            await self._act_delegate(session, progress=progress)
            return None

        if action is AgentAction.DELIVER:
            await self._check_evidence_freshness(session, request_id=request_id, stage="deliver")
            # A2 六道闸（本产品可判定的两道）：有纠偏未消化或没有产出时，自然收尾先弹回一次。
            # 通知后回到循环——纠偏会被下一轮决策消费，弹回有界（不改变状态机，MUST-07）。
            gate = self._evaluate_finish_gate(session)
            if not gate.allowed:
                emit(
                    "agent.finish_gate_blocked",
                    gate=gate.blocked_by.value if gate.blocked_by is not None else "",
                    reason=gate.detail,
                    request_id=request_id,
                )
                await _notify(session, progress, gate.detail)
                return None
            return await self._act_deliver(session, progress=progress)

        await self._act_abort(session, reason="模型放弃本轮")
        return self._snapshot(session, "aborted")

    async def _act_delegate(
        self, session: FlowSession, *, progress: ProgressSink | None = None
    ) -> None:
        """只读委派（2026-11-08）：把「汇总当前取证」交给独立上下文的 worker。

        当前 execute 是确定性的（不调 LLM）：先把 worker 契约、超时与打捞跑通；
        接真实子 agent 时只替换 execute，调度与结果结构不变。
        """
        import json as _json

        from devprompt_ai.domain.agent.work_order import WorkOrder
        from devprompt_ai.harness.worker_session import run_read_worker

        target = session.data.get("target") or {}
        path = str(target.get("path") or "")
        if not path:
            await _notify(session, progress, "委派需要先定位目标文件")
            return
        facts = session.data.get("facts") or []
        passed = [item for item in facts if item.get("passed")]

        name = str(target.get("name", ""))

        async def _execute(_order: WorkOrder) -> str:
            summary = f"目标 {name} 已取证 {len(passed)}/{len(facts)} 项"
            evidence = [str(item.get("evidence", ""))[:120] for item in passed[:5]]
            return _json.dumps({"summary": summary, "evidence": evidence}, ensure_ascii=False)

        order = WorkOrder(
            id=f"delegate-{session.session_id[:8]}",
            parent_turn_id=str(session.data.get("turn_id", "")),
            profile="code_scout",
            objective=str(session.data.get("sentence", "")) or "汇总当前取证",
            scope_files=(path,),
        )
        orders = self._orders_from_payload(session) or [order]
        # K6 多波流水线：决策层草案 → 工单列表按波调度（无草案时单工单=单波，行为等价）。
        # team_orchestration 关闭 → 单工单直连调度闸（旧路径）。
        if self._cfg.team_orchestration:
            await self._run_delegation_waves(session, orders, progress, execute=_execute)
            return
        # 阶段9：工单过调度闸（可运行性→文件占位→分池容量）再执行；被拒只降级不阻断。
        try:
            result = await self._coordinator.run(
                order, lambda o: run_read_worker(o, execute=_execute)
            )
        except ValueError as exc:
            emit(
                "delegation.rejected",
                reason=str(exc)[:120],
                request_id=str(session.data.get("last_request_id", "")),
            )
            await _notify(session, progress, f"委派被调度闸拒绝：{exc}")
            return
        session.data["delegation"] = {
            "status": result.status,
            "summary": result.output[:300],
            "evidence": list(result.evidence),
            "salvaged": result.salvaged,
            "evidence_status": result.evidence_status,
        }
        await _notify(
            session,
            progress,
            f"委派完成（{result.status}）：{result.output[:200]}",
        )

    @staticmethod
    def _orders_from_payload(session: FlowSession) -> list[WorkOrder]:
        """决策层草案 → 工单列表（K6 多波来源）。

        空目标草案丢弃；依赖以草案序号引用（"0"/"1"…），换成本单 id；
        profile 白名单由 `DelegationOrderDraft` 的 Literal 在解析层强制；
        无有效草案返回空列表（走确定性单工单）。
        """
        from devprompt_ai.domain.agent.work_order import WorkOrder

        payload = session.data.get("delegation_orders")
        if not isinstance(payload, list) or not payload:
            return []
        drafts: list[dict[str, Any]] = []
        for item in payload[:8]:
            if not isinstance(item, dict):
                continue
            objective = str(item.get("objective") or "").strip()
            if not objective:
                continue
            profile = str(item.get("profile") or "code_scout")
            drafts.append(
                {
                    "profile": profile if profile in {"code_scout", "verifier"} else "code_scout",
                    "objective": objective[:300],
                    "scope_files": tuple(str(f) for f in (item.get("scope_files") or ()) if str(f))[
                        :6
                    ],
                    "dependencies": tuple(
                        str(d) for d in (item.get("dependencies") or ()) if str(d)
                    ),
                }
            )
        if not drafts:
            return []
        prefix = f"delegate-{session.session_id[:8]}"
        ids = [f"{prefix}-{index}" for index in range(len(drafts))]
        return [
            WorkOrder(
                id=ids[index],
                parent_turn_id=str(session.data.get("turn_id", "")),
                profile=draft["profile"],
                objective=draft["objective"],
                scope_files=draft["scope_files"],
                dependencies=tuple(
                    ids[int(dep)]
                    for dep in draft["dependencies"]
                    if dep.isdigit() and int(dep) < len(drafts) and int(dep) != index
                ),
            )
            for index, draft in enumerate(drafts)
        ]

    async def _run_delegation_waves(
        self,
        session: FlowSession,
        orders: Sequence[WorkOrder],
        progress: ProgressSink | None = None,
        *,
        execute: Callable[[Any], Awaitable[str]],
    ) -> None:
        """K6：工单按波次经调度闸执行，结果按 id 落位；被拒/失败只降级不阻断。

        单工单时与直连调度闸行为等价（单波）；多工单逐波串行保证占位闸正确。
        """
        from devprompt_ai.domain.agent.delegation import WorkerResult
        from devprompt_ai.domain.agent.team import merge_results, plan_waves
        from devprompt_ai.harness.worker_session import run_read_worker

        try:
            waves = plan_waves(orders)
        except ValueError as exc:
            emit(
                "delegation.rejected",
                reason=str(exc)[:120],
                request_id=str(session.data.get("last_request_id", "")),
            )
            await _notify(session, progress, f"委派计划被拒：{exc}")
            return
        results: dict[str, WorkerResult] = {}
        for wave in waves:
            emit(
                "delegation.wave",
                wave=wave.index,
                total=len(waves),
                orders=[o.id for o in wave.orders],
                request_id=str(session.data.get("last_request_id", "")),
            )
            for order in wave.orders:
                try:
                    results[order.id] = await self._coordinator.run(
                        order, lambda o: run_read_worker(o, execute=execute)
                    )
                except ValueError as exc:
                    emit(
                        "delegation.rejected",
                        reason=str(exc)[:120],
                        request_id=str(session.data.get("last_request_id", "")),
                    )
                    await _notify(session, progress, f"委派被调度闸拒绝：{exc}")
                    continue
        first = next(iter(results.values()), None)
        if first is None:
            await _notify(session, progress, "委派全部被调度闸拒绝")
            return
        session.data["delegation"] = {
            "status": first.status,
            "summary": first.output[:300],
            "evidence": list(first.evidence),
            "salvaged": first.salvaged,
            "evidence_status": first.evidence_status,
            "results": merge_results(orders, results),
        }
        await _notify(session, progress, f"委派完成（{first.status}）：{first.output[:200]}")

    async def _attach_impact(
        self, session: FlowSession, *, project_root: str, request_id: str
    ) -> None:
        """把目标文件的反向依赖写入 session.data['impact_files']（最多 10 条）。

        索引懒建：每会话首次检索时建一次；失败只降级为「无影响信息」，不阻断取证。
        """
        if not bool(getattr(self._cfg, "repo_graph_enabled", False)):
            return
        target = session.data.get("target") or {}
        path = str(target.get("path") or "")
        root = project_root
        if not path or not root:
            return
        # 只在明确的 Python 项目上建图：无 pyproject/setup 的目录（大量测试夹具）跳过，
        # 否则每次首检索都要扫 800 个文件，把 30s 的测试拖成 3 分钟。
        marker = Path(root)
        if not ((marker / "pyproject.toml").exists() or (marker / "setup.py").exists()):
            return
        try:
            if not session.data.get("repo_indexed"):
                await index_project(self._cfg.db_path, root)
                session.data["repo_indexed"] = True
            impact = await impact_for(self._cfg.db_path, root, path)
        except Exception as exc:  # noqa: BLE001 - 索引是增益信息，失败必须降级
            logger.debug("retrieval.impact_failed", exc_info=exc)
            return
        if not impact:
            return
        # I6 访问强化：本次触及的边权重 +（长期不用自然衰减），并作同跳数内的次级排序
        index = SQLiteRepoIndex(self._cfg.db_path)
        weights: dict[str, float] = {}
        try:
            await index.reinforce_edges(project_root, [(src, path) for src in impact])
            weights = await index.edge_weights(project_root, path)
        except Exception as exc:  # noqa: BLE001 - 权重是增益信息，失败不阻断
            logger.debug("retrieval.edge_weight_failed", exc_info=exc)
        items = sorted(impact.items(), key=lambda pair: (pair[1], -weights.get(pair[0], 1.0)))[:10]
        session.data["impact_files"] = [
            {"path": p, "hops": h, "weight": round(weights.get(p, 1.0), 4)} for p, h in items
        ]
        emit("retrieval.impact", count=len(impact), request_id=request_id)

    def _render_ledger(self, session: FlowSession) -> str:
        """B15：按开关生成只读账本；关闭或失败时返回空串。"""
        if not bool(getattr(self._cfg, "context_ledger_enabled", False)):
            return ""
        from devprompt_ai.domain.context.ledger import LedgerInput, build_ledger
        from devprompt_ai.domain.context.task_contract import TaskContract

        target = session.data.get("target") or {}
        sensorium = session.data.get("sensorium") or {}
        facts = session.data.get("facts") or []
        try:
            contract = TaskContract(
                objective=str(session.data.get("sentence", ""))[:200],
                scope_paths=(str(target.get("path", "")),) if target.get("path") else (),
            )
            return build_ledger(
                LedgerInput(
                    contract=contract,
                    turn_index=int(session.data.get("turn_index", 0) or 0),
                    files_modified=1 if target.get("path") else 0,
                    verified=sum(1 for item in facts if item.get("passed")),
                    sensorium_score=float(sensorium.get("score", 0.0) or 0.0),
                )
            )
        except Exception:  # noqa: BLE001 - 账本是增益信息，失败即不注入
            return ""

    @staticmethod
    def _phase_for(steps: list[AgentStep]) -> PhaseClass:
        """按最近一步动作判定阶段：决定收敛权重（执行期看改动、验证期看错误）。"""
        if not steps:
            return PhaseClass.PLAN
        action = steps[-1].action
        if action in (AgentAction.RETRIEVE, AgentAction.PROBE):
            return PhaseClass.EXPLORE
        if action is AgentAction.GENERATE:
            return PhaseClass.EXECUTE
        if action is AgentAction.DELIVER:
            return PhaseClass.DELIVER
        return PhaseClass.PLAN

    @staticmethod
    def _is_wedged(steps: list[AgentStep], *, repeats: int = 4) -> bool:
        """连续 N 步同一动作且事实数无增长 → 原地打转（A4）。

        取 4 而非常见的 3：收敛检测在 3 步时只给 L2 提醒，这里不抢它的预警机会；
        4 步仍未推进才判卡死，5 步则由收敛熔断兜底。
        """
        if len(steps) < repeats:
            return False
        tail = steps[-repeats:]
        if len({step.action for step in tail}) != 1:
            return False
        return tail[0].facts_passed == tail[-1].facts_passed

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
        # 先入账再读成本：否则本步刚完成的 LLM 调用不会体现在 pressure 里。
        self._account_usage(session)
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
                context_tokens=int(session.data.get("context_tokens", 0)),
                context_window=int(self._cfg.runtime_state_budget()),
                claim_coverage=coverage,
                notes_hit=int(session.data.get("notes_hit", 0)),
                turn_index=int(session.data.get("turn_index", 0)),
            )
        )
        session.data["sensorium"] = snapshot.as_payload()
        # E4 策略映射（shadow）：effort/breadth 只落会话，供生成侧与观测消费
        strategy = derive_strategy(snapshot)
        session.data["strategy"] = {
            "reasoning_effort": strategy.reasoning_effort,
            "exploration_breadth": round(strategy.exploration_breadth, 4),
        }
        emit("agent.sensorium", score=snapshot.score, request_id=request_id)

    async def _record_token_ledger(self, session: FlowSession) -> None:
        """H5：每轮一次把 LLM 用量落 token_ledger；零用量不记（空行无信息量）。"""
        if self._token_ledger is None:
            return
        if int(session.data.get("cost_tokens", 0)) <= 0:
            return
        try:
            await self._token_ledger.record(
                session_id=session.session_id,
                turn_index=int(session.data.get("turn_index", 0) or 0),
                prompt_tokens=int(session.data.get("cost_prompt_tokens", 0)),
                completion_tokens=int(session.data.get("cost_completion_tokens", 0)),
                cached_tokens=int(session.data.get("cost_cached_tokens", 0)),
            )
        except Exception:  # noqa: BLE001 - 账本是旁路，失败不阻断收尾
            logger.warning("ledger.record_failed", exc_info=True)

    @staticmethod
    def _step_outcome(action: AgentAction, session: FlowSession) -> StepOutcome:
        """非终态动作失败的落账点（E10 死路检测的数据源）。

        当前唯一非终态失败是委派 blocked/partial（其余失败会终止本轮）；
        后续动作有了「失败但可继续」的路径在此补记。
        """
        if action is AgentAction.DELEGATE:
            delegation = session.data.get("delegation")
            if isinstance(delegation, dict) and delegation.get("status") in {"blocked", "partial"}:
                return StepOutcome.FAILED
        return StepOutcome.OK

    async def _emit_checkpoint(
        self,
        session: FlowSession,
        steps: list[AgentStep],
        action: AgentAction,
        request_id: str,
    ) -> None:
        """把执行进度写入 run_events；sink 未装配或写入失败只降级为跳过。"""
        if self.checkpoint_sink is None:
            return
        try:
            await self.checkpoint_sink(
                session.session_id,
                {
                    "step": len(steps),
                    "action": action.value,
                    "facts_passed": sum(
                        1 for f in session.data.get("facts", []) if f.get("passed")
                    ),
                    "request_id": request_id,
                },
            )
        except Exception:  # noqa: BLE001 - checkpoint 是旁路，失败不阻断主循环
            logger.debug("checkpoint.write_failed", exc_info=True)

    async def _abort_quietly(self, session: FlowSession) -> None:
        """失败兜底（6G 遗留①）：异常路径置 ABORTED，避免死会话（如 PROBING）残留污染历史。"""
        try:
            await transition(session, FlowState.ABORTED, self._sessions)
        except Exception:
            logger.exception("state.abort_failed", extra={"session_id": session.session_id})
        # 阶段7 记忆沉淀：静默中断同样要收尾（落 turn 记录与 L2 笔记），否则中断轮在
        # 下一轮「不可回看」。_finish_turn 幂等（重复 finish 只改状态），尽力而为。
        try:
            await self._finish_turn(session)
        except Exception:  # noqa: BLE001 - 收尾失败不得掩盖原始异常
            logger.debug("turn.finish_failed_on_abort", exc_info=True)

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

        2026-11-10：**id 必须唯一**。前端曾按页内序号生成 `p-new-N`，刷新页面后会与
        已落盘的 id 撞名；两个供应商撞名后，写侧按 id 去重只剩一条，模型条目却全部
        保留，表现为「MiniMax 名下出现 Kimi 模型」。撞名即整单拒绝，不静默合并。
        """
        ids = [str(raw.get("id") or "").strip() for raw in incoming]
        duplicates = sorted(
            {record_id for record_id in ids if record_id and ids.count(record_id) > 1}
        )
        if duplicates:
            raise ConfigurationError(
                "供应商 id 重复，未写入任何改动："
                + "、".join(duplicates)
                + "（每个供应商必须有唯一 id）",
                context={"duplicate_provider_ids": duplicates},
            )
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

    async def get_settings(self, locale: Locale = DEFAULT_LOCALE) -> dict[str, Any]:
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
            "providers": providers_projection(locale),
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
            "observability": {
                "trace_enabled": cfg.obs_trace_enabled,
                "trace_retention_days": cfg.obs_trace_retention_days,
                "metrics_enabled": cfg.obs_metrics_enabled,
                "replay_enabled": cfg.obs_replay_enabled,
            },
            "locked": {"candidate_limit": MAX_CANDIDATES},  # MUST-09 宪法常量，只读下发
        }

    def _allowed_efforts(self, provider: str, model_id: str, base_url: str) -> set[str]:
        """该模型可用的 effort 集合：静态能力位 ∪ 动态目录。

        两者都查不到时返回空集（表示「能力位未知」）：此时不拒绝显式值，避免把
        动态目录先于静态表提供的合法档位误杀。
        """
        allowed: set[str] = set()
        meta = model_meta_of(provider, model_id)
        if meta is not None:
            allowed.update(meta.reasoning_efforts)
        try:
            items, _ = read_model_catalog(resolve_provider_key(provider), base_url)
        except Exception:  # noqa: BLE001 - 校验辅助失败按「未知」处理，不阻断保存
            items = []
        wanted = model_id.strip().lower()
        for item in items:
            if item.model_id.strip().lower() == wanted:
                allowed.update(item.reasoning_efforts)
                break
        return allowed

    @staticmethod
    def _validate_registry_entries(merged: list[dict[str, Any]]) -> list[str]:
        """写盘前校验注册表条目。返回问题描述列表（空 = 通过）。

        N-5 为什么要这一步：`_merge_registry_entries` 已做到「先算清再一次性写」，
        但它对**内容合法性**不设防——一个 `model_id` 为空的条目会被完整写入并可能成为
        激活项，用户得到的是「已保存」却根本调不通。宁可整单拒绝，也不要半成品。

        仅做**与模型能力无关**的结构校验；思考强度与窗口档位的校验在
        :meth:`_validate_model_tuning`（需要读取目录/静态表）。
        """
        problems: list[str] = []
        seen: set[tuple[str, str]] = set()
        for index, entry in enumerate(merged):
            name = str(entry.get("model_id") or entry.get("id") or f"第 {index + 1} 项")
            if not str(entry.get("model_id", "")).strip():
                problems.append(f"{name}：缺少模型标识（model_id）")
            if not str(entry.get("base_url", "")).strip():
                problems.append(f"{name}：缺少服务地址（base_url）")
            api_key = entry.get("api_key", "")
            if api_key is not None and not isinstance(api_key, str):
                problems.append(f"{name}：api_key 必须是字符串")
            # 同一供应商下同一模型只应有一条（前端曾因供应商 id 撞名而重复提交）
            pair = (
                str(entry.get("provider_id", "")),
                str(entry.get("model_id", "")).strip().lower(),
            )
            if pair[1]:
                if pair in seen:
                    problems.append(f"{name}：同一供应商下重复出现该模型")
                seen.add(pair)
        return problems

    def _validate_model_tuning(self, merged: list[dict[str, Any]]) -> list[str]:
        """校验思考强度与上下文长度（2026-11-10）。

        - effort 非空时必须在该模型登记的集合内；
        - 窗口非空时必须能被 `effective_window` 原样接受（被回落即说明越界）。
        """
        problems: list[str] = []
        for index, entry in enumerate(merged):
            name = str(entry.get("model_id") or entry.get("id") or f"第 {index + 1} 项")
            provider = str(entry.get("provider", ""))
            model_id = str(entry.get("model_id", ""))
            effort = str(entry.get("reasoning_effort", "") or "").strip().lower()
            if effort:
                allowed = self._allowed_efforts(provider, model_id, str(entry.get("base_url", "")))
                if allowed and effort not in allowed:
                    options = "、".join(sorted(allowed))
                    problems.append(f"{name}：不支持的思考强度 {effort}（可选：{options}）")

            window = entry.get("max_context_length")
            if isinstance(window, int) and window > 0:
                effective = self.effective_window(provider, model_id, window)
                # 窗口完全未知（自定义端点）时不误杀：没有合法集合就无从校验。
                if effective is not None and effective != window:
                    problems.append(
                        f"{name}：上下文长度 {window} 不在该模型可选档位内"
                        f"（合法值需来自模型窗口档位集合）"
                    )
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
        obs_in: dict[str, Any] = dict(update.get("observability") or {})
        obs_write = {
            cfg_key: value
            for api_key, cfg_key in _OBS_SETTING_KEYS.items()
            if (value := obs_in.get(api_key)) is not None
        }
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
            problems.extend(self._validate_model_tuning(merged))
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
            # 2026-11-10：只改 models（如启动页调思考强度/窗口）时也要把**当前激活条目**
            # 重新镜像进运行配置，否则设置落盘了但运行时仍是旧值（参数形同装饰）。
            target_active_id = active_id or str(registry.get("active_model_id") or "")
            active_entry = next((e for e in merged if str(e.get("id")) == target_active_id), None)
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
                # 2026-11-10：空值→none 在此解析（需要模型能力位）；显式值原样保留。
                entry_effort = str(active_entry.get("reasoning_effort", "") or "")
                allowed = self._allowed_efforts(
                    str(active_entry.get("provider", "")),
                    str(active_entry.get("model_id", "")),
                    str(active_entry.get("base_url", "")),
                )
                resolved_effort = resolve_effort(entry_effort, tuple(allowed))
                if resolved_effort:
                    current = mirror.get("llm_params")
                    merged_params: dict[str, Any] = (
                        dict(current) if isinstance(current, dict) else {}
                    )
                    merged_params["reasoning_effort"] = resolved_effort
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
        if process_write or obs_write:
            await asyncio.to_thread(write_process_settings, {**process_write, **obs_write})
        for src_key, value in model_write.items():
            setattr(self._cfg, MODEL_KEY_MAP[src_key], value)
        for key, value in process_write.items():
            setattr(self._cfg, key, value)
        for key, value in obs_write.items():
            setattr(self._cfg, key, value)
        self._cfg.validate()
        set_telemetry(self._cfg.telemetry)
        if obs_write:
            modules = getattr(self, "obs", None)
            if modules is not None:
                # 即时生效（独立启停）：采集器/三服务各自读自己的开关
                modules.apply_settings(self._cfg)
                # 保留天数变更立即回收过期 Trace（启动时也做一次，此处是运行期入口）
                await modules.trace.startup(self._cfg.obs_trace_retention_days)
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
        """研判取证结果，写入 unknowns / facts_complete，返回「是否有未决问题」。

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
            answered_header_asks=answered_headers(
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
        # 2026-11-07：`judged` 必须为真。模型参数畸形时 fallback 返回空 judgments，
        # 旧口径把「没有未知」当成「信息足够」，档位会虚高到最高档（静默降质）。
        evidence_ok = is_evidence_complete(facts)
        judged = bool(probe.judgments)
        if not judged and not unknowns:
            emit(
                "decision.probe_empty",
                reason=str(probe.confidence_source),
                request_id=request_id,
            )
        facts_complete = is_probe_complete(
            evidence_ok=evidence_ok,
            measured=measured,
            confidence=confidence,
            threshold=self._cfg.fact_probe_threshold,
            has_unknowns=bool(unknowns),
            judged=judged,
        )
        session.data["facts_complete"] = facts_complete
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
        self, session: FlowSession, *, shrink: bool = False
    ) -> GenerationContext:
        """装配生成/回答共用的上下文（2026-11-05 抽出，避免两处漂移）。

        回答追问所依赖的 ``previous_variants`` 与 ``history_block`` 与生成完全同源，
        因此不另建上下文类型。``shrink``（A8）时同时丢弃上一轮方案正文——超窗最
        常见的元凶就是它。
        """
        context_payload = await self._assemble_context(session, shrink=shrink)
        return GenerationContext(
            sentence=session.data["sentence"],
            project_root=session.data["project_root"],
            facts_summary=session.data.get("facts_summary", _summarize_facts(session)),
            clarifications=session.data.get("clarifications", {}),
            conservative=bool(session.data.get("conservative", False)),
            history_block=context_payload.history_block,
            memory_block=context_payload.memory_block,
            # 迭代轮要让模型看到上一轮原文，否则「把第 2 条改成 X」无法定位
            previous_variants=(
                ""
                if shrink
                else _render_previous_variants(
                    TurnMemory.from_payload(session.data.get("turn_memory")).variants
                )
            ),
            # 四段式方案的两路证据（2026-11-11）：超窗压缩时**保留**——
            # 它们是最小充分证据，比上一轮方案正文更不可替代。
            target_excerpt=str(session.data.get("target_excerpt", "")),
            design_tokens=tuple(session.data.get("design_tokens") or ()),
            # 领域包（2026-11-14）：模板据此切换分段语义与领域指令
            domain_id=self._domain_id(session),
            # 多模态（2026-11-14）：visual 域风格与图生图参考图
            style_id=str(session.data.get("style", "")),
            images=tuple(str(x) for x in session.data.get("images") or ()),
        )

    async def _generate_single_guarded(
        self,
        session: FlowSession,
        ctx: GenerationContext,
        locale: Locale,
        *,
        fallback: bool = False,
    ) -> VariantDraft:
        """A8 超窗「压一次重发一次」：只对上下文超限降级，其它异常原样抛出。"""
        try:
            return await self._generator.generate_single(ctx, locale, fallback=fallback)
        except Exception as exc:
            if not is_context_overflow(exc):
                raise
        emit(
            "context.overflow_retry",
            request_id=str(session.data.get("last_request_id", "")),
        )
        shrunk = await self._generation_context(session, shrink=True)
        return await self._generator.generate_single(shrunk, locale, fallback=fallback)

    async def _answer_guarded(
        self,
        session: FlowSession,
        ctx: GenerationContext,
        locale: Locale,
    ) -> str:
        """纯回答的超窗保护：与三套生成同构，压一次重发一次。

        回答轮同样依赖 ``history_block`` 与上一轮方案正文；窗口调小后若不压缩，
        会以未分类异常中断整轮（2026-11-10）。
        """
        try:
            return await self._generator.answer(ctx, locale)
        except Exception as exc:
            if not is_context_overflow(exc):
                raise
        emit(
            "context.overflow_retry",
            request_id=str(session.data.get("last_request_id", "")),
        )
        shrunk = await self._generation_context(session, shrink=True)
        return await self._generator.answer(shrunk, locale)

    async def _act_generate(
        self, session: FlowSession, *, progress: ProgressSink | None = None
    ) -> VariantDraft:
        """生成唯一方案并写入 ``session.data["variant"]``（2026-11-11 单套输出）。

        主流程用 B 标准版；抛 ``GenerationError`` 或产出非法（标题/正文为空）时
        用 A 保守版兜底一次，产物 ``fallback=True``。兜底同样失败则抛原异常——
        不得伪造正文（spec「兜底仍失败」）。
        """
        await hop(session, FlowState.GENERATING, self._sessions)
        locale = _session_locale(session)
        # 先清零：生成失败抛出时不得残留上一轮/继承态让调度层误判「本轮已生成」。
        session.data["generated_variant_count"] = 0
        ctx = await self._generation_context(session)
        await _notify(session, progress, generation_text(locale))
        # 流式增量出口（2026-11-15）：生成期间把首个 delta 起就推给前端，首字感知降至秒级
        sink_token = set_generation_sink(progress)
        try:
            draft = await self._generate_single_guarded(session, ctx, locale)
            self._require_valid_draft(draft)
        except GenerationError as first_error:
            emit(
                "generate.fallback",
                reason=str(first_error),
                request_id=session.data.get("last_request_id", ""),
            )
            try:
                draft = await self._generate_single_guarded(session, ctx, locale, fallback=True)
                self._require_valid_draft(draft)
            except Exception:
                # 兜底也失败：抛原异常，不产出半个方案（错误信息保留主流程原因）
                raise first_error from None
        finally:
            reset_generation_sink(sink_token)
        # slots dataclass 无 __dict__，序列化必须走 model_dump（计划 §6.2 注意事项）
        session.data["variant"] = draft.model_dump()
        # 记录本轮实际生成套数，供调度层区分「继承的旧方案」与「本轮成果」。
        session.data["generated_variant_count"] = 1
        if draft.fallback:
            # 兜底披露（spec）：文案走既有 message 字段，不新增 i18n 键。
            session.data["message"] = "已降级为保守输出"
        await self._audit_claims(session, draft)
        return draft

    @staticmethod
    def _require_valid_draft(draft: VariantDraft) -> None:
        """结构非法（标题/正文为空）视同生成失败，交由兜底路径处理。"""
        if not draft.title.strip() or not draft.body.strip():
            raise GenerationError(
                "生成方案标题或正文为空",
                code=4003,
                context={"title_len": len(draft.title), "body_len": len(draft.body)},
            )

    @staticmethod
    def _claim_evidence_text(session: FlowSession) -> str:
        """断言对账的证据源（2026-11-11）：目标路径 + 代码片段 + 令牌 + 事实证据。

        只用 ``FactResult.evidence`` 时，引用组件、跨文件路径、行号与 AntD 类 token 的
        断言恒判未覆盖（账本失真）；这几路证据拼在一起后覆盖判据才与正文实际引用对齐。
        """
        parts: list[str] = []
        target = session.data.get("target")
        if isinstance(target, dict) and target.get("path"):
            parts.append(str(target["path"]))
        excerpt = str(session.data.get("target_excerpt", "") or "")
        if excerpt:
            parts.append(excerpt)
        tokens = session.data.get("design_tokens") or ()
        if tokens:
            parts.append("\n".join(str(item) for item in tokens))
        for item in session.data.get("facts", []) or []:
            if isinstance(item, dict):
                evidence = str(item.get("evidence", "") or "")
                if evidence:
                    parts.append(evidence)
        return "\n".join(parts)

    async def _verified_file_claims(self, session: FlowSession, draft: VariantDraft) -> list[str]:
        """``file`` 断言引用的第三个文件做有界存在性核对（去重、上限 5 个）。

        为什么需要：证据源只含目标文件与片段，模型引用工具函数/父组件时必然判未覆盖
        （假阴性）。存在性核对把「确实存在的文件」补进证据源，不改 ``match_claims``。
        上限 5 防止模型声明几十条路径导致每轮几十次 stat。
        """
        root = str(session.data.get("project_root", ""))
        targets: list[str] = []
        for claim in draft.claims:
            if claim.kind != "file":
                continue
            target = claim.target.strip().replace("\\", "/")
            if target and target not in targets:
                targets.append(target)
        hits: list[str] = []
        for target in targets[:5]:
            full = safe_join(root, target)
            if not full:
                continue
            try:
                exists = await self._reader.exists(full)
            except Exception:  # noqa: BLE001 - 核对失败按「未命中」处理，不影响对账
                exists = False
            if exists:
                hits.append(f"file={target}")
        return hits

    async def _audit_claims(self, session: FlowSession, draft: VariantDraft) -> None:
        """断言对账（2026-11-04）：覆盖率与缺口如实留痕，不重新生成。

        2026-11-11：单套方案不再跨档累加，证据源见 :meth:`_claim_evidence_text`。
        2026-11-12：``file`` 断言先对引用文件做有界存在性核对，消除假阴性。
        覆盖不足由交付门披露（claim_strict 决定「未声明」是否计入 RED）。
        """
        facts = [FactResult(**f) for f in session.data.get("facts", [])]
        evidence = self._claim_evidence_text(session)
        extra = await self._verified_file_claims(session, draft)
        if extra:
            evidence = f"{evidence}\n{' '.join(extra)}" if evidence else " ".join(extra)
        report = validate_claims(draft, facts, evidence)
        session.data["claim_report"] = {
            "total": report.total,
            "covered": report.covered,
            "uncovered": list(report.uncovered),
            "coverage": report.coverage,
            "undeclared": report.undeclared,
            "summary": report.render(_session_locale(session)),
        }
        if report.undeclared:
            if self._cfg.claim_strict:
                emit(
                    "evidence.claim_undeclared",
                    request_id=session.data.get("last_request_id", ""),
                )
            return
        if report.coverage >= CLAIM_COVERAGE_MIN:
            return
        emit(
            "evidence.claim_uncovered",
            total=report.total,
            covered=report.covered,
            request_id=session.data.get("last_request_id", ""),
        )

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
        text = await self._answer_guarded(session, ctx, _session_locale(session))
        if not text.strip():
            # A3 no-answer 闸：空回答不算完成，按放弃收尾并留下结构化原因。
            session.data["stop_reason"] = StopReason.NO_ANSWER.value
            await self._act_abort(session, reason="no_answer")
            return self._snapshot(session, "aborted")
        session.data["reply_text"] = text
        if FlowState(session.state) is not FlowState.DONE:
            await transition(session, FlowState.DONE, self._sessions)
        self._emit_completed(session, variants=0)
        await self._finish_turn(session)
        return self._snapshot(session, "done")

    async def _act_deliver(
        self, session: FlowSession, *, progress: ProgressSink | None = None
    ) -> FlowSnapshot:
        """交付：锚点核验 → 证据门 → 转 DONE 并回填产出。

        顺序固定（spec「统一核验并入 B」）：写方案与断言对账在 ``_act_generate``
        内完成，这里只做锚点核验与门禁判定。门禁只降质量标记，**不阻断交付**。
        """
        await self._verify_anchors(session)
        verdict = self._evaluate_delivery_gate(session)
        session.data["delivery_gate"] = {
            "status": verdict.status,
            "tone": verdict.tone,
            "reasons": list(verdict.reasons),
            "disclosure": verdict.disclosure,
        }
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
        variant = session.data.get("variant")
        self._emit_completed(session, variants=1 if isinstance(variant, dict) else 0)
        await self._finish_turn(session)
        return self._snapshot(session, "done")

    async def _verify_anchors(self, session: FlowSession) -> None:
        """正文锚点后端核验（2026-11-06 U-2，2026-11-11 并入单套常规链路）。

        对唯一方案执行：明确无效的锚点（文件不存在/行号越界）计入交付门并披露；
        判不清（读取失败、路径无法在项目内核验）保守不降级。
        """
        raw = session.data.get("variant")
        body = str(raw.get("body", "")) if isinstance(raw, dict) else ""
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
        # MUST-20：越界/非法路径等价于「目标不存在」，判明确无效（不读任何文件）。
        full = safe_join(root, anchor.path)
        if not full:
            return False
        try:
            if not await self._reader.exists(full):
                return False
            text = await self._reader.read(full)
        except Exception:  # noqa: BLE001 - 读取失败属判不清，保守不降档
            return None
        return 1 <= anchor.line <= len(text.splitlines())

    def _evaluate_delivery_gate(self, session: FlowSession) -> DeliveryVerdict:
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
            # 灰度关闭（claim_strict=False）时整条不参与门禁，保留披露不降档。
            coverage = None
            undeclared = self._cfg.claim_strict
        anchor_report = session.data.get("anchor_report")
        anchor_invalid = (
            len(anchor_report.get("invalid", [])) if isinstance(anchor_report, dict) else 0
        )
        # E11 改动归属：影响半径里未被任一 file 断言引用的文件 → YELLOW 披露
        attribution = self._build_attribution(session)
        # 通用域（2026-11-14 领域包）：无仓库证据可核，改核方案自身结构完整性
        structural = None
        if self._domain_id(session) != "code":
            variant = session.data.get("variant")
            if isinstance(variant, dict):
                structural = check_structural(
                    str(variant.get("body", "")),
                    [str(item) for item in variant.get("changes", []) if item],
                )
        variant = session.data.get("variant")
        is_fallback = bool(variant.get("fallback", False)) if isinstance(variant, dict) else False
        return evaluate_delivery(
            DeliveryInput(
                has_target=bool(session.data.get("target")),
                facts=facts,
                claim_coverage=coverage,
                claims_undeclared=undeclared,
                anchor_invalid_count=anchor_invalid,
                attribution=attribution,
                structural=structural,
                fallback=is_fallback,
            ),
            _session_locale(session),
        )

    @staticmethod
    def _build_attribution(session: FlowSession) -> Attribution | None:
        """影响半径与 file 断言求差集；无影响数据时返回 None（不参与门禁）。"""
        impact = session.data.get("impact_files")
        if not isinstance(impact, list) or not impact:
            return None
        variant = session.data.get("variant")
        claims = variant.get("claims") if isinstance(variant, dict) else None
        claimed = {
            str(claim.get("target"))
            for claim in (claims or [])
            if isinstance(claim, dict) and claim.get("kind") == "file"
        }
        uncovered = tuple(
            str(item.get("path"))
            for item in impact
            if isinstance(item, dict) and str(item.get("path")) not in claimed
        )
        return Attribution(uncovered_impact=uncovered)

    @staticmethod
    def _evaluate_finish_gate(session: FlowSession) -> FinishDecision:
        """A2 六道闸取值：本产品只保留 STEER 一道硬拦截。

        其余各道依赖对话式 Agent 的自由文本收尾：goal 缺失由交付门披露；义务清单
        不存在。STEER 弹回有界：纠偏会被下一轮决策消费。交付准入按 spec 收敛为
        「方案已生成」——没有 ``variant`` 时不允许收尾。
        """
        return evaluate_finish(
            GateInput(
                has_text=isinstance(session.data.get("variant"), dict),
                pending_steer=str(session.data.get("hook_correction", "")),
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
        """线性路径：GENERATING→DONE，与 agentic 循环共用同一批动作方法。"""
        await self._act_generate(session, progress=progress)
        return await self._act_deliver(session, progress=progress)

    async def _assemble_context(
        self, session: FlowSession, *, shrink: bool = False
    ) -> ContextPayload:
        """装配多轮上下文（纯函数在 domain/context）：历史摘要 + 偏好投影。

        ``shrink``（A8）：超窗重发时把 estimated 拉满窗口，强制走压缩档位出最小历史。
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
        estimated = (
            estimate_ctx_tokens(current.render())
            + sum(estimate_ctx_tokens(summary.render()) for summary in summaries)
            + sum(estimate_ctx_tokens(note) for note in notes)
        )
        # E3：绝对压力的分母数据源（六维 pressure 与压缩决策共用同一估算口径）
        session.data["context_tokens"] = estimated
        # 2026-11-10：窗口取条目档位（未登记回落全局）；它驱动压缩与请求预算，
        # 但不硬截断 current 层（MUST-25）。
        window = self._cfg.runtime_window()
        if shrink:
            estimated = max(estimated, window)
        # B11：压缩触发时把窗口外的旧轮折成一段 LLM 摘要（失败回退规则摘要，不阻断）
        summaries = await self._maybe_llm_digest(
            session, summaries, estimated_tokens=estimated, shrunk=shrink
        )
        payload = build_context(
            summaries,
            current,
            notes=notes,
            budget=ContextBudget(total=self._cfg.runtime_state_budget()),
            context_window=window,
            estimated_tokens=estimated,
            cache_kind=CacheKind.AUTOMATIC,
            ledger_block=self._render_ledger(session),
            delta_block=self._render_context_delta(session),
        )
        # B13/B14：历史被压缩时把权威块重新注入消息尾部（与摘要冲突以本块为准）
        compacted = tuple(t for t in payload.truncated_layers if t.startswith("compacted:"))
        if compacted:
            tail = self._render_tail_anchor(session)
            if tail:
                payload = dataclasses.replace(
                    payload, history_block=compose_history(payload.history_block, anchor=tail)
                )
            emit(
                "context.compacted",
                layers=list(compacted),
                request_id=str(session.data.get("last_request_id", "")),
            )
        # MUST-11c 检测面：历史轮次前缀被改写（异常回滚等）只告警不阻断
        indexes = tuple(summary.turn_index for summary in summaries)
        previous_indexes = session.data.get("context_turn_indexes")
        if isinstance(previous_indexes, list) and not assert_append_only(previous_indexes, indexes):
            emit(
                "context.append_violation",
                request_id=str(session.data.get("last_request_id", "")),
            )
        session.data["context_turn_indexes"] = list(indexes)
        return payload

    def _render_tail_anchor(self, session: FlowSession) -> str:
        """压缩后的权威块：目标/范围/约束来自锚点，验收标准与已完成事实一并列明。"""
        anchor = anchor_from_payload(session.data.get("turn_anchor"))
        contract = TaskContract(
            objective=(
                anchor.objective
                if anchor is not None
                else str(session.data.get("sentence", ""))[:200]
            ),
            scope_paths=anchor.scope_paths if anchor is not None else (),
            constraints=anchor.constraints if anchor is not None else (),
            status=(
                ContractStatus.EXECUTING
                if session.data.get("facts_complete")
                else ContractStatus.EXPLORING
            ),
        )
        passed = tuple(
            str(item.get("key"))
            for item in session.data.get("facts", [])
            if isinstance(item, dict) and item.get("passed")
        )
        return render_tail_anchor(contract, completed=passed)

    async def _maybe_llm_digest(
        self,
        session: FlowSession,
        summaries: list[TurnSummary],
        *,
        estimated_tokens: int,
        shrunk: bool,
    ) -> list[TurnSummary]:
        """B11：压缩触发时把 recent(2)+digest(6) 窗口外的旧轮折成一段 cheap 槽摘要。

        `summary_llm_enabled` 关闭时原样返回（规则摘要路径，现状行为）；
        摘要失败由 `summarize_history` 兜底为确定性 handoff，本方法不向上抛。
        """
        if not self._cfg.summary_llm_enabled or not summaries:
            return summaries
        plan = plan_compaction(
            estimated_tokens=estimated_tokens,
            window=self._cfg.runtime_window(),
            cache_kind=CacheKind.AUTOMATIC,
        )
        if not (shrunk or plan.should_compact):
            return summaries
        keep = 2 if shrunk else 8  # 弹性收缩时保住 recent 两轮，「接着刚才说的」不能断
        dropped = summaries[:-keep] if len(summaries) > keep else summaries[:1]
        if not dropped:
            return summaries
        anchor = anchor_from_payload(session.data.get("turn_anchor"))
        digest, _fell_back = await summarize_history(
            self._cfg,
            "\n".join(item.render() for item in dropped),
            required_terms=(),
            fallback_context={
                "objective": anchor.objective if anchor is not None else "",
                "decisions": [item.decision for item in dropped if item.decision],
                "files": [item.target for item in dropped if item.target],
                "current": summaries[-1].conclusion,
            },
        )
        merged = TurnSummary(
            turn_id=f"digest-{dropped[-1].turn_index}",
            turn_index=dropped[-1].turn_index,
            conclusion=digest[:200],
        )
        return [merged, *summaries[len(dropped) :]]

    def _render_context_delta(self, session: FlowSession) -> str:
        """B1–B4 增量附录：只下发本轮变动的上下文块，无变动时自闭合。

        shortcut: 每次 LLM 调用都是无状态单发，增量只作「自上次以来的变化」提示，
        缺内容时仍以完整历史为准；会话改为携带消息历史后再改成真正的增量替换。
        """
        if not self._cfg.context_layers_enabled:
            return ""
        blocks = {"task_status": "executing" if session.data.get("facts_complete") else "exploring"}
        previous = session.data.get("prompt_layers")
        prev = previous if isinstance(previous, dict) else {}
        # seq 用上次快照 +1 递增：turn_index 在没有 turn 存储时不增，靠它算会永远停在首轮
        seq = int(prev.get("seq", 0) or 0) + 1
        prev_context = prev.get("context")
        session.data["prompt_layers"] = {"seq": seq, "context": blocks}
        return render_delta(
            prev_context if isinstance(prev_context, dict) else None, blocks, seq=seq
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
            "prev_facts_complete": previous_summary.get("facts_complete"),
            "cost_tokens": 0,
            "cost_llm_tokens": 0,
            "rounds": 0,
        }
        if memory.variants:
            # 单套输出：撤销重建时只保留最近一套。
            session.data["variant"] = memory.variants[-1].model_dump()
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
        raw_variant = session.data.get("variant")
        if isinstance(raw_variant, dict):
            with contextlib.suppress(TypeError, ValueError):
                variants.append(VariantDraft(**raw_variant))
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
            await self._record_token_ledger(session)
            variant = session.data.get("variant")
            await self._turns.finish(
                turn_id,
                state=session.state,
                facts=[dict(item) for item in session.data.get("facts", [])],
                clarifications=dict(session.data.get("clarifications", {})),
                output=[dict(variant)] if isinstance(variant, dict) else [],
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

    def _emit_completed(self, session: FlowSession, *, variants: int) -> None:
        """flow.completed（T6-9）：耗时 = 会话起点至生成收尾（跨反问轮次的真实全程）。"""
        started_at = float(session.data.get("started_at", 0.0))
        elapsed_ms = int((time.time() - started_at) * 1000) if started_at else None
        emit(
            "flow.completed",
            flow_id=session.session_id,
            variants=variants,
            elapsed_ms=elapsed_ms,
            request_id=session.data.get("last_request_id", ""),
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
        except Exception as exc:
            logger.exception(
                "ranking.rank_failed",
                extra={"reason": "decider-failed", "request_id": request_id},
            )
            # 排序失败直接回退分数第一名（2026-11-15）：留痕，避免「悄悄降级」无从定位
            emit(
                "decision.rank_degraded",
                candidates=len(candidates),
                reason=type(exc).__name__,
                request_id=request_id,
            )
            return candidates[0]
        _RANK_CACHE[key] = (now + _RANK_CACHE_TTL_SECONDS, list(out.order))
        if out.order and out.order[0] < len(candidates):
            return candidates[out.order[0]]
        return candidates[0]

    def _account_usage(self, session: FlowSession) -> None:
        """F-805：把本请求内已发生的全部 LLM 调用用量并入会话（取用后累计器清零）。

        2026-11-10：从 total-only 改为全字段聚合。探针/排序/打分与生成共用同一个
        聚合器，prompt/completion/cached 不再只记最后一次生成。
        """
        usage = take_llm_usage()
        total = usage.total
        if total <= 0 and (usage.prompt or usage.completion):
            total = usage.prompt + usage.completion
        if total <= 0 and not usage.prompt and not usage.completion and usage.cached is None:
            return
        session.data["cost_llm_tokens"] = int(session.data.get("cost_llm_tokens", 0)) + total
        session.data["cost_tokens"] = int(session.data.get("cost_tokens", 0)) + total
        if usage.prompt:
            session.data["cost_prompt_tokens"] = (
                int(session.data.get("cost_prompt_tokens", 0)) + usage.prompt
            )
        if usage.completion:
            session.data["cost_completion_tokens"] = (
                int(session.data.get("cost_completion_tokens", 0)) + usage.completion
            )
        if usage.cached is not None:
            session.data["cost_cached_tokens"] = (
                int(session.data.get("cost_cached_tokens", 0)) + usage.cached
            )

    @property
    def config(self) -> AppConfig:
        """只读配置：运行时层据此组装存储（不反向依赖 interfaces）。"""
        return self._cfg

    def _snapshot(self, session: FlowSession, status: SnapshotStatus) -> FlowSnapshot:
        self._account_usage(session)
        llm_tokens = int(session.data.get("cost_llm_tokens", 0))
        cost = CostBreakdown(
            llm_tokens=llm_tokens,
            total_tokens=llm_tokens,
            llm_source="actual" if llm_tokens > 0 else "no_call",
        )
        # 反问只属于 ask 状态（2026-11-15）：DONE/ABORTED 等状态不得携带未问出口的 unknowns，
        # 否则前端会渲染「等待确认」提示却无处可答（实测：done 快照仍带 2 条含选项的问题）。
        questions = (
            [_unknown_from(raw) for raw in session.data.get("unknowns", [])]
            if status == "ask"
            else []
        )
        variant_data = session.data.get("variant")
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
            variant=VariantDraft(**variant_data) if isinstance(variant_data, dict) else None,
            target=target,
            facts=facts,
            cost=cost,
            message=str(session.data.get("message", "")),
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
            domain=(
                session.data.get("domain") if isinstance(session.data.get("domain"), dict) else None
            ),
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
    from devprompt_ai.harness.obs.traced_ports import (
        TracedDecider,
        TracedGenerator,
        TracedReader,
        TracedRunner,
        TracedSymbolProvider,
    )
    from devprompt_ai.harness.output_store import cleanup as cleanup_raw_outputs
    from devprompt_ai.memory.project_note_store import SQLiteProjectNoteStore
    from devprompt_ai.memory.session_store import SQLiteSessionStore
    from devprompt_ai.memory.startup_safety_check import run_startup_safety_check
    from devprompt_ai.memory.token_ledger import SQLiteTokenLedger as _TokenLedger
    from devprompt_ai.memory.turn_store import SQLiteTurnStore
    from devprompt_ai.obs import registry as obs_registry

    # N-1 启动自愈：必须在任何 Manager 打开库之前跑，坏行隔离才有意义
    run_startup_safety_check(cfg.db_path)
    # C3：清掉上一进程遗留的超时工件（内容已在卡片指针过期后无意义）
    cleanup_raw_outputs()

    sessions = SQLiteSessionStore(cfg.db_path)
    await sessions.init_schema()
    obs = obs_registry.build_obs_modules(cfg)
    await obs.startup()
    service = ForgeService(
        cfg=cfg,
        decider=TracedDecider(create_decider(cfg), obs.collector),
        sessions=sessions,
        runner=TracedRunner(LocalCommandRunner(), obs.collector),
        reader=TracedReader(LocalFileReader(), obs.collector),
        generator=TracedGenerator(LLMGenerator(cfg), obs.collector),
        symbols_provider=TracedSymbolProvider(
            SymbolTableProvider(LocalCommandRunner()), obs.collector
        ),
        catalog_fetcher=OpenAIModelsFetcher(),
        turns=SQLiteTurnStore(cfg.db_path),
        notes=SQLiteProjectNoteStore(cfg.db_path),
        token_ledger=_TokenLedger(cfg.db_path),
        trace=obs.collector,
    )
    service.obs = obs
    return service
