"""Anthropic Messages API 原生形态。

把 `anthropic` SDK 的 Messages 请求/响应适配成 openai-agents 的 `Model` 接口。
Runner 的客户端工具循环、并行工具、流式事件映射全部由 SDK 复用——本模块只处理
「协议形状差异」这一个问题。

协议差异要点（2026-09-17 实现时核实）：

- **鉴权**：`x-api-key` 头 + `anthropic-version` 版本头，非 `Authorization: Bearer`；
- **system**：顶层 `system` 字段（字符串或 block 列表），**不是** messages 里的 role；
- **tools**：扁平结构 `{name, description, input_schema}`，非 OpenAI 的
  `{type:"function", function:{...}}` 嵌套；
- **tool_choice**：`{type:"auto"|"any"|"tool", name?}`；
- **max_tokens**：**必填**；
- **停止原因**：`end_turn` / `max_tokens` / `stop_sequence` / `tool_use`；
- **content blocks**：`text` / `tool_use` / `thinking` 等多种类型混在一个数组里。

实现范围说明：**不支持 thinking block 回传**（需额外的 signature 校验），
遇 thinking block 时记录诊断信息后跳过——本项目不依赖推理链回放。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

from agents.items import ModelResponse
from agents.stream_events import RawResponsesStreamEvent
from agents.tool import Tool
from openai import AsyncOpenAI
from openai.types.responses import ResponseOutputMessage, ResponseTextDeltaEvent

from devprompt_ai.domain.model.tuning import anthropic_thinking
from devprompt_ai.harness.adapters.base import BaseNativeModel

#: Anthropic API 版本头（官方要求；缺省会 400）。
_ANTHROPIC_VERSION = "2023-06-01"

#: 本项目实际使用的模型标识上限（防御性截断，防用户误贴整段文本）。
_MAX_MODEL_LEN = 200


class AnthropicNativeModel(BaseNativeModel):
    """Anthropic Messages 原生形态的 Model 实现。"""

    def __init__(
        self, model: str, client: AsyncOpenAI, *, api_key: str = "", base_url: str = ""
    ) -> None:
        super().__init__(model, api_mode="anthropic_messages")
        # client 参数仅用于接口统一（OpenAI 兼容路径需要）；原生路径另建 SDK client
        self._client = client
        self._api_key = api_key
        #: 原生端点；留空则用 SDK 默认（api.anthropic.com）。供应商提供 Anthropic 兼容层时
        #: 必须下传其自身的 base_url，否则请求会打到 Anthropic 官方而失败。
        self._base_url = base_url
        self._native: Any = None  # anthropic.AsyncAnthropic，惰性构造

    # ------------------------------------------------------------------
    # SDK client 惰性构造
    # ------------------------------------------------------------------

    def _ensure_native(self) -> Any:
        if self._native is not None:
            return self._native
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - 依赖未安装
            raise RuntimeError(
                "使用 Anthropic 原生形态需安装依赖：uv add anthropic（或 --extra anthropic）"
            ) from exc
        # kwargs 散装而不是直接**展开：后者让 mypy 无法匹配参数位置（质量不可丢）
        kwargs: dict[str, Any] = {"api_key": self._api_key or "EMPTY"}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._native = anthropic.AsyncAnthropic(**kwargs)
        return self._native

    # ------------------------------------------------------------------
    # 协议转换
    # ------------------------------------------------------------------

    @staticmethod
    def _to_messages(
        system_instructions: str | None, user_input: str | list[Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        """把 agents 的输入转成 Anthropic 的 (system, messages)。

        agents 的 input 可能是 str 或 item 列表；本项目只用 str 与 user message 两种，
        其余形态（工具回传等）由 Runner 在多轮中逐步喂入，此处按 user 消息处理。
        """
        system = system_instructions or ""
        if isinstance(user_input, str):
            return system, [{"role": "user", "content": user_input}]
        messages: list[dict[str, Any]] = []
        for item in user_input:
            raw = getattr(item, "raw_item", item)
            role = str(getattr(raw, "role", "user"))
            content = getattr(raw, "content", "")
            if isinstance(content, list):
                text = "".join(
                    str(getattr(block, "text", "")) for block in content if hasattr(block, "text")
                )
            else:
                text = str(content)
            messages.append({"role": role, "content": text})
        return system, messages or [{"role": "user", "content": ""}]

    @staticmethod
    def _to_tools(tools: list[Tool]) -> list[dict[str, Any]]:
        """agents Tool → Anthropic 扁平 tools 结构。"""
        result: list[dict[str, Any]] = []
        for tool in tools:
            name = getattr(tool, "name", "")
            if not name:
                continue
            schema = getattr(tool, "params_json_schema", None) or {"type": "object"}
            result.append(
                {
                    "name": str(name),
                    "description": str(getattr(tool, "description", "") or ""),
                    "input_schema": schema,
                }
            )
        return result

    def _build_request(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model_settings: Any,
    ) -> dict[str, Any]:
        """组装 Anthropic Messages 请求体。"""
        max_tokens = self._max_tokens(model_settings)
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            request["system"] = system
        if tools:
            request["tools"] = tools
            request["tool_choice"] = {"type": "auto"}
        # 2026-11-10：思考强度映射为 Anthropic 扩展思考预算。
        extra_body = getattr(model_settings, "extra_body", None) or {}
        effort = str(extra_body.get("reasoning_effort", "") or "")
        thinking = anthropic_thinking(effort, max_tokens)
        if thinking is not None:
            request["thinking"] = thinking
        # Anthropic 原生不支持 temperature/top_p 时由 model_spec 的 drop_params 剔除，
        # 此处只透传 model_settings 中确有的值；启用 thinking 时二者必须省略。
        thinking_enabled = isinstance(thinking, dict) and thinking.get("type") == "enabled"
        if not thinking_enabled:
            temperature = getattr(model_settings, "temperature", None)
            if isinstance(temperature, int | float):
                request["temperature"] = float(temperature)
            top_p = getattr(model_settings, "top_p", None)
            if isinstance(top_p, int | float):
                request["top_p"] = float(top_p)
        return request

    @staticmethod
    def _max_tokens(model_settings: Any) -> int:
        value = getattr(model_settings, "max_tokens", None)
        return int(value) if isinstance(value, int) and value > 0 else 4096

    @staticmethod
    def _to_output_items(content_blocks: list[Any]) -> tuple[list[Any], str]:
        """Anthropic content blocks → agents output items + 纯文本。

        返回 `(items, text)`：text 用于 `final_output`，items 用于工具调用回传。

        **故意不包 `MessageOutputItem`**：`ModelResponse.output` 的类型是裸
        `TResponseOutputItem`（dict 或 pydantic 对象），由 Runner 负责包成 RunItem。
        自己包反而会崩——`RunItemBase.agent` 必填且要建 weakref，传 `None` 会
        `TypeError: cannot create weak reference to 'NoneType'`。
        """
        items: list[Any] = []
        texts: list[str] = []
        for block in content_blocks:
            kind = str(getattr(block, "type", ""))
            if kind == "text":
                text = str(getattr(block, "text", ""))
                texts.append(text)
                items.append(
                    cast(
                        "ResponseOutputMessage",
                        {
                            "id": f"msg_{len(items)}",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": text,
                                    "annotations": [],
                                    "logprobs": [],
                                }
                            ],
                        },
                    )
                )
            elif kind == "tool_use":
                items.append(
                    {
                        "type": "function_call",
                        "call_id": str(getattr(block, "id", "")),
                        "name": str(getattr(block, "name", "")),
                        "arguments": json.dumps(getattr(block, "input", {})),
                    }
                )
            # thinking / redacted_thinking：本项目不回传推理链，跳过
        return items, "".join(texts)

    # ------------------------------------------------------------------
    # Model 抽象实现
    # ------------------------------------------------------------------

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: Any,
        tools: list[Tool],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> ModelResponse:
        native = self._ensure_native()
        system, messages = self._to_messages(system_instructions, input)
        request = self._build_request(system, messages, self._to_tools(tools), model_settings)

        response = await native.messages.create(**request)
        items, _text = self._to_output_items(list(getattr(response, "content", [])))
        usage = _usage_from_anthropic(getattr(response, "usage", None))
        return ModelResponse(
            output=items,
            usage=usage,
            response_id=str(getattr(response, "id", "")) or None,
            request_id=None,
        )

    async def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: Any,
        tools: list[Tool],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> AsyncIterator[Any]:
        """流式实现：逐 block 产出 `ResponseTextDeltaEvent`。

        Anthropic 的流式事件是 `content_block_delta` 序列；本项目只需要文本增量，
        工具调用的流式增量由 Runner 的非流式路径处理（max_turns=1 场景下不涉及）。
        """

        native = self._ensure_native()
        system, messages = self._to_messages(system_instructions, input)
        request = self._build_request(system, messages, self._to_tools(tools), model_settings)

        async with native.messages.stream(**request) as stream:
            async for event in stream:
                delta = getattr(event, "delta", None)
                text = getattr(delta, "text", None)
                if not isinstance(text, str) or text == "":
                    continue
                yield RawResponsesStreamEvent(
                    data=ResponseTextDeltaEvent(
                        content_index=0,
                        delta=text,
                        item_id="msg_0",
                        logprobs=[],
                        output_index=0,
                        sequence_number=0,
                        type="response.output_text.delta",
                    )
                )


def _usage_from_anthropic(usage: Any) -> Any:
    """Anthropic usage → agents Usage。"""
    from agents.usage import Usage

    if usage is None:
        return Usage()
    return Usage(
        requests=1,
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "input_tokens", 0) or 0)
        + int(getattr(usage, "output_tokens", 0) or 0),
    )


def build_anthropic_model(
    model: str,
    client: AsyncOpenAI,
    *,
    api_key: str = "",
    base_url: str = "",
    api_mode: str = "",
) -> Any:
    """构造 Anthropic 原生 Model（registry 入口）。"""
    return AnthropicNativeModel(model, client, api_key=api_key, base_url=base_url)


__all__ = ["AnthropicNativeModel", "build_anthropic_model"]
