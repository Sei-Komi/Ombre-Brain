import os
from unittest.mock import MagicMock

import frontmatter
import pytest

import tools._runtime as rt
from tools.breath.surface import surface_default
from tools.breath.search import surface_search
from tools.breath.importance import surface_by_importance
from tools._common import repair_pinned_desync


class EchoDehydrator:
    async def dehydrate(self, content, meta=None):
        return content


class FailingDehydrator:
    async def dehydrate(self, content, meta=None):
        raise RuntimeError("dehydrate unavailable")


class EmptyEmbedding:
    enabled = False

    async def search_similar(self, query, top_k=20):
        return []


def install_runtime(bucket_mgr, decay_eng, dehydrator):
    rt.config = {"surfacing": {}}
    rt.bucket_mgr = bucket_mgr
    rt.decay_engine = decay_eng
    rt.dehydrator = dehydrator
    rt.embedding_engine = EmptyEmbedding()
    rt.logger = MagicMock()
    rt.fire_webhook = None
    rt.mark_op = None


@pytest.mark.asyncio
async def test_default_breath_surfaces_type_permanent_bucket_without_pinned_flag(bucket_mgr, decay_eng):
    bucket_id = await bucket_mgr.create(
        content="Core rule alpha must always be visible.",
        bucket_type="permanent",
        importance=10,
        domain=["rules"],
    )
    install_runtime(bucket_mgr, decay_eng, EchoDehydrator())

    result = await surface_default(max_results=10, max_tokens=10000, tag_filter=[])

    assert bucket_id in result
    assert "Core rule alpha" in result


@pytest.mark.asyncio
async def test_search_breath_rejects_when_embedding_unavailable_even_if_dehydrate_fails(
    bucket_mgr,
    decay_eng,
    monkeypatch,
):
    """embedding 是 breath(query=...) 的强制依赖：未启用时直接拒绝整个检索，
    不再像旧版那样靠 dehydrate 失败回退原文继续返回结果（rule.md §1.5 的
    「不静默」现在延伸为「不降级」，见 bucket_manager._require_embedding_available）。
    """
    await bucket_mgr.create(
        content="Candlelit protocol belongs to the permanent rules.",
        bucket_type="permanent",
        importance=10,
        domain=["rules"],
    )
    install_runtime(bucket_mgr, decay_eng, FailingDehydrator())

    import tools.breath.search as search_mod

    monkeypatch.setattr(search_mod.random, "random", lambda: 1.0)

    with pytest.raises(RuntimeError, match="embedding"):
        await surface_search(
            query="Candlelit protocol",
            max_results=10,
            max_tokens=10000,
            domain="",
            valence=-1,
            arousal=-1,
            tag_filter=[],
        )


@pytest.mark.asyncio
async def test_search_domain_filter_matches_legacy_scalar_domain_on_permanent(bucket_mgr):
    permanent_id = await bucket_mgr.create(
        content="Legacy scalar domain permanent rule.",
        bucket_type="permanent",
        importance=10,
        domain=["rules"],
    )
    await bucket_mgr.create(
        content="Dynamic bucket in the same domain but without the query phrase.",
        domain=["rules"],
    )

    path = bucket_mgr._find_bucket_file(permanent_id)
    post = frontmatter.load(path)
    post["domain"] = "rules"
    with open(path, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))

    results = await bucket_mgr.search("Legacy scalar", domain_filter=["rules"], limit=10)
    result_ids = {bucket["id"] for bucket in results}

    assert permanent_id in result_ids


@pytest.mark.asyncio
async def test_decay_cycle_preserves_explicit_permanent_bucket_without_pinned_flag(bucket_mgr, decay_eng):
    permanent_id = await bucket_mgr.create(
        content="Permanent memory is a first-class bucket type.",
        bucket_type="permanent",
        importance=10,
        domain=["rules"],
    )

    stats = await decay_eng.run_decay_cycle()
    bucket = await bucket_mgr.get(permanent_id)

    assert stats["demoted_orphans"] == 0
    assert bucket["metadata"]["type"] == "permanent"
    assert f"{os.sep}permanent{os.sep}" in bucket["path"]


@pytest.mark.asyncio
async def test_direct_pinned_create_writes_permanent_type_and_unpin_moves_to_dynamic(bucket_mgr):
    bucket_id = await bucket_mgr.create(
        content="Direct pinned create should keep type and path in sync.",
        pinned=True,
    )

    pinned = await bucket_mgr.get(bucket_id)
    assert pinned["metadata"]["type"] == "permanent"
    assert pinned["metadata"]["pinned"] is True
    assert f"{os.sep}permanent{os.sep}" in pinned["path"]

    await bucket_mgr.update(bucket_id, pinned=False)
    unpinned = await bucket_mgr.get(bucket_id)

    assert unpinned["metadata"]["type"] == "dynamic"
    assert unpinned["metadata"]["pinned"] is False
    assert f"{os.sep}dynamic{os.sep}" in unpinned["path"]


@pytest.mark.asyncio
async def test_importance_breath_falls_back_to_raw_permanent_content_when_dehydrate_fails(
    bucket_mgr,
    decay_eng,
):
    bucket_id = await bucket_mgr.create(
        content="Permanent importance fallback should be readable.",
        bucket_type="permanent",
        importance=10,
        domain=["rules"],
    )
    install_runtime(bucket_mgr, decay_eng, FailingDehydrator())

    result = await surface_by_importance(importance_min=8, max_tokens=10000, tag_filter=[])

    assert bucket_id in result
    assert "Permanent importance fallback" in result


@pytest.mark.asyncio
async def test_repair_pinned_desync_does_not_demote_explicit_permanent_bucket(bucket_mgr):
    bucket_id = await bucket_mgr.create(
        content="Permanent repair guard should stay in permanent storage.",
        bucket_type="permanent",
        importance=10,
        domain=["rules"],
    )
    rt.logger = MagicMock()

    preview = await repair_pinned_desync(bucket_mgr, apply=False)
    applied = await repair_pinned_desync(bucket_mgr, apply=True)
    bucket = await bucket_mgr.get(bucket_id)

    assert preview["orphans"] == []
    assert applied["demoted"] == 0
    assert bucket["metadata"]["type"] == "permanent"
    assert f"{os.sep}permanent{os.sep}" in bucket["path"]


@pytest.mark.asyncio
async def test_idempotent_unpinned_update_preserves_explicit_permanent_bucket(bucket_mgr):
    bucket_id = await bucket_mgr.create(
        content="Permanent buckets should survive an idempotent pinned false update.",
        bucket_type="permanent",
        importance=10,
        domain=["rules"],
    )

    await bucket_mgr.update(bucket_id, pinned=False)
    bucket = await bucket_mgr.get(bucket_id)

    assert bucket["metadata"]["type"] == "permanent"
    assert bucket["metadata"].get("pinned") is False
    assert f"{os.sep}permanent{os.sep}" in bucket["path"]
