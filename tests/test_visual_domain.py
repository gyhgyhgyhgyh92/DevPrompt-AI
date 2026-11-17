"""视觉生成域（2026-11-14 多模态）：路由、风格注入、契约校验与多模态消息组装。"""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from devprompt_ai.common.i18n import DEFAULT_LOCALE
from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains import get_pack
from devprompt_ai.domain.domains.packs.visual import VISUAL_STYLES, visual_pack
from devprompt_ai.domain.domains.rules import match_by_keyword
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.generate.templates.b_standard import build_user
from devprompt_ai.harness.adapters.base import parse_image_data_url
from devprompt_ai.harness.llm import _user_payload
from devprompt_ai.interfaces.api.schemas import OptimizeRequest, validate_images

# ---------------------------------------------------------------------------
# 路由与领域包契约
# ---------------------------------------------------------------------------


def test_keyword_routes_visual() -> None:
    """词表第一级：文生图/即梦/Sora 等命中 visual，不落到 LLM 分类。"""
    for sentence in (
        "帮我优化一张赛博朋克海报的文生图提示词",
        "给即梦写一段视频提示词",
        "midjourney prompt for a dragon",
    ):
        verdict = match_by_keyword(sentence)
        assert verdict is not None and verdict[0] == "visual"


def test_visual_pack_contract() -> None:
    pack = visual_pack()
    assert pack.id == "visual" and get_pack("visual").id == "visual"
    assert pack.needs_repo is False
    assert AgentAction.RETRIEVE not in pack.allowed_actions
    assert pack.claim_kinds == frozenset()
    assert len(pack.keywords) >= 10


def test_visual_styles_whitelist() -> None:
    assert VISUAL_STYLES == (
        "general",
        "photography",
        "creative",
        "chinese-model",
        "json-structured",
        "video",
    )


# ---------------------------------------------------------------------------
# 风格指令注入（b_standard.build_user 纯函数）
# ---------------------------------------------------------------------------


def _ctx(**overrides: object) -> GenerationContext:
    fields: dict[str, object] = {"sentence": "画一张海报", "project_root": ""}
    fields.update(overrides)
    return GenerationContext(**fields)  # type: ignore[arg-type]


def test_style_directive_injected_for_visual() -> None:
    body = build_user(_ctx(domain_id="visual", style_id="photography"), DEFAULT_LOCALE)
    assert "摄影向" in body


def test_unknown_style_falls_back_to_generic() -> None:
    body = build_user(_ctx(domain_id="visual", style_id="no-such-style"), DEFAULT_LOCALE)
    # 指令经 evidence JSON 块包裹，原文换行会被转义——断言短片段而非整段
    assert "视觉风格" not in body
    assert "【领域指令：视觉生成】" in body


def test_non_visual_domain_ignores_style() -> None:
    body = build_user(_ctx(domain_id="code", style_id="photography"), DEFAULT_LOCALE)
    assert "摄影向" not in body
    # code 域不注入任何领域指令占位字段（与领域化改造前逐字一致的约定）
    assert "领域指令" not in body


# ---------------------------------------------------------------------------
# service 层 override / style 透传
# ---------------------------------------------------------------------------


async def test_optimize_with_visual_override_needs_no_repo() -> None:
    """visual 域 needs_repo=False：无项目路径也能启动（不抛 2001）。"""
    from devprompt_ai.config import AppConfig
    from devprompt_ai.harness.process import SymbolTableProvider
    from devprompt_ai.service import ForgeService
    from test_service import FakeDecider, FakeGenerator, FakeReader, FakeRunner, FakeStore

    gen = FakeGenerator()
    svc = ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader(set()),
        generator=gen,
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
    )
    snap = await svc.optimize(
        "local",
        "",
        "帮我优化一张国风插画的文生图提示词",
        request_id="r1",
        domain_override="visual",
        style="chinese-model",
    )
    assert snap.status in {"ask", "done"}


# ---------------------------------------------------------------------------
# 参考图契约校验
# ---------------------------------------------------------------------------


def _png_data_url(size_bytes: int = 16) -> str:
    payload = base64.b64encode(b"\x89PNG" + b"\x00" * max(size_bytes - 4, 0)).decode()
    return f"data:image/png;base64,{payload}"


def test_validate_images_accepts_visual_domain() -> None:
    images = [_png_data_url() for _ in range(3)]
    assert validate_images(images, "visual") == images


def test_validate_images_rejects_non_visual_domain() -> None:
    with pytest.raises(ValueError, match="visual"):
        validate_images([_png_data_url()], "code")


def test_validate_images_rejects_over_limit() -> None:
    images = [_png_data_url() for _ in range(4)]
    with pytest.raises(ValueError, match="最多"):
        validate_images(images, "visual")


def test_validate_images_rejects_bad_media_type() -> None:
    payload = base64.b64encode(b"\x00" * 8).decode()
    with pytest.raises(ValueError, match="png/jpeg/webp"):
        validate_images([f"data:image/gif;base64,{payload}"], "visual")


def test_validate_images_rejects_oversize() -> None:
    with pytest.raises(ValueError, match="4MB"):
        validate_images([_png_data_url(4 * 1024 * 1024 + 1)], "visual")


def test_optimize_request_images_validated() -> None:
    with pytest.raises(ValidationError):
        OptimizeRequest(sentence="x", images=[_png_data_url()], domain="code")
    req = OptimizeRequest(sentence="x", images=[_png_data_url()], domain="visual")
    assert req.images is not None and len(req.images) == 1


# ---------------------------------------------------------------------------
# 多模态消息组装（harness 层）
# ---------------------------------------------------------------------------


def test_user_payload_plain_text_unchanged() -> None:
    assert _user_payload("你好", ()) == "你好"


def test_user_payload_with_images() -> None:
    img = _png_data_url()
    payload = _user_payload("优化这张图", (img,))
    assert isinstance(payload, list)
    message = payload[0]
    assert message["role"] == "user"
    content = message["content"]
    assert content[0] == {"type": "input_text", "text": "优化这张图"}
    assert content[1] == {"type": "input_image", "image_url": img}


def test_parse_image_data_url() -> None:
    media_type, data = parse_image_data_url("data:image/webp;base64,QUJD")
    assert (media_type, data) == ("image/webp", "QUJD")
    assert parse_image_data_url("https://example.com/a.png") is None
    assert parse_image_data_url("data:image/png,QUJD") is None  # 无 base64 标记
