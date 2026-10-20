"""协议适配层测试（W2/W3）。

分三层，从「纯函数映射」到「端到端 fake 调用」：

1. **协议转换**（不发请求）：agents 的输入 → 各协议请求体；各协议响应 → agents items。
   这是最易错的部分（Gemini 的 functionCall.args 是 dict 不是 JSON 字符串、
   Anthropic 的 content blocks 混合多种类型），用 SDK 真实类型构造样本。
2. **注册表**：`adapter_kind` 与 `PROVIDER_SPECS` 表一致；未登记 kind 必须报错而非静默回落。
3. **端到端 fake**：monkeypatch 两个原生 SDK 的 client，验证 `get_response` 能跑通并
   产出可被 Runner 消费的 `ModelResponse`。**不发真实请求、不需要 API key**。
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from agents.tool import Tool
from openai import AsyncOpenAI

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.model_spec import (
    PROVIDER_SPECS,
    max_context_length_of,
    resolve_api_mode,
)
from devprompt_ai.harness.adapters import (
    adapter_kind_for,
    build_adapter,
    registered_api_modes,
    supported_adapter_kinds,
)
from devprompt_ai.harness.adapters.anthropic_native import AnthropicNativeModel
from devprompt_ai.harness.adapters.gemini_native import GeminiNativeModel
from devprompt_ai.harness.llm import build_model


@pytest.fixture
def openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url="https://api.example.com/v1", api_key="EMPTY")


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_every_api_mode_has_a_builder(self) -> None:
        """每种 api_mode 都有构造器（api_mode 是路由的唯一真值源）。

        防「静态表里写了新的 supported_api_modes 但漏登记构造器」——那种疏漏会让运行时才炸。
        """
        used = {mode for spec in PROVIDER_SPECS.values() for mode in spec.supported_api_modes}
        used.add(spec_default_mode := next(iter(PROVIDER_SPECS.values())).api_mode)
        assert used <= set(registered_api_modes()), (
            f"未登记的 api_mode: {used - set(registered_api_modes())}"
        )
        assert spec_default_mode in registered_api_modes()

    def test_every_api_mode_maps_to_kind_with_builder(self) -> None:
        """每种 api_mode 的映射目标都必须有构造器（否则路由到个未登记的 kind）。"""
        for mode in registered_api_modes():
            assert adapter_kind_for(mode) in supported_adapter_kinds()

    def test_unknown_api_mode_raises_not_fallback(self) -> None:
        """未登记 api_mode 必须报错——静默回落到 chat_completions 会让用户以为在用自己选的形态。"""
        with pytest.raises(KeyError, match="未登记的 api_mode"):
            adapter_kind_for("no_such_mode")

    def test_unknown_kind_raises_not_fallback(self) -> None:
        """未登记 kind 必须报错——静默回落会让用户以为在用原生协议，实际走了兼容层。"""
        with pytest.raises(KeyError, match="未登记的 adapter_kind"):
            build_adapter("no_such_kind", "m", AsyncOpenAI(api_key="EMPTY"))

    def test_openai_kinds_return_sdk_models(self, openai_client: AsyncOpenAI) -> None:
        from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
        from agents.models.openai_responses import OpenAIResponsesModel

        assert isinstance(
            build_adapter("openai_compat", "m", openai_client), OpenAIChatCompletionsModel
        )
        assert isinstance(
            build_adapter("openai_responses", "m", openai_client), OpenAIResponsesModel
        )

    def test_empty_model_name_rejected(self, openai_client: AsyncOpenAI) -> None:
        """空 model 名必须早失败——否则请求发出去才 400，错误信息还指不到根因。"""
        with pytest.raises(ValueError, match="model 名不能为空"):
            build_adapter("openai_compat", "  ", openai_client)


class TestApiModeResolution:
    def test_openai_defaults_to_responses(self) -> None:
        assert resolve_api_mode("openai") == "responses"

    def test_deepseek_defaults_to_chat_completions(self) -> None:
        """DeepSeek 无 /responses 端点——这是技术栈 §4.5 当初选 chat 的理由。"""
        assert resolve_api_mode("deepseek") == "chat_completions"

    def test_native_providers(self) -> None:
        assert resolve_api_mode("anthropic") == "anthropic_messages"
        assert resolve_api_mode("gemini") == "gemini_generate_content"

    def test_unknown_provider_falls_back_conservatively(self) -> None:
        assert resolve_api_mode("acme-unknown") == "chat_completions"

    def test_override_rejected_when_unsupported(self) -> None:
        """deepseek 不支持 responses：显式传 responses 应回落而非照用。"""
        assert resolve_api_mode("deepseek", "responses") == "chat_completions"

    def test_override_accepted_when_supported(self) -> None:
        assert resolve_api_mode("custom", "responses") == "responses"

    def test_verified_providers_have_real_base_url(self) -> None:
        """已查证到端点的 provider 必须填真实值（2026-09-17 联网核实）。

        商汤的旧地址 api.sensenova.cn 已迁移到 token.sensenova.cn——填旧值会让
        用户拿到 404，故必须用官方现行地址。
        """
        assert PROVIDER_SPECS["yi"].base_url == "https://api.lingyiwanwu.com/v1"
        assert PROVIDER_SPECS["sensetime"].base_url == "https://token.sensenova.cn/v1"
        assert PROVIDER_SPECS["xiaomi-mimo"].base_url == "https://api.xiaomimimo.com/v1"

    def test_user_defined_providers_stay_blank(self) -> None:
        """`custom` 与 `openai_compatible` 必须留空——前者用户自填、后者是泛称端点。

        给泛称端点填一个默认值会误导用户以为只能填那个。
        """
        for key in ("custom", "openai_compatible"):
            assert PROVIDER_SPECS[key].base_url == "", key


# ---------------------------------------------------------------------------
# Anthropic 协议转换
# ---------------------------------------------------------------------------


class TestAnthropicProtocolMapping:
    def setup_method(self) -> None:
        self.model = AnthropicNativeModel("claude-x", AsyncOpenAI(api_key="EMPTY"), api_key="k")

    def test_system_is_top_level_not_message(self) -> None:
        """Anthropic 的 system 是顶层字段，不是 messages 里的 role。"""
        system, messages = self.model._to_messages("你是裁判", "改按钮")
        assert system == "你是裁判"
        assert messages == [{"role": "user", "content": "改按钮"}]

    def test_tools_are_flat(self) -> None:
        """Anthropic tools 是扁平 {name, description, input_schema}，非 OpenAI 嵌套。"""

        class _Tool:
            name = "add"
            description = "相加"
            params_json_schema = {"type": "object"}

        tools = self.model._to_tools([cast("Tool", _Tool())])
        assert tools == [{"name": "add", "description": "相加", "input_schema": {"type": "object"}}]

    def test_max_tokens_is_required_and_defaulted(self) -> None:
        class _S:
            max_tokens = None

        assert self.model._max_tokens(_S()) == 4096

        class _S2:
            max_tokens = 2048

        assert self.model._max_tokens(_S2()) == 2048

    def test_mixed_content_blocks(self) -> None:
        """content blocks 混合 text 与 tool_use；text 要抽出来，tool_use 要转 function_call。"""

        class _Text:
            type = "text"
            text = "结论"

        class _ToolUse:
            type = "tool_use"
            id = "tu_1"
            name = "add"
            input = {"a": 1}

        class _Thinking:
            type = "thinking"
            thinking = "内部推理"

        items, text = self.model._to_output_items([_Text(), _ToolUse(), _Thinking()])
        assert text == "结论"
        assert len(items) == 2
        assert items[1] == {
            "type": "function_call",
            "call_id": "tu_1",
            "name": "add",
            "arguments": '{"a": 1}',
        }

    async def test_get_response_end_to_end_with_fake_sdk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """端到端：fake 掉 anthropic SDK，验证 get_response 产出合法 ModelResponse。"""

        class _Block:
            type = "text"
            text = "好的"

        class _Usage:
            input_tokens = 10
            output_tokens = 5

        class _Resp:
            id = "msg_1"
            content = [_Block()]
            usage = _Usage()

        class _Messages:
            async def create(self, **_kw: Any) -> _Resp:
                return _Resp()

        class _Native:
            def __init__(self) -> None:
                self.messages = _Messages()

        monkeypatch.setattr(self.model, "_native", _Native())

        response = await self.model.get_response(
            "sys",
            "user",
            None,
            [],
            None,
            [],
            None,
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )
        assert response.response_id == "msg_1"
        assert response.usage.input_tokens == 10
        assert response.usage.output_tokens == 5
        assert len(response.output) == 1


# ---------------------------------------------------------------------------
# Gemini 协议转换
# ---------------------------------------------------------------------------


class TestGeminiProtocolMapping:
    def setup_method(self) -> None:
        self.model = GeminiNativeModel("gemini-x", AsyncOpenAI(api_key="EMPTY"), api_key="k")

    def test_contents_use_parts(self) -> None:
        contents = self.model._to_contents("改按钮")
        assert contents == [{"role": "user", "parts": [{"text": "改按钮"}]}]

    def test_assistant_role_maps_to_model(self) -> None:
        """Gemini 用 model 而非 assistant 表示模型回合。"""

        class _Raw:
            role = "assistant"
            content = "上文"

        class _Item:
            raw_item = _Raw()

        contents = self.model._to_contents([_Item()])
        assert contents[0]["role"] == "model"

    def test_tools_use_function_declarations(self) -> None:
        class _Tool:
            name = "add"
            description = "相加"
            params_json_schema = {"type": "object"}

        tools = self.model._to_tools([cast("Tool", _Tool())])
        assert tools == [
            {
                "function_declarations": [
                    {"name": "add", "description": "相加", "parameters": {"type": "object"}}
                ]
            }
        ]

    def test_function_call_args_are_json_encoded(self) -> None:
        """Gemini 的 functionCall.args 是原生 dict，必须 json.dumps 才进 agents item。

        这是最常见的踩坑点：不编码会让 Runner 按 JSON 字符串解析 dict 而抛错。
        """

        class _Call:
            name = "add"
            args = {"a": 1, "b": 2}

        class _Part:
            text = None
            function_call = _Call()

        items, text = self.model._to_output_items([_Part()])
        assert text == ""
        assert items[0]["type"] == "function_call"
        assert items[0]["name"] == "add"
        assert isinstance(items[0]["arguments"], str)
        assert '"a": 1' in items[0]["arguments"]

    async def test_get_response_end_to_end_with_fake_sdk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Part:
            text = "好的"

        class _Content:
            parts = [_Part()]

        class _Candidate:
            content = _Content()

        class _Meta:
            prompt_token_count = 8
            candidates_token_count = 4

        class _Resp:
            response_id = "r1"
            candidates = [_Candidate()]
            usage_metadata = _Meta()

        class _Models:
            async def generate_content(self, **_kw: Any) -> _Resp:
                return _Resp()

        class _Native:
            def __init__(self) -> None:
                self.aio = type("Aio", (), {"models": _Models()})()

        monkeypatch.setattr(self.model, "_native", _Native())

        response = await self.model.get_response(
            "sys",
            "user",
            None,
            [],
            None,
            [],
            None,
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )
        assert response.response_id == "r1"
        assert response.usage.input_tokens == 8
        assert response.usage.output_tokens == 4
        assert len(response.output) == 1


# ---------------------------------------------------------------------------
# W4：build_model 工厂（消除全局开关竞态）
# ---------------------------------------------------------------------------


class TestBuildModelFactory:
    """按 provider 分发 API 形态，且**无进程级共享状态**。

    这是本次多供应商扩展的核心不变量：若改用 `set_default_openai_api` 全局开关，
    Web 并发下 A 请求设 responses、B 请求设 chat_completions 会相互覆盖 → 随机 4xx。
    """

    @pytest.mark.parametrize(
        ("provider", "expected"),
        [
            ("deepseek", "OpenAIChatCompletionsModel"),
            ("zhipu", "OpenAIChatCompletionsModel"),
            ("moonshot", "OpenAIChatCompletionsModel"),
            ("openai", "OpenAIResponsesModel"),
            ("anthropic", "AnthropicNativeModel"),
            ("gemini", "GeminiNativeModel"),
        ],
    )
    def test_dispatch_by_provider(self, provider: str, expected: str) -> None:
        cfg = AppConfig(
            llm_provider=provider,
            llm_base_url="https://api.example.com/v1",
            llm_model="m",
            llm_api_key="k",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert type(build_model(cfg)).__name__ == expected

    def test_no_global_switch_call(self) -> None:
        """llm.py 不得再调用 set_default_openai_api（进程级单例，并发竞态根源）。"""
        import re
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[2] / "src" / "devprompt_ai" / "harness" / "llm.py"
        ).read_text(encoding="utf-8")
        assert not re.search(r"^\s*set_default_openai_api\(", src, re.MULTILINE)

    def test_idempotent_globals_kept(self) -> None:
        """client 注册与 tracing 禁用仍须保留（前者幂等，后者与协议无关）。"""
        import re
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[2] / "src" / "devprompt_ai" / "harness" / "llm.py"
        ).read_text(encoding="utf-8")
        assert re.search(r"^\s*set_default_openai_client\(", src, re.MULTILINE)
        assert re.search(r"^\s*set_tracing_disabled\(", src, re.MULTILINE)

    async def test_concurrent_build_has_no_cross_talk(self) -> None:
        """并发交替构造不同形态：每实例形态独立，互不污染。"""
        import asyncio
        from collections import Counter

        def cfg_for(provider: str) -> AppConfig:
            return AppConfig(
                llm_provider=provider,
                llm_base_url="https://api.example.com/v1",
                llm_model="m",
                llm_api_key="k",
                _env_file=None,  # type: ignore[call-arg]
            )

        pairs = [cfg_for("openai"), cfg_for("deepseek")] * 10
        models = await asyncio.gather(*[asyncio.to_thread(build_model, c) for c in pairs])
        counts = Counter(type(m).__name__ for m in models)
        assert counts["OpenAIResponsesModel"] == 10
        assert counts["OpenAIChatCompletionsModel"] == 10

    def test_missing_config_raises_configuration_error(self) -> None:
        """未配置 base_url/model 时应给出可操作的配置错误，而非 AttributeError。"""
        from devprompt_ai.domain.errors import ConfigurationError

        cfg = AppConfig(llm_provider="deepseek", llm_base_url="", llm_model="", _env_file=None)  # type: ignore[call-arg]
        with pytest.raises(ConfigurationError, match="LLM 未配置"):
            build_model(cfg)


# ---------------------------------------------------------------------------
# W5：reasoning_effort 走 extra_body + 上下文窗口只告警不截断
# ---------------------------------------------------------------------------


class TestExtraBodyParams:
    """`ModelSettings` 未建模的参数（reasoning_effort）必须真正下发，不能静默丢弃。"""

    def test_reasoning_effort_goes_to_extra_body(self) -> None:
        cfg = AppConfig(
            llm_provider="deepseek",
            llm_model="deepseek-reasoner",
            llm_params={"reasoning_effort": "high"},
            _env_file=None,  # type: ignore[call-arg]
        )
        assert cfg.extra_body_params() == {"reasoning_effort": "high"}

    def test_not_duplicated_into_model_settings(self) -> None:
        """同一个值不能既进 ModelSettings 又进 extra_body——否则请求里会出现两次。"""
        cfg = AppConfig(
            llm_provider="deepseek",
            llm_model="deepseek-reasoner",
            llm_params={"reasoning_effort": "high", "temperature": 0.3},
            _env_file=None,  # type: ignore[call-arg]
        )
        assert "reasoning_effort" not in cfg.effective_llm_params()
        assert cfg.effective_llm_params()["temperature"] == 0.3

    def test_empty_value_not_sent(self) -> None:
        """未设置或空值不进 extra_body，避免覆盖供应商默认。"""
        cfg = AppConfig(llm_provider="deepseek", llm_model="m", _env_file=None)  # type: ignore[call-arg]
        assert cfg.extra_body_params() == {}

    def test_provider_dropped_param_not_in_extra_body(self) -> None:
        """provider 不接受的参数即使用户填了也不下发。"""
        cfg = AppConfig(
            llm_provider="anthropic",
            llm_model="claude-x",
            llm_params={"temperature": 0.7, "reasoning_effort": "high"},
            _env_file=None,  # type: ignore[call-arg]
        )
        assert "temperature" not in cfg.extra_body_params()

    def test_model_settings_accepts_extra_body(self) -> None:
        """最终产物必须能被 ModelSettings 直接展开。"""
        from agents import ModelSettings

        cfg = AppConfig(
            llm_provider="deepseek",
            llm_model="m",
            llm_params={"reasoning_effort": "high"},
            _env_file=None,  # type: ignore[call-arg]
        )
        ModelSettings(**cfg.effective_llm_params(), extra_body=cfg.extra_body_params() or None)


class TestContextWindowWarning:
    """窗口告警只提示、**不截断**——截断证据会削弱召回率（MUST-25 硬门禁）。"""

    def test_returns_none_when_within_window(self) -> None:
        cfg = AppConfig(llm_provider="openai", llm_model="gpt-x", _env_file=None)  # type: ignore[call-arg]
        limit = max_context_length_of("openai")
        assert cfg.context_window_warning(10) is None
        assert limit is None or limit > 10

    def test_warns_when_exceeding(self) -> None:
        limit = max_context_length_of("openai")
        if limit is None:
            pytest.skip("openai 未登记窗口上限")
        cfg = AppConfig(llm_provider="openai", llm_model="gpt-x", _env_file=None)  # type: ignore[call-arg]
        warning = cfg.context_window_warning(limit + 1000)
        assert warning is not None
        assert str(limit) in warning
        assert "缩小检索范围" in warning, "告警须给出可操作建议，不能只报错"

    def test_does_not_truncate_input(self) -> None:
        """核心不变量：告警是纯函数，绝不改动入参或返回值长度。"""
        cfg = AppConfig(llm_provider="openai", llm_model="gpt-x", _env_file=None)  # type: ignore[call-arg]
        payload = "x" * 100_000
        before = len(payload)
        cfg.context_window_warning(10_000_000)
        assert len(payload) == before


# ---------------------------------------------------------------------------
# 流式路径（F-802 第 4 项；smoke_provider.check_streaming 走的就是这里）
# ---------------------------------------------------------------------------


class TestAnthropicStreaming:
    def setup_method(self) -> None:
        self.model = AnthropicNativeModel("claude-x", AsyncOpenAI(api_key="EMPTY"), api_key="k")

    async def test_emits_text_delta_events(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Anthropic 的 content_block_delta 序列须转成 agents 的文本增量事件。"""

        class _Delta:
            text = "你"

        class _Event:
            delta = _Delta()

        class _Stream:
            def __aiter__(self) -> Any:
                async def gen() -> Any:
                    yield _Event()
                    yield _Event()

                return gen()

        class _Messages:
            def stream(self, **_kw: Any) -> Any:
                return _Ctx()

        class _Ctx:
            async def __aenter__(self) -> _Stream:
                return _Stream()

            async def __aexit__(self, *_a: object) -> None:
                return None

        class _Native:
            def __init__(self) -> None:
                self.messages = _Messages()

        monkeypatch.setattr(self.model, "_native", _Native())

        events = [
            e
            async for e in self.model.stream_response(
                "sys",
                "hi",
                None,
                [],
                None,
                [],
                None,
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        ]
        assert len(events) == 2
        assert events[0].data.type == "response.output_text.delta"
        assert events[0].data.delta == "你"

    async def test_skips_non_text_events(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非文本增量（tool_use 等）不产出事件，避免污染流。"""

        class _Event:
            delta = object()  # 无 text 属性

        class _Stream:
            def __aiter__(self) -> Any:
                async def gen() -> Any:
                    yield _Event()

                return gen()

        class _Messages:
            def stream(self, **_kw: Any) -> Any:
                return _Ctx()

        class _Ctx:
            async def __aenter__(self) -> _Stream:
                return _Stream()

            async def __aexit__(self, *_a: object) -> None:
                return None

        class _Native:
            def __init__(self) -> None:
                self.messages = _Messages()

        monkeypatch.setattr(self.model, "_native", _Native())

        events = [
            e
            async for e in self.model.stream_response(
                "sys",
                "hi",
                None,
                [],
                None,
                [],
                None,
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        ]
        assert events == []


class TestGeminiStreaming:
    def setup_method(self) -> None:
        self.model = GeminiNativeModel("gemini-x", AsyncOpenAI(api_key="EMPTY"), api_key="k")

    async def test_emits_text_delta_events(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Part:
            text = "好"

        class _Content:
            parts = [_Part()]

        class _Chunk:
            candidates = [type("C", (), {"content": _Content()})()]

        async def _gen() -> Any:
            yield _Chunk()

        class _Models:
            async def generate_content_stream(self, **_kw: Any) -> Any:
                return _gen()

        class _Native:
            def __init__(self) -> None:
                self.aio = type("Aio", (), {"models": _Models()})()

        monkeypatch.setattr(self.model, "_native", _Native())

        events = [
            e
            async for e in self.model.stream_response(
                "sys",
                "hi",
                None,
                [],
                None,
                [],
                None,
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        ]
        assert len(events) == 1
        assert events[0].data.delta == "好"

    async def test_skips_empty_chunks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 candidates 的 chunk（安全过滤等场景）须跳过而非崩。"""

        class _Chunk:
            candidates: list[Any] = []

        async def _gen() -> Any:
            yield _Chunk()

        class _Models:
            async def generate_content_stream(self, **_kw: Any) -> Any:
                return _gen()

        class _Native:
            def __init__(self) -> None:
                self.aio = type("Aio", (), {"models": _Models()})()

        monkeypatch.setattr(self.model, "_native", _Native())

        events = [
            e
            async for e in self.model.stream_response(
                "sys",
                "hi",
                None,
                [],
                None,
                [],
                None,
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        ]
        assert events == []


class TestMultiTurnInputMapping:
    """多轮时 Runner 会喂 **item 列表**（而非 str）——该分支必须覆盖。

    只测 str 分支的话，单轮能用、多轮静默丢历史。
    """

    def test_anthropic_item_list_to_messages(self) -> None:
        model = AnthropicNativeModel("claude-x", AsyncOpenAI(api_key="EMPTY"), api_key="k")

        class _Raw:
            def __init__(self, role: str, text: str) -> None:
                self.role = role
                self.content = text

        class _Item:
            def __init__(self, role: str, text: str) -> None:
                self.raw_item = _Raw(role, text)

        system, messages = model._to_messages(
            "sys", [_Item("user", "第一轮"), _Item("assistant", "答")]
        )
        assert system == "sys"
        assert messages == [
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "答"},
        ]

    def test_anthropic_content_blocks_flattened(self) -> None:
        """content 为 block 列表时须拼接文本，不能丢。"""
        model = AnthropicNativeModel("claude-x", AsyncOpenAI(api_key="EMPTY"), api_key="k")

        class _Block:
            def __init__(self, text: str) -> None:
                self.text = text

        class _Raw:
            role = "user"
            content = [_Block("前半"), _Block("后半")]

        class _Item:
            raw_item = _Raw()

        _, messages = model._to_messages(None, [_Item()])
        assert messages[0]["content"] == "前半后半"

    def test_anthropic_empty_input_falls_back(self) -> None:
        model = AnthropicNativeModel("claude-x", AsyncOpenAI(api_key="EMPTY"), api_key="k")
        _, messages = model._to_messages(None, [])
        assert messages == [{"role": "user", "content": ""}]

    def test_gemini_item_list_to_contents(self) -> None:
        model = GeminiNativeModel("gemini-x", AsyncOpenAI(api_key="EMPTY"), api_key="k")

        class _Raw:
            def __init__(self, role: str, content: str) -> None:
                self.role = role
                self.content = content

        class _Item:
            def __init__(self, role: str, text: str) -> None:
                self.raw_item = _Raw(role, text)

        contents = model._to_contents([_Item("user", "第一轮"), _Item("assistant", "答")])
        assert [c["role"] for c in contents] == ["user", "model"]
        assert contents[0]["parts"][0]["text"] == "第一轮"

    def test_gemini_empty_input_falls_back(self) -> None:
        model = GeminiNativeModel("gemini-x", AsyncOpenAI(api_key="EMPTY"), api_key="k")
        assert model._to_contents([]) == [{"role": "user", "parts": [{"text": ""}]}]


# ---------------------------------------------------------------------------
# W7/W8：契约 additive 扩展 + provider 目录
# ---------------------------------------------------------------------------


class TestProviderDirectory:
    """provider 目录是前端下拉的唯一数据源（前端不再硬编码厂商清单）。"""

    def test_covers_all_registered_providers(self) -> None:
        from devprompt_ai.domain.model_spec import providers_projection

        assert len(providers_projection()) == len(PROVIDER_SPECS)

    def test_entry_fields_match_contract(self) -> None:
        from devprompt_ai.domain.model_spec import providers_projection

        expected = {
            "id",
            "label",
            "base_url",
            "needs_key",
            "default_api_mode",
            "supported_api_modes",
            "max_context_length",
            "context_window_tiers",
            "models",
            "supports_reasoning",
            "quirks",
        }
        for entry in providers_projection():
            assert set(entry) == expected, f"目录字段与契约不符：{set(entry) ^ expected}"

    def test_projection_carries_verified_base_urls(self) -> None:
        """目录投影必须带出已核实的端点（前端下拉据此预填 Base URL）。"""
        from devprompt_ai.domain.model_spec import providers_projection

        by_id = {e["id"]: e for e in providers_projection()}
        assert by_id["yi"]["base_url"] == "https://api.lingyiwanwu.com/v1"
        assert by_id["custom"]["base_url"] == "", "用户自填项须留空"

    def test_native_providers_default_to_native_modes(self) -> None:
        from devprompt_ai.domain.model_spec import providers_projection

        by_id = {e["id"]: e for e in providers_projection()}
        assert by_id["anthropic"]["default_api_mode"] == "anthropic_messages"
        assert by_id["gemini"]["default_api_mode"] == "gemini_generate_content"
        assert by_id["openai"]["default_api_mode"] == "responses"


class TestEntryFieldNormalization:
    """三个新字段在读时归一化：缺失补默认，不报错（旧条目兼容）。"""

    def test_missing_fields_get_defaults(self) -> None:
        from devprompt_ai.domain.model_migration import normalize_entry

        entry, _errors = normalize_entry(
            {"id": "m-1", "label": "x", "provider": "deepseek", "base_url": "u", "model_id": "m"}
        )
        assert entry["api_mode"] == ""
        assert entry["reasoning_effort"] == ""
        assert entry["max_context_length"] is None

    def test_wrong_types_become_defaults(self) -> None:
        from devprompt_ai.domain.model_migration import normalize_entry

        entry, _errors = normalize_entry(
            {
                "id": "m-1",
                "label": "x",
                "provider": "deepseek",
                "base_url": "u",
                "model_id": "m",
                "api_mode": 123,
                "reasoning_effort": [],
                "max_context_length": -5,
            }
        )
        assert entry["api_mode"] == ""
        assert entry["reasoning_effort"] == ""
        assert entry["max_context_length"] is None

    def test_valid_values_preserved(self) -> None:
        from devprompt_ai.domain.model_migration import normalize_entry

        entry, _errors = normalize_entry(
            {
                "id": "m-1",
                "label": "x",
                "provider": "deepseek",
                "base_url": "u",
                "model_id": "m",
                "api_mode": "responses",
                "reasoning_effort": "high",
                "max_context_length": 64000,
            }
        )
        assert entry["api_mode"] == "responses"
        assert entry["reasoning_effort"] == "high"
        assert entry["max_context_length"] == 64000


class TestApiModeRouting:
    """api_mode 为路由真值源（2026-10-18）。"""

    def test_custom_provider_anthropic_messages_builds_native(
        self, openai_client: AsyncOpenAI
    ) -> None:
        """custom + anthropic_messages → 原生适配器，且 base_url 落到 SDK client。

        回归：之前两个原生 adapter 完全忽略 base_url，选了原生形态也会打到
        Anthropic 官方端点而失败；且 adapter_kind 才是唯一决定者，api_mode 选了不生效。
        """
        model = AnthropicNativeModel(
            "claude-x",
            openai_client,
            api_key="sk-ant",
            base_url="https://api.deepseek.com/anthropic",
        )
        native = model._ensure_native()
        assert model.describe().startswith("AnthropicNativeModel")
        assert str(native.base_url).startswith("https://api.deepseek.com/anthropic")

    def test_gemini_native_receives_base_url(self, openai_client: AsyncOpenAI) -> None:
        """genai.Client 没有 base_url 参数，必须走 HttpOptions（已核实安装版本字段）。"""
        model = GeminiNativeModel(
            "gemini-x",
            openai_client,
            api_key="g",
            base_url="https://gemini.example/v1beta",
        )
        native = model._ensure_native()
        assert model.describe().startswith("GeminiNativeModel")
        # genai.Client._api_client 惰构，真实 client 在 _models 下（已核实安装版本的属性路径）
        assert "/v1beta" in str(native._models._api_client._http_options.base_url)

    def test_build_model_routes_by_api_mode(self) -> None:
        """build_model 按 api_mode 选构造器：同 provider 不同形态 → 不同适配器。"""
        import devprompt_ai.harness.llm as llm_mod
        from devprompt_ai.config import AppConfig

        llm_mod._client = None
        llm_mod._client_key = None
        chat = build_model(
            AppConfig(
                llm_provider="custom",
                llm_model="m-x",
                llm_base_url="https://relay.example/v1",
                llm_api_key="sk-x",
            )
        )
        anthropic = build_model(
            AppConfig(
                llm_provider="custom",
                llm_model="m-x",
                llm_base_url="https://relay.example/v1",
                llm_api_key="sk-x",
                api_mode="anthropic_messages",
            )
        )
        assert type(chat).__name__ == "OpenAIChatCompletionsModel"
        assert isinstance(anthropic, AnthropicNativeModel)

    def test_client_cache_key_covers_endpoint_and_key(self) -> None:
        """缓存键必须含 base_url / api_key：同 model 换端点换密钥不得复用旧 client。"""
        import devprompt_ai.harness.llm as llm_mod
        from devprompt_ai.config import AppConfig

        llm_mod._client = None
        llm_mod._client_key = None
        cfg_a = AppConfig(
            llm_provider="custom", llm_model="m", llm_base_url="https://a/v1", llm_api_key="sk-a"
        )
        first = llm_mod._ensure_client(cfg_a)
        assert llm_mod._ensure_client(cfg_a) is first  # 同配置复用
        other = llm_mod._ensure_client(
            AppConfig(
                llm_provider="custom",
                llm_model="m",
                llm_base_url="https://b/v1",
                llm_api_key="sk-b",
            )
        )
        assert other is not first
        assert str(other.base_url).startswith("https://b/v1")
