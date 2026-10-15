"""F-803 / SHOULD-10 必测边界⑧：校验层对畸形响应的拒绝。

前端由 Zod 校验后端响应（畸形响应拒绝）；后端等价物 = `interfaces/api/schemas.py`
的响应契约模型（Pydantic v2）。本文件验证：喂入「畸形但字段名正确」的响应负载时，
契约模型必须抛 `ValidationError`（绝不容错收下），与请求侧的 422 用例互补——
后者覆盖 `FollowupRequest` / `HistoryUpdateRequest` 等**请求**模型，本文件覆盖
`FlowSnapshotResponse` / `RankingViewPayload` / `CostDetailPayload` / `ApiResponse`
等**响应**模型（此前无任何用例构造过这些模型）。
"""

from typing import Any

import pytest
from pydantic import ValidationError

from devprompt_ai.interfaces.api.schemas import (
    ApiResponse,
    CostDetailPayload,
    FlowSnapshotResponse,
    RankingViewPayload,
)


def _valid_ranking() -> dict[str, Any]:
    return {
        "variant": "A",
        "gap": 0.4,
        "confidence": 0.8,
        "marked": True,
        "reason": "",
        "fit": 0.9,
        "pref": 0.6,
        "total": 0.78,
    }


def test_valid_response_payload_accepted() -> None:
    # 基线：合法负载必须通过（先证模式可用，再证拒绝，避免「全拒绝」假绿）
    snap = FlowSnapshotResponse(
        session_id="s1",
        status="done",
        state="DONE",
        ranking=RankingViewPayload(**_valid_ranking()),
    )
    assert snap.ranking is not None
    assert snap.ranking.marked is True


def test_flow_snapshot_rejects_malformed_ranking_scalar_type() -> None:
    # 畸形响应①：ranking.gap 为字符串（期望 float，非数字串不可强制转换）→ 拒绝
    bad_ranking = _valid_ranking() | {"gap": "not-a-number"}
    with pytest.raises(ValidationError):
        FlowSnapshotResponse.model_validate(
            {"session_id": "s1", "status": "done", "state": "DONE", "ranking": bad_ranking}
        )


def test_ranking_view_rejects_missing_required_field() -> None:
    # 畸形响应②：缺必填字段 total → 拒绝（契约破坏不得静默补默认值）
    payload = _valid_ranking()
    del payload["total"]
    with pytest.raises(ValidationError):
        RankingViewPayload.model_validate(payload)


def test_cost_detail_rejects_unknown_literal_source() -> None:
    # 畸形响应③：llm_source 取非 Literal 成员（来源如实标注契约，F-805）→ 拒绝
    with pytest.raises(ValidationError):
        CostDetailPayload(
            llm_tokens=2,
            total_tokens=3,
            llm_source="guessed",  # type: ignore[arg-type]  # 合法集仅 {actual, no_call}
        )


def test_api_envelope_rejects_malformed_data_type() -> None:
    # 畸形响应④：信封 data 与泛型参数不符（泛型 int，却传非数字串）→ 拒绝
    with pytest.raises(ValidationError):
        ApiResponse[int](data="oops")  # type: ignore[arg-type]


def test_api_envelope_rejects_non_integer_code() -> None:
    # 畸形响应⑤：统一信封的错误码 code 非整数 → 拒绝（错误码契约强类型）
    with pytest.raises(ValidationError):
        ApiResponse[int](code="六")  # type: ignore[arg-type]
