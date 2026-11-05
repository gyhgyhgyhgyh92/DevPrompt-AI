"""5C 三套同次调用生成契约测试（T5-1/T5-2）。

Fake 模式沿用既有约定：monkeypatch chat_structured（test_fallback.py 模式）测
generate_variants 的请求档位/排序/守卫契约；monkeypatch Runner 测解析失败纠偏重试。
无真实网络。
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from pydantic import ValidationError

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import GenerationError
from devprompt_ai.domain.generate.ports import (
    GenerationContext,
    Level,
    MultiVariantDraft,
    VariantDraft,
)
from devprompt_ai.domain.generate.variants import expand_levels, plan_levels, resolve_level
from devprompt_ai.harness import llm as llm_mod
from devprompt_ai.harness.llm import LLMGenerator

# 行号形态：覆盖「path.tsx:12」与「12:8」两类写法（项目取证摘要惯用 path:line）
_LINE_REF_RE = re.compile(r":\d{1,5}\b")
_LINE_WORD_RE = re.compile(r"\blines?\b", re.IGNORECASE)


def _cfg() -> AppConfig:
    return AppConfig(
        _env_file=None,  # type: ignore[call-arg]
        llm_base_url="https://fake/v1",
        llm_model="fake-model",
    )


def _ctx(level: Level = "C") -> GenerationContext:
    return GenerationContext(
        sentence="把提交按钮颜色改为 primary-500",
        project_root=".",
        level=level,
        facts_summary="SubmitButton@src/ui/Button.tsx:12；token 定义于 src/theme/tokens.ts:8",
        clarifications={},
    )


def _draft(level: Level, body: str | None = None) -> VariantDraft:
    return VariantDraft(
        title=f"{level} 档方案",
        body=body if body is not None else f"{level} 档正文",
        changes=["调整 SubmitButton 样式"],
        level=level,
    )


# ---- 档位推导（resolve_level → levels 的唯一映射，MUST-28 附注）----


def test_expand_levels_prefix_contract() -> None:
    assert expand_levels("A") == ["A"]
    assert expand_levels("B") == ["A", "B"]
    assert expand_levels("C") == ["A", "B", "C"]
    # 与 resolve_level 联动：C 档（取证完成）→ 三套；A 档（原始模糊句）→ 单套
    assert expand_levels(resolve_level(has_symbol=True, facts_complete=True)) == [
        "A",
        "B",
        "C",
    ]
    assert expand_levels(resolve_level(has_symbol=False, facts_complete=False)) == ["A"]


# ---- MultiVariantDraft 模型校验：n∈[1,3] + 前缀档位集 + 无重复 ----


def test_multi_variant_draft_accepts_valid_prefix_sets() -> None:
    prefix_sets: tuple[list[Level], ...] = (["A"], ["A", "B"], ["A", "B", "C"])
    for levels in prefix_sets:
        draft = MultiVariantDraft(variants=[_draft(lv) for lv in levels])
        assert [v.level for v in draft.variants] == levels


@pytest.mark.parametrize(
    "levels",
    [
        pytest.param([], id="n-0"),
        pytest.param(["A", "A"], id="n-2-dup"),
        pytest.param(["A", "C"], id="skip-AC"),
        pytest.param(["B", "C"], id="skip-BC"),
        pytest.param(["A", "B", "A", "C"], id="n-4"),
    ],
)
def test_multi_variant_draft_rejects_invalid(levels: list[Level]) -> None:
    with pytest.raises(ValidationError):
        MultiVariantDraft(variants=[_draft(lv) for lv in levels])


# ---- generate_variants：请求档位一致性 + prompt 注入 + timeout ----


async def test_generate_variants_requests_exact_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat(
        cfg: AppConfig,
        output_type: type[MultiVariantDraft],
        system: str,
        user: str,
        *,
        timeout: float | None = None,
    ) -> MultiVariantDraft:
        captured["output_type"] = output_type
        captured["system"] = system
        captured["user"] = user
        captured["timeout"] = timeout
        return MultiVariantDraft(variants=[_draft(lv) for lv in ("A", "B")])

    monkeypatch.setattr(llm_mod, "chat_structured", fake_chat)
    out = await LLMGenerator(_cfg()).generate_variants(_ctx(level="B"), ["A", "B"])

    assert captured["output_type"] is MultiVariantDraft
    # 生成超时委托 cfg.llm_timeout（F-604）：生成器不覆写，chat_structured 缺省取配置值
    assert captured["timeout"] is None
    assert [v.level for v in out.variants] == ["A", "B"]
    # 套数与请求档位写入 prompt
    assert "2 套" in captured["system"]
    assert "A、B" in captured["system"]
    assert '"level": "A"' in captured["user"]
    # 一致性与梯度约束必在（F-301）
    assert "描述必须一致" in captured["system"]
    assert "梯度" in captured["system"]
    # 上下文共享（同一次调用的 user 消息携带同一份取证摘要）
    assert "src/ui/Button.tsx:12" in captured["user"]


async def test_generate_variants_prompt_trims_constraints_to_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def fake_chat(
        cfg: AppConfig,
        output_type: type[MultiVariantDraft],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> MultiVariantDraft:
        captured["system"] = system
        return MultiVariantDraft(variants=[_draft("A")])

    monkeypatch.setattr(llm_mod, "chat_structured", fake_chat)
    out = await LLMGenerator(_cfg()).generate_variants(_ctx(level="A"), ["A"])

    assert [v.level for v in out.variants] == ["A"]
    assert "1 套" in captured["system"]
    # 仅请求 A 档：A 约束在，B/C 约束不出现（MUST-28 附注：仅 A 档=单套）
    assert "待确认清单" in captured["system"]
    assert "（推断）" not in captured["system"]
    assert "边界预判" not in captured["system"]


async def test_generate_variants_prompt_contains_all_tier_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def fake_chat(
        cfg: AppConfig,
        output_type: type[MultiVariantDraft],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> MultiVariantDraft:
        captured["system"] = system
        return MultiVariantDraft(variants=[_draft(lv) for lv in ("A", "B", "C")])

    monkeypatch.setattr(llm_mod, "chat_structured", fake_chat)
    await LLMGenerator(_cfg()).generate_variants(_ctx(), ["A", "B", "C"])

    # A：意图 + 待确认清单 + 禁行号
    assert "待确认清单" in captured["system"]
    assert "禁止出现任何行号" in captured["system"]
    # B：已取证路径 + 「（推断）」标注 + 验证方式
    assert "（推断）" in captured["system"]
    assert "验证方式" in captured["system"]
    # C：完整路径 + 行号 + 设计 token 出处 + 边界预判（多状态/响应式/暗色/无障碍）+ 测试指令
    assert "行号" in captured["system"]
    assert "设计 token" in captured["system"]
    assert "边界预判" in captured["system"]
    for keyword in ("多状态", "响应式", "暗色", "无障碍"):
        assert keyword in captured["system"]
    assert "测试指令" in captured["system"]


# ---- 输出归一化：档位单调（A<B<C）+ 档位集合必须匹配请求 ----


async def test_generate_variants_sorts_levels_monotonic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_chat(
        cfg: AppConfig,
        output_type: type[MultiVariantDraft],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> MultiVariantDraft:
        # 模拟 LLM 乱序返回 C→A→B
        return MultiVariantDraft(variants=[_draft("C"), _draft("A"), _draft("B")])

    monkeypatch.setattr(llm_mod, "chat_structured", fake_chat)
    out = await LLMGenerator(_cfg()).generate_variants(_ctx(), ["A", "B", "C"])
    assert [v.level for v in out.variants] == ["A", "B", "C"]


async def test_generate_variants_accepts_subset_of_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """U-7：套数不足不再整单失败——返回请求档位的非空子集即放行，交付门披露。"""

    async def fake_chat(
        cfg: AppConfig,
        output_type: type[MultiVariantDraft],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> MultiVariantDraft:
        return MultiVariantDraft(variants=[_draft("A"), _draft("B")])  # 请求了 C 却少给

    monkeypatch.setattr(llm_mod, "chat_structured", fake_chat)
    out = await LLMGenerator(_cfg()).generate_variants(_ctx(), ["A", "B", "C"])
    assert [v.level for v in out.variants] == ["A", "B"]


async def test_generate_variants_rejects_illegal_prefix_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非法前缀集（如 {A,C}）仍拒绝：结构层校验失败 → 纠偏重试后 4003。"""

    async def fake_chat(
        cfg: AppConfig,
        output_type: type[MultiVariantDraft],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> MultiVariantDraft:
        # MultiVariantDraft 的 model_validator 拒绝 {A,C}；chat_structured 纠偏重试
        # 仍失败的最终形态就是 GenerationError(4003)，这里直接给出该终态。
        raise GenerationError("档位集合不是合法可输出档位前缀集（MUST-28）", code=4003)

    monkeypatch.setattr(llm_mod, "chat_structured", fake_chat)
    with pytest.raises(GenerationError):
        await LLMGenerator(_cfg()).generate_variants(_ctx(), ["A", "B", "C"])


@pytest.mark.parametrize(
    "levels",
    [
        pytest.param([], id="empty"),
        pytest.param(["B"], id="skip-B"),
        pytest.param(["A", "C"], id="skip-AC"),
        pytest.param(["A", "A"], id="dup"),
        pytest.param(["A", "B", "C", "A"], id="n-4"),
    ],
)
async def test_generate_variants_rejects_invalid_levels_request(
    levels: list[Level],
) -> None:
    with pytest.raises(GenerationError):
        await LLMGenerator(_cfg()).generate_variants(_ctx(), levels)


# ---- 档位模板保真（Fake 遵循档位模板输出，passthrough 校验 F-302/304 验收形态）----


async def test_generate_variants_a_without_line_numbers_c_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_chat(
        cfg: AppConfig,
        output_type: type[MultiVariantDraft],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> MultiVariantDraft:
        return MultiVariantDraft(
            variants=[
                _draft(
                    "A",
                    body="只述意图：把提交按钮颜色改为 primary-500。待确认清单：目标文件未确认。",
                ),
                _draft(
                    "B",
                    body=(
                        "已取证路径 src/ui/Button.tsx（推断）将 color 改为"
                        " var(--color-primary-500)；验证方式：跑组件测试并比对 diff。"
                    ),
                ),
                _draft(
                    "C",
                    body=(
                        "修改 src/ui/Button.tsx:12 的 className 为 btn-primary；token 出处 "
                        "src/theme/tokens.ts:8。边界预判：多状态、响应式、暗色模式、无障碍。"
                        "测试指令：在 tests/ui/button.test.tsx 断言配色与状态类。"
                    ),
                ),
            ]
        )

    monkeypatch.setattr(llm_mod, "chat_structured", fake_chat)
    out = await LLMGenerator(_cfg()).generate_variants(_ctx(), ["A", "B", "C"])
    variant_a, variant_b, variant_c = out.variants

    # A 无行号（\d+:\d+ 与 "line" 字样均不得出现，F-302 验收）
    assert _LINE_REF_RE.search(variant_a.body) is None
    assert _LINE_WORD_RE.search(variant_a.body) is None
    # B 推断项显式标注（F-303）
    assert "（推断）" in variant_b.body
    # C 含行号与测试指令（F-304 验收）
    assert _LINE_REF_RE.search(variant_c.body) is not None
    assert "测试" in variant_c.body
    # 三套正文呈 A<B<C 梯度（F-301 验收）
    assert len(variant_a.body) < len(variant_b.body) < len(variant_c.body)


# ---- 解析失败纠偏重试（chat_structured 内聚：Runner 层 fake）----


class _FakeResult:
    def __init__(self, final_output: str) -> None:
        self.final_output = final_output
        self.usage = None


def _runner_with_outputs(outputs: list[str], calls: list[str]) -> type:
    """构造按序吐出 outputs 的假 Runner（每次 run 记录入参到 calls）。"""

    class _FakeRunner:
        @staticmethod
        async def run(agent: Any, user_input: Any, *, max_turns: int = 1) -> _FakeResult:
            calls.append(str(user_input))
            return _FakeResult(outputs[min(len(calls), len(outputs)) - 1])

    return _FakeRunner


async def test_generate_variants_retries_once_on_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    valid = MultiVariantDraft(variants=[_draft("A")])
    monkeypatch.setattr(
        llm_mod,
        "Runner",
        _runner_with_outputs(["抱歉，这不是 JSON。", valid.model_dump_json()], calls),
    )

    out = await LLMGenerator(_cfg()).generate_variants(_ctx(level="A"), ["A"])

    assert len(calls) == 2  # 首轮解析失败 → 恰好一次纠偏重试
    assert [v.level for v in out.variants] == ["A"]


async def test_generate_variants_raises_after_second_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        llm_mod,
        "Runner",
        _runner_with_outputs(["仍然不是 JSON", "还是不是 JSON"], calls),
    )

    with pytest.raises(GenerationError) as exc_info:
        await LLMGenerator(_cfg()).generate_variants(_ctx(level="A"), ["A"])

    assert exc_info.value.code == 4003
    assert len(calls) == 2  # 只重试一次，不无限重试


class TestPlanLevels:
    """多轮产物形态（2026-10-20）：首轮三套、后续单套且不越级。"""

    def test_three_versions_follow_prefix(self) -> None:
        assert plan_levels("B", max_versions=3) == ["A", "B"]

    def test_single_version_prefers_previous_choice(self) -> None:
        assert plan_levels("C", max_versions=1, preferred="B") == ["B"]

    def test_single_version_never_exceeds_turn_level(self) -> None:
        """上一轮选了 C，但本轮取证不完整（level=A）→ 只能出 A（MUST-28 不越级）。"""
        assert plan_levels("A", max_versions=1, preferred="C") == ["A"]

    def test_single_version_without_preference_uses_current(self) -> None:
        assert plan_levels("C", max_versions=1) == ["C"]
