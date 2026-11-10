"""Google Gemini GenerateContent 原生形态。

把 `google-genai` SDK 的 GenerateContent 请求/响应适配成 openai-agents 的 `Model`
接口。与 Anthropic 版同理：Runner 的工具循环与流式映射全部复用，本模块只处理协议差异。

协议差异要点（2026-09-17 实现时核实）：

- **鉴权**：`x-goog-api-key` 头（`google-genai` 封装为 `api_key=` 构造参数）；
- **system**：顶层 `system_instruction` 字段，不是 contents 里的 role；
- **contents**：`[{role: "user"|"model", parts: [{text: ...}]}]`；
- **tools**：`[{function_declarations: [{name, description, parameters}]}]`；
- **tool_config**：`{function_calling_config: {mode: "AUTO"}}`；
- **响应**：`candidates[0].content.parts[]`，part 类型含 `text` / `functionCall`；
- **usage**：`usage_metadata.prompt_token_count` / `candidates_token_count`。

实现范围说明：Gemini 的 `functionCall` 参数是**原生 dict**（非 JSON 字符串），
转成 agents 的 `function_call` item 时须 `json.dumps`——这是最常见的踩坑点。
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

from devprompt_ai.domain.model.tuning import gemini_thinking_budget
from devprompt_ai.harness.adapters.base import BaseNativeModel


class GeminiNativeModel(BaseNativeModel):
    """Gemini GenerateContent 原生形态的 Model 实现。"""

    def __init__(
        self, model: str, client: AsyncOpenAI, *, api_key: str = "", base_url: str = ""
    ) -> None:
        super().__init__(model, api_mode="gemini_generate_content")
        self._client = client  # 仅为接口统一；原生路径另建 SDK client
        self._api_key = api_key
        #: 原生端点；留空则用 SDK 默认。`genai.Client` 没有 base_url 参数，
        #: 必须走 `http_options=HttpOptions(base_url=...)`（已核实安装版本的字段）。
        self._base_url = base_url
        self._native: Any = None  # google.genai.Client，惰性构造

    def _ensure_native(self) -> Any:
        if self._native is not None:
            return self._native
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - 依赖未安装
            raise RuntimeError(
                "使用 Gemini 原生形态需安装依赖：uv add google-genai（或 --extra gemini）"
            ) from exc
        # kwargs 散装而不是直接 **展开：后者让 mypy 无法匹配参数位置（质量不可丢）
        kwargs: dict[str, Any] = {"api_key": self._api_key or "EMPTY"}
        if self._base_url:
            kwargs["http_options"] = types.HttpOptions(base_url=self._base_url)
        self._native = genai.Client(**kwargs)
        return self._native

    # ------------------------------------------------------------------
    # 协议转换
    # ------------------------------------------------------------------

    @staticmethod
    def _to_contents(user_input: str | list[Any]) -> list[dict[str, Any]]:
        """agents input → Gemini contents。"""
        if isinstance(user_input, str):
            return [{"role": "user", "parts": [{"text": user_input}]}]
        contents: list[dict[str, Any]] = []
        for item in user_input:
            raw = getattr(item, "raw_item", item)
            role = "model" if str(getattr(raw, "role", "user")) == "assistant" else "user"
            content = getattr(raw, "content", "")
            if isinstance(content, list):
                text = "".join(str(getattr(b, "text", "")) for b in content if hasattr(b, "text"))
            else:
                text = str(content)
            contents.append({"role": role, "parts": [{"text": text}]})
        return contents or [{"role": "user", "parts": [{"text": ""}]}]

    @staticmethod
    def _to_tools(tools: list[Tool]) -> list[dict[str, Any]]:
        """agents Tool → Gemini function_declarations。"""
        declarations: list[dict[str, Any]] = []
        for tool in tools:
            name = getattr(tool, "name", "")
            if not name:
                continue
            schema = getattr(tool, "params_json_schema", None) or {"type": "object"}
            declarations.append(
                {
                    "name": str(name),
                    "description": str(getattr(tool, "description", "") or ""),
                    "parameters": schema,
                }
            )
        return [{"function_declarations": declarations}] if declarations else []

    def _build_config(
        self,
        system: str,
        tools: list[dict[str, Any]],
        model_settings: Any,
    ) -> Any:
        """组装 Gemini GenerateContentConfig。"""
        from google.genai import types

        config_kwargs: dict[str, Any] = {}
        if system:
            config_kwargs["system_instruction"] = system
        if tools:
            config_kwargs["tools"] = tools
            config_kwargs["tool_config"] = {"function_calling_config": {"mode": "AUTO"}}
        temperature = getattr(model_settings, "temperature", None)
        if isinstance(temperature, int | float):
            config_kwargs["temperature"] = float(temperature)
        top_p = getattr(model_settings, "top_p", None)
        if isinstance(top_p, int | float):
            config_kwargs["top_p"] = float(top_p)
        max_tokens = getattr(model_settings, "max_tokens", None)
        if isinstance(max_tokens, int) and max_tokens > 0:
            config_kwargs["max_output_tokens"] = int(max_tokens)
        # 2026-11-10：思考强度映射为 Gemini thinking budget。
        extra_body = getattr(model_settings, "extra_body", None) or {}
        effort = str(extra_body.get("reasoning_effort", "") or "")
        budget = gemini_thinking_budget(effort)
        thinking_cls = getattr(types, "ThinkingConfig", None)
        if budget is not None and thinking_cls is not None:
            config_kwargs["thinking_config"] = thinking_cls(
                thinking_budget=budget,
                include_thoughts=False,
            )
        return types.GenerateContentConfig(**config_kwargs)

    @staticmethod
    def _to_output_items(parts: list[Any]) -> tuple[list[Any], str]:
        """Gemini parts → agents output items + 纯文本。

        `functionCall.args` 是原生 dict，须 `json.dumps` 才能进 agents 的
        `function_call` item（该字段约定为 JSON 字符串）。
        """
        items: list[Any] = []
        texts: list[str] = []
        for part in parts:
            text = getattr(part, "text", None)
            if isinstance(text, str) and text:
                texts.append(text)
                # 不包 MessageOutputItem：output 是裸 item，由 Runner 包装
                # （RunItemBase.agent 必填且要 weakref，传 None 会 TypeError）
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
                continue
            call = getattr(part, "function_call", None)
            if call is not None:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": f"call_{len(items)}",
                        "name": str(getattr(call, "name", "")),
                        "arguments": json.dumps(getattr(call, "args", {}) or {}),
                    }
                )
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
        contents = self._to_contents(input)
        config = self._build_config(
            system_instructions or "", self._to_tools(tools), model_settings
        )

        response = await native.aio.models.generate_content(
            model=self._model, contents=contents, config=config
        )
        candidates = list(getattr(response, "candidates", []) or [])
        parts: list[Any] = []
        if candidates:
            content = getattr(candidates[0], "content", None)
            parts = list(getattr(content, "parts", []) or [])
        items, _text = self._to_output_items(parts)
        return ModelResponse(
            output=items,
            usage=_usage_from_gemini(getattr(response, "usage_metadata", None)),
            response_id=str(getattr(response, "response_id", "")) or None,
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
        """流式实现：逐 chunk 产出文本增量。"""
        native = self._ensure_native()
        contents = self._to_contents(input)
        config = self._build_config(
            system_instructions or "", self._to_tools(tools), model_settings
        )

        async for chunk in await native.aio.models.generate_content_stream(
            model=self._model, contents=contents, config=config
        ):
            candidates = list(getattr(chunk, "candidates", []) or [])
            if not candidates:
                continue
            content = getattr(candidates[0], "content", None)
            for part in list(getattr(content, "parts", []) or []):
                text = getattr(part, "text", None)
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


def _usage_from_gemini(metadata: Any) -> Any:
    """Gemini usage_metadata → agents Usage。"""
    from agents.usage import Usage

    if metadata is None:
        return Usage()
    prompt_tokens = int(getattr(metadata, "prompt_token_count", 0) or 0)
    candidates_tokens = int(getattr(metadata, "candidates_token_count", 0) or 0)
    return Usage(
        requests=1,
        input_tokens=prompt_tokens,
        output_tokens=candidates_tokens,
        total_tokens=prompt_tokens + candidates_tokens,
    )


def build_gemini_model(
    model: str,
    client: AsyncOpenAI,
    *,
    api_key: str = "",
    base_url: str = "",
    api_mode: str = "",
) -> Any:
    """构造 Gemini 原生 Model（registry 入口）。"""
    return GeminiNativeModel(model, client, api_key=api_key, base_url=base_url)


__all__ = ["GeminiNativeModel", "build_gemini_model"]
