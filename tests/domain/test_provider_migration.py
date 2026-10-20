"""供应商段（2026-10-18 供应商中心化重构）的迁移与拆分测试。

锁定的核心语义：
1. 旧格式条目（自带 provider/base_url/api_key）首次读取即归并进供应商段，**密钥不丢**；
2. 迁移幂等——第二次读不再改动；
3. 读侧返回展平条目（内部消费方无需感知供应商段）；
4. 写侧 split 后条目只留 provider_id，端点与密钥只存一份；
5. 权威 providers 列表未出现的记录被删除（级联），刚配好零条目的记录保留。
"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.model_migration import (
    attach_providers,
    join_providers,
    normalize_providers,
    split_registry,
)

_LEGACY_ENTRY: dict[str, Any] = {
    "id": "m-e94707cd",
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "api_key": "sk-keep-1234567890",
    "model_id": "deepseek-flash",
}


def test_legacy_entry_is_merged_into_providers_without_losing_key() -> None:
    models, providers = attach_providers([dict(_LEGACY_ENTRY)], [])

    assert len(providers) == 1
    record = providers[0]
    assert record["provider"] == "deepseek"
    assert record["base_url"] == "https://api.deepseek.com"
    assert record["api_key"] == "sk-keep-1234567890"
    assert record["id"].startswith("p-")
    # 条目改为引用，且仍带 provider 供能力兜底判定
    assert models[0]["provider_id"] == record["id"]
    assert models[0]["provider"] == "deepseek"


def test_migration_is_idempotent() -> None:
    once, providers = attach_providers([dict(_LEGACY_ENTRY)], [])
    twice, providers_again = attach_providers(once, providers)

    assert [m["provider_id"] for m in twice] == [m["provider_id"] for m in once]
    assert [p["id"] for p in providers_again] == [p["id"] for p in providers]
    assert len(providers_again) == 1


def test_same_endpoint_entries_share_one_provider_record() -> None:
    second = {**_LEGACY_ENTRY, "id": "m-2", "model_id": "deepseek-v4-pro"}
    models, providers = attach_providers([dict(_LEGACY_ENTRY), second], [])

    assert len(providers) == 1
    assert {m["provider_id"] for m in models} == {providers[0]["id"]}


def test_distinct_endpoints_stay_distinct_records() -> None:
    relay = {
        **_LEGACY_ENTRY,
        "id": "m-2",
        "base_url": "https://relay.example.com/v1",
        "api_key": "sk-relay-1234567890",
    }
    _, providers = attach_providers([dict(_LEGACY_ENTRY), relay], [])

    assert len(providers) == 2
    assert {p["base_url"] for p in providers} == {
        "https://api.deepseek.com",
        "https://relay.example.com/v1",
    }


def test_join_flattens_endpoint_and_key_back_onto_entries() -> None:
    models, providers = attach_providers([dict(_LEGACY_ENTRY)], [])
    flat = join_providers(models, providers)

    assert flat[0]["base_url"] == "https://api.deepseek.com"
    assert flat[0]["api_key"] == "sk-keep-1234567890"


def test_split_drops_endpoint_fields_from_entries() -> None:
    models, providers = attach_providers([dict(_LEGACY_ENTRY)], [])
    flat = join_providers(models, providers)
    entries, records = split_registry(flat, None, providers)

    assert len(records) == 1
    assert records[0]["api_key"] == "sk-keep-1234567890"
    # 落库条目只留引用 + 按模型字段
    assert "base_url" not in entries[0]
    assert "api_key" not in entries[0]
    assert entries[0]["provider_id"] == records[0]["id"]
    assert entries[0]["model_id"] == "deepseek-flash"


def test_authoritative_providers_cascade_delete_unlisted() -> None:
    keep = {"id": "p-keep", "provider": "deepseek", "base_url": "https://a", "api_key": "sk-a"}
    drop = {"id": "p-drop", "provider": "deepseek", "base_url": "https://b", "api_key": "sk-b"}
    models = [
        {"id": "m-1", "provider_id": "p-keep", "model_id": "deepseek-flash"},
        {"id": "m-2", "provider_id": "p-drop", "model_id": "deepseek-v4-pro"},
    ]
    entries, records = split_registry(models, [keep], [keep, drop])

    assert [r["id"] for r in records] == ["p-keep"]
    assert [e["id"] for e in entries] == ["m-1"]


def test_authoritative_providers_keep_entry_less_record() -> None:
    """刚配好、还没勾选任何模型的供应商必须保留——否则多选列表永远是空的。"""
    fresh = {"id": "p-fresh", "provider": "deepseek", "base_url": "https://a", "api_key": "sk-a"}
    entries, records = split_registry([], [fresh], [])

    assert [r["id"] for r in records] == ["p-fresh"]
    assert entries == []


def test_normalize_providers_generates_id_and_keeps_key() -> None:
    records = normalize_providers(
        [{"provider": "deepseek", "base_url": "https://a", "api_key": "sk-x"}]
    )

    assert len(records) == 1
    assert records[0]["id"].startswith("p-")
    assert records[0]["api_key"] == "sk-x"


def test_normalize_providers_deduplicates_by_id() -> None:
    records = normalize_providers(
        [
            {"id": "p-1", "provider": "deepseek", "base_url": "https://a"},
            {"id": "p-1", "provider": "deepseek", "base_url": "https://b"},
        ]
    )

    assert len(records) == 1
    assert records[0]["base_url"] == "https://a"
