"""模型目录拉取客户端测试（**全部离线**：假客户端替换 SDK，不联网）。

覆盖：① 字段解析（含 DeepSeek 官方文档确认的扩展字段）；② 畸形响应不崩；
③ 异常归一化出可展示的中文原因，且**不含 api_key**（MUST-19）。
"""

from __future__ import annotations

from typing import Any

import httpx
import openai
import pytest

from devprompt_ai.domain.errors import CatalogFetchError
from devprompt_ai.harness import models_client as mc
from devprompt_ai.harness.models_client import (
    OpenAIModelsFetcher,
    parse_model_entry,
    parse_models_response,
)

#: DeepSeek《Lists Models》官方文档给出的真实示例对象
_DEEPSEEK_SAMPLE: dict[str, Any] = {
    "id": "deepseek-flash",
    "object": "model",
    "owned_by": "deepseek",
    "name": "DeepSeek-V4.1-Flash",
    "context_window": 1048576,
    "max_output_tokens": 393216,
    "input_modalities": ["text", "image"],
    "output_modalities": ["text"],
    "effort": {"supported_levels": ["low", "high", "max"], "default_level": "high"},
}

_SECRET = "sk-secret-value-should-never-appear"


class _FakeModels:
    def __init__(self, payload: dict[str, Any] | None, exc: Exception | None) -> None:
        self._payload = payload
        self._exc = exc

    async def list(self) -> Any:
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._payload or {})


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """替身：只实现本模块用到的那两个成员。"""

    closed = False

    def __init__(self, *, payload: dict[str, Any] | None, exc: Exception | None, **_kw: Any):
        self.models = _FakeModels(payload, exc)

    async def close(self) -> None:
        type(self).closed = True


def _stub_client(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any] | None, exc: Exception | None
) -> None:
    monkeypatch.setattr(mc, "AsyncOpenAI", lambda **kw: _FakeClient(payload=payload, exc=exc, **kw))


def _status_error(exc_cls: type[Exception], status: int) -> Exception:
    """构造带 HTTP 响应上下文的 SDK 异常（SDK 要求 status_code 存在）。"""
    request = httpx.Request("GET", "https://api.example.com/v1/models")
    return exc_cls("boom", response=httpx.Response(status, request=request), body=None)


class TestParseModelEntry:
    def test_parses_deepseek_official_shape(self) -> None:
        info = parse_model_entry(_DEEPSEEK_SAMPLE)
        assert info is not None
        assert info.model_id == "deepseek-flash"
        assert info.display_name == "DeepSeek-V4.1-Flash"
        assert info.max_context_length == 1_048_576
        assert info.reasoning_efforts == ("low", "high", "max")

    def test_standard_entry_without_extensions(self) -> None:
        """绝大多数 OpenAI 兼容端点只给 id —— 其余字段留空，交给静态表兜底。"""
        info = parse_model_entry({"id": "gpt-x"})
        assert info is not None
        assert info.max_context_length is None
        assert info.context_window_tiers == ()
        assert info.reasoning_efforts == ()
        assert info.display_name == ""

    def test_missing_id_is_rejected(self) -> None:
        assert parse_model_entry({"name": "无 id"}) is None
        assert parse_model_entry({"id": "   "}) is None
        assert parse_model_entry(None) is None

    def test_non_positive_window_ignored(self) -> None:
        assert parse_model_entry({"id": "m", "context_window": 0}).max_context_length is None
        assert parse_model_entry({"id": "m", "context_window": True}).max_context_length is None

    def test_string_window_accepted(self) -> None:
        info = parse_model_entry({"id": "m", "context_window": "131072"})
        assert info is not None and info.max_context_length == 131072

    def test_malformed_effort_ignored(self) -> None:
        info = parse_model_entry({"id": "m", "effort": "low"})
        assert info is not None and info.reasoning_efforts == ()

    def test_no_tiers_invented(self) -> None:
        """DeepSeek 不提供窗口档位字段 —— 解析器不得凭空造档位。"""
        info = parse_model_entry(_DEEPSEEK_SAMPLE)
        assert info is not None and info.context_window_tiers == ()

    def test_sdk_object_is_parsed(self) -> None:
        """真实 SDK 返回 pydantic 对象（含 extra 字段），也要能解析。"""

        class _Model:
            def model_dump(self) -> dict[str, Any]:
                return dict(_DEEPSEEK_SAMPLE)

        info = parse_model_entry(_Model())
        assert info is not None and info.max_context_length == 1_048_576


class TestParseModelsResponse:
    def test_parses_list(self) -> None:
        models = parse_models_response({"data": [_DEEPSEEK_SAMPLE, {"id": "deepseek-v4-pro"}]})
        assert [m.model_id for m in models] == ["deepseek-flash", "deepseek-v4-pro"]

    def test_malformed_payloads_yield_empty(self) -> None:
        for payload in (None, [], {"data": None}, {"data": {}}, "text"):
            assert parse_models_response(payload) == []

    def test_invalid_entries_skipped(self) -> None:
        models = parse_models_response({"data": [{"name": "no id"}, _DEEPSEEK_SAMPLE]})
        assert len(models) == 1


class TestFetcher:
    async def test_returns_parsed_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_client(monkeypatch, {"data": [_DEEPSEEK_SAMPLE]}, None)
        models = await OpenAIModelsFetcher().fetch(
            base_url="https://api.example.com/v1", api_key=_SECRET
        )
        assert [m.model_id for m in models] == ["deepseek-flash"]
        assert models[0].max_context_length == 1_048_576

    async def test_client_is_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _FakeClient.closed = False
        _stub_client(monkeypatch, {"data": [_DEEPSEEK_SAMPLE]}, None)
        await OpenAIModelsFetcher().fetch(base_url="https://api.example.com/v1", api_key=_SECRET)
        assert _FakeClient.closed, "客户端必须关闭，否则连接池泄漏"

    async def test_empty_list_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_client(monkeypatch, {"data": []}, None)
        with pytest.raises(CatalogFetchError, match="空"):
            await OpenAIModelsFetcher().fetch(
                base_url="https://api.example.com/v1", api_key=_SECRET
            )

    async def test_blank_base_url_rejected(self) -> None:
        with pytest.raises(CatalogFetchError, match="接口地址"):
            await OpenAIModelsFetcher().fetch(base_url="  ", api_key=_SECRET)

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (_status_error(openai.AuthenticationError, 401), "鉴权失败"),
            (_status_error(openai.RateLimitError, 429), "限流"),
            (_status_error(openai.NotFoundError, 404), "未提供模型列表接口"),
            (_status_error(openai.APIStatusError, 500), "HTTP 500"),
            (openai.APIConnectionError(request=httpx.Request("GET", "https://x")), "无法连接"),
        ],
    )
    async def test_errors_are_user_readable(
        self, monkeypatch: pytest.MonkeyPatch, exc: Exception, expected: str
    ) -> None:
        _stub_client(monkeypatch, None, exc)
        with pytest.raises(CatalogFetchError) as info:
            await OpenAIModelsFetcher().fetch(
                base_url="https://api.example.com/v1", api_key=_SECRET
            )
        message = str(info.value)
        assert expected in message
        assert _SECRET not in message, "错误文案绝不能泄漏 api_key（MUST-19）"

    async def test_timeout_is_user_readable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request = httpx.Request("GET", "https://api.example.com/v1/models")
        _stub_client(monkeypatch, None, openai.APITimeoutError(request=request))
        with pytest.raises(CatalogFetchError, match="超时"):
            await OpenAIModelsFetcher().fetch(
                base_url="https://api.example.com/v1", api_key=_SECRET
            )
