# SPDX-License-Identifier: CPAL-1.0
from __future__ import annotations

from test_metadata_normalization import UNICODE_CASES

import asyncio
import json
import math
from io import BytesIO
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PIL import Image

from remember_me.core import (
    AssetRecord,
    EmbeddingRecord,
    IngestImageRequest,
    ReindexEmbeddingsRequest,
    SearchAssetsRequest,
    SearchAssetsResult,
    SearchResultItem,
    StorageFailure,
    UpdateMetadataRequest,
)
from remember_me.core.vector_index import (
    canonical_index_text,
    cosine_similarity,
    index_content_hash,
    validate_embedding_vector,
)
from remember_me.factory import create_local_runtime
from remember_me.mcp.server import MCP_TOOL_NAMES, create_mcp_runtime
from remember_me.search import NullVectorProvider
from remember_me.standalone.config import StandaloneConfig


MODEL = "test/semantic-v1"


def _png():
    output = BytesIO()
    Image.new("RGB", (2, 2), (20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


def _asset(asset_id="a" * 32, **changes):
    values = {
        "asset_id": asset_id,
        "source_sha256": asset_id[0] * 64,
        "stored_sha256": asset_id[0] * 64,
        "stored_relpath": "assets/{}/{}.png".format(
            asset_id[0] * 2,
            asset_id[0] * 64,
        ),
        "original_filename": "photo.png",
        "mime_type": "image/png",
        "kind": "image",
        "decoded_bytes": 100,
        "stored_bytes": 80,
        "width": 10,
        "height": 8,
        "created_at": "2026-07-28T00:00:00+00:00",
        "updated_at": "2026-07-28T00:00:00+00:00",
        "title": "Mountain",
        "description": "Landscape",
        "tags": ("Travel",),
    }
    values.update(changes)
    return AssetRecord(**values)


class QueryProvider:
    enabled = True

    def __init__(self, result=None, model_id=MODEL):
        self.model_id = model_id
        self.result = [1.0, 0.0] if result is None else result
        self.calls = []

    async def embed(self, text):
        self.calls.append(text)
        if isinstance(self.result, BaseException):
            raise self.result
        if callable(self.result):
            return self.result(text)
        return self.result


def _run_search(service, request=None):
    return asyncio.run(
        service.search_assets(request or SearchAssetsRequest(query="ocean"))
    )


def _store_current(repository, asset, vector=(1.0, 0.0), model_id=MODEL):
    text = canonical_index_text(asset)
    repository.store_embedding(
        asset.asset_id,
        vector,
        model_id,
        index_content_hash(text),
        asset.updated_at,
    )


def _runtime_with_asset(tmp_path, provider=None, asset=None):
    runtime = create_local_runtime(
        tmp_path,
        vector_provider=provider or QueryProvider(),
    )
    stored = runtime.repository.add(asset or _asset())
    return runtime, stored


def test_vector_validation_and_cosine_contract():
    assert validate_embedding_vector([1, 2.5]) == (1.0, 2.5)
    for invalid in (
        (),
        [],
        (1.0,),
        [True],
        [float("nan")],
        [float("inf")],
        ["1"],
        [[1.0]],
        [10 ** 1000],
        [Decimal("1.0")],
    ):
        assert validate_embedding_vector(invalid) is None
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == 1.0
    assert cosine_similarity((1.0, 0.0), (-1.0, 0.0)) == -1.0
    assert cosine_similarity((1.0, 0.0), (1.0,)) is None
    assert cosine_similarity((0.0, 0.0), (1.0, 0.0)) is None
    assert cosine_similarity((5e-324,), (5e-324,)) is None
    assert cosine_similarity((1e308, 1e308), (1e308, 1e308)) is None
    score = cosine_similarity((0.1, 0.2), (0.1, 0.2))
    assert math.isfinite(score)
    assert -1.0 <= score <= 1.0


@pytest.mark.parametrize(
    "query_vector",
    [
        [],
        [True],
        [float("nan")],
        [float("inf")],
        ["1"],
        [[1.0]],
        [10 ** 1000],
        [0.0, 0.0],
    ],
)
def test_invalid_query_vector_falls_back_exactly_to_keyword(tmp_path, query_vector):
    provider = QueryProvider(query_vector)
    runtime, asset = _runtime_with_asset(tmp_path, provider)
    _store_current(runtime.repository, asset)
    request = SearchAssetsRequest(query="mountain")
    expected = runtime.repository.search(request)
    assert _run_search(runtime.service, request) == expected
    assert provider.calls == ["mountain"]


@pytest.mark.parametrize("model_id", ["", "   "])
def test_invalid_model_identity_does_not_call_provider(tmp_path, model_id):
    provider = QueryProvider(model_id=model_id)
    runtime, _ = _runtime_with_asset(tmp_path, provider)
    request = SearchAssetsRequest(query="mountain")
    assert _run_search(runtime.service, request) == runtime.repository.search(request)
    assert provider.calls == []


def test_provider_disabled_blank_query_and_no_embeddings_are_exact_keyword_only(
    tmp_path,
):
    runtime, asset = _runtime_with_asset(tmp_path)
    _store_current(runtime.repository, asset)
    runtime.service.vector_provider = NullVectorProvider()
    request = SearchAssetsRequest(query="mountain")
    assert _run_search(runtime.service, request) == runtime.repository.search(request)

    provider = QueryProvider()
    runtime.service.vector_provider = provider
    blank = SearchAssetsRequest(query="   ")
    assert _run_search(runtime.service, blank) == runtime.repository.search(blank)
    assert provider.calls == []

    missing, _ = _runtime_with_asset(tmp_path / "missing", QueryProvider())
    assert _run_search(missing.service, request) == missing.repository.search(request)


@pytest.mark.parametrize("attribute", ["enabled", "model_id"])
def test_provider_state_property_failure_falls_back_without_embedding(
    tmp_path,
    attribute,
):
    class FailingStateProvider(QueryProvider):
        def __getattribute__(self, name):
            if name == attribute:
                raise RuntimeError("private provider state detail")
            return super().__getattribute__(name)

    provider = FailingStateProvider()
    runtime, _ = _runtime_with_asset(tmp_path, provider)
    request = SearchAssetsRequest(query="mountain")
    assert _run_search(runtime.service, request) == runtime.repository.search(request)
    assert provider.calls == []


def test_query_is_stripped_once_before_provider_embedding(tmp_path):
    provider = QueryProvider()
    runtime, asset = _runtime_with_asset(tmp_path, provider)
    _store_current(runtime.repository, asset)
    result = _run_search(
        runtime.service,
        SearchAssetsRequest(query="  ocean  "),
    )
    assert provider.calls == ["ocean"]
    assert result.results[0].semantic_score == 1.0


def test_provider_failure_falls_back_but_cancellation_propagates(tmp_path):
    runtime, _ = _runtime_with_asset(
        tmp_path / "failure",
        QueryProvider(RuntimeError("private provider detail")),
    )
    request = SearchAssetsRequest(query="mountain")
    assert _run_search(runtime.service, request) == runtime.repository.search(request)

    cancelled, _ = _runtime_with_asset(
        tmp_path / "cancelled",
        QueryProvider(asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        _run_search(cancelled.service, request)


@pytest.mark.parametrize(
    "error",
    [KeyboardInterrupt(), SystemExit(), BaseException("fatal")],
)
def test_fatal_provider_exceptions_are_not_swallowed(tmp_path, error):
    runtime, _ = _runtime_with_asset(tmp_path, QueryProvider(error))
    with pytest.raises(type(error)):
        _run_search(runtime.service)


def test_model_identity_change_during_embed_falls_back_before_vector_reads(
    tmp_path,
    monkeypatch,
):
    class SwitchingProvider(QueryProvider):
        async def embed(self, text):
            self.calls.append(text)
            self.model_id = "test/semantic-v2"
            return [1.0, 0.0]

    provider = SwitchingProvider(model_id=MODEL)
    runtime, _ = _runtime_with_asset(tmp_path, provider)
    calls = []

    def forbidden_read():
        calls.append("assets")
        raise AssertionError("semantic repository read must not occur")

    monkeypatch.setattr(runtime.repository, "list_assets_for_search", forbidden_read)
    request = SearchAssetsRequest(query="mountain")
    assert _run_search(runtime.service, request) == runtime.repository.search(request)
    assert provider.calls == ["mountain"]
    assert calls == []


def test_current_embedding_enables_pure_semantic_match(tmp_path):
    provider = QueryProvider()
    runtime, asset = _runtime_with_asset(tmp_path, provider)
    _store_current(runtime.repository, asset)
    result = _run_search(runtime.service)
    assert provider.calls == ["ocean"]
    assert [item.asset.asset_id for item in result.results] == [asset.asset_id]
    assert result.results[0].match_reasons == ("semantic",)
    assert result.results[0].semantic_score == 1.0


@pytest.mark.parametrize("vector", [(0.0, 1.0), (-1.0, 0.0)])
def test_zero_and_negative_scores_do_not_create_pure_semantic_matches(
    tmp_path,
    vector,
):
    runtime, asset = _runtime_with_asset(tmp_path)
    _store_current(runtime.repository, asset, vector)
    assert _run_search(runtime.service).results == ()


def test_keyword_and_semantic_reasons_can_coexist_for_one_asset(tmp_path):
    runtime, asset = _runtime_with_asset(tmp_path)
    _store_current(runtime.repository, asset)
    result = _run_search(
        runtime.service,
        SearchAssetsRequest(query="mountain"),
    )
    assert result.results[0].match_reasons == ("title_exact", "semantic")
    assert result.results[0].semantic_score == 1.0


def test_mixed_dimensions_and_zero_norm_only_skip_bad_assets(tmp_path):
    provider = QueryProvider([1.0, 0.0])
    runtime = create_local_runtime(tmp_path, vector_provider=provider)
    matching = runtime.repository.add(_asset("a" * 32, title="First"))
    wrong_dimension = runtime.repository.add(_asset("b" * 32, title="Second"))
    zero_norm = runtime.repository.add(_asset("c" * 32, title="Third"))
    _store_current(runtime.repository, matching, (1.0, 0.0))
    _store_current(runtime.repository, wrong_dimension, (1.0, 0.0, 0.0))
    _store_current(runtime.repository, zero_norm, (0.0, 0.0))
    result = _run_search(runtime.service)
    assert [item.asset.asset_id for item in result.results] == [matching.asset_id]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Changed"),
        ("description", "Changed"),
        ("original_filename", "changed.png"),
        ("kind", "file"),
        ("mime_type", "image/jpeg"),
    ],
)
def test_stale_scalar_index_fields_are_not_consumed(tmp_path, field, value):
    runtime, asset = _runtime_with_asset(tmp_path)
    _store_current(runtime.repository, asset)
    column = {"original_filename": "original_filename"}.get(field, field)
    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE assets SET {} = ? WHERE asset_id = ?".format(column),
            (value, asset.asset_id),
        )
    assert _run_search(runtime.service).results == ()


def test_stale_tags_empty_metadata_and_deleted_asset_are_not_consumed(tmp_path):
    tags_runtime, tags_asset = _runtime_with_asset(tmp_path / "tags")
    _store_current(tags_runtime.repository, tags_asset)
    with tags_runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE asset_tags SET tag_normalized = ?, tag_display = ? "
            "WHERE asset_id = ?",
            ("changed", "changed", tags_asset.asset_id),
        )
    assert _run_search(tags_runtime.service).results == ()

    empty_runtime, empty_asset = _runtime_with_asset(tmp_path / "empty")
    _store_current(empty_runtime.repository, empty_asset)
    with empty_runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE assets SET title = '', description = '' WHERE asset_id = ?",
            (empty_asset.asset_id,),
        )
        connection.execute(
            "DELETE FROM asset_tags WHERE asset_id = ?",
            (empty_asset.asset_id,),
        )
    assert _run_search(empty_runtime.service).results == ()

    deleted_runtime, deleted_asset = _runtime_with_asset(tmp_path / "deleted")
    _store_current(deleted_runtime.repository, deleted_asset)
    assert deleted_runtime.repository.delete(deleted_asset.asset_id) is True
    assert _run_search(deleted_runtime.service).results == ()


def test_other_model_is_not_consumed(tmp_path):
    runtime, asset = _runtime_with_asset(tmp_path)
    _store_current(runtime.repository, asset, model_id="test/other-model")
    assert _run_search(runtime.service).results == ()


def test_keyword_precedes_pure_semantic_and_scores_remain_publicly_safe(tmp_path):
    runtime = create_local_runtime(tmp_path, vector_provider=QueryProvider())
    keyword = runtime.repository.add(_asset("a" * 32, title="Ocean"))
    semantic = runtime.repository.add(_asset("b" * 32, title="Mountain"))
    _store_current(runtime.repository, semantic, (1.0, 0.0))
    result = _run_search(runtime.service)
    assert [item.asset.asset_id for item in result.results] == [
        keyword.asset_id,
        semantic.asset_id,
    ]
    assert result.results[0].semantic_score is None
    assert result.results[1].semantic_score == 1.0
    assert all(
        item.semantic_score is None or math.isfinite(item.semantic_score)
        for item in result.results
    )


def test_semantic_candidates_obey_filters_limit_and_stable_ties(tmp_path):
    runtime = create_local_runtime(tmp_path, vector_provider=QueryProvider())
    older = runtime.repository.add(
        _asset(
            "a" * 32,
            title="First",
            tags=("shared",),
            created_at="2026-07-27T00:00:00+00:00",
            updated_at="2026-07-27T00:00:00+00:00",
        )
    )
    newer = runtime.repository.add(
        _asset(
            "b" * 32,
            title="Second",
            tags=("shared",),
            created_at="2026-07-28T00:00:00+00:00",
        )
    )
    excluded = runtime.repository.add(
        _asset("c" * 32, title="Third", kind="file", tags=("shared",))
    )
    for asset in (older, newer, excluded):
        _store_current(runtime.repository, asset)
    request = SearchAssetsRequest(
        query="ocean",
        tags=("shared",),
        kind="image",
        limit=1,
    )
    result = _run_search(runtime.service, request)
    assert result.total == 2
    assert [item.asset.asset_id for item in result.results] == [newer.asset_id]

    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE assets SET created_at = ? WHERE asset_id = ?",
            (older.created_at, newer.asset_id),
        )
    tied = _run_search(
        runtime.service,
        replace(request, limit=20),
    )
    assert [item.asset.asset_id for item in tied.results] == [
        older.asset_id,
        newer.asset_id,
    ]


def test_final_pagination_is_applied_after_complete_combined_ranking(tmp_path):
    runtime = create_local_runtime(tmp_path, vector_provider=QueryProvider())
    for index, letter in enumerate(("a", "b", "c")):
        runtime.repository.add(
            _asset(
                letter * 32,
                title="Ocean {}".format(index),
                created_at="2026-07-2{}T00:00:00+00:00".format(index + 1),
            )
        )
    semantic = runtime.repository.add(_asset("d" * 32, title="Mountain"))
    _store_current(runtime.repository, semantic)
    result = _run_search(
        runtime.service,
        SearchAssetsRequest(query="ocean", limit=1, offset=3),
    )
    assert result.total == 4
    assert [item.asset.asset_id for item in result.results] == [semantic.asset_id]
    assert result.results[0].match_reasons == ("semantic",)


def test_keyword_ties_do_not_use_semantic_score_as_a_hidden_weight(tmp_path):
    runtime = create_local_runtime(tmp_path, vector_provider=QueryProvider())
    first = runtime.repository.add(_asset("a" * 32, title="Ocean"))
    second = runtime.repository.add(_asset("b" * 32, title="Ocean"))
    _store_current(runtime.repository, first, (0.5, math.sqrt(0.75)))
    _store_current(runtime.repository, second, (1.0, 0.0))
    result = _run_search(runtime.service)
    assert [item.asset.asset_id for item in result.results] == [
        first.asset_id,
        second.asset_id,
    ]
    assert result.results[0].semantic_score < result.results[1].semantic_score


def test_current_hash_and_final_ranking_share_one_asset_snapshot(
    tmp_path,
    monkeypatch,
):
    runtime, asset = _runtime_with_asset(tmp_path)
    _store_current(runtime.repository, asset)
    original = runtime.repository.list_embeddings_for_search

    def mutate_after_asset_snapshot(model_id):
        records = original(model_id)
        with runtime.repository._connect() as connection:
            connection.execute(
                "UPDATE assets SET title = ? WHERE asset_id = ?",
                ("Changed after snapshot", asset.asset_id),
            )
        return records

    monkeypatch.setattr(
        runtime.repository,
        "list_embeddings_for_search",
        mutate_after_asset_snapshot,
    )
    result = _run_search(runtime.service)
    assert result.results[0].asset.title == "Mountain"
    assert result.results[0].semantic_score == 1.0
    assert runtime.repository.get(asset.asset_id).title == "Changed after snapshot"


def test_repository_model_filter_order_and_corrupt_row_isolation(tmp_path):
    runtime = create_local_runtime(tmp_path)
    first = runtime.repository.add(_asset("a" * 32))
    corrupt = runtime.repository.add(_asset("b" * 32))
    last = runtime.repository.add(_asset("c" * 32))
    other = runtime.repository.add(_asset("d" * 32))
    _store_current(runtime.repository, first)
    _store_current(runtime.repository, corrupt)
    _store_current(runtime.repository, last)
    _store_current(runtime.repository, other, model_id="test/other")
    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE asset_embeddings SET embedding = ? WHERE asset_id = ?",
            (json.dumps([True]), corrupt.asset_id),
        )
    records = runtime.repository.list_embeddings_for_search(MODEL)
    assert [record.asset_id for record in records] == [
        first.asset_id,
        last.asset_id,
    ]


def test_repository_overall_failure_propagates_and_search_does_not_write(tmp_path, monkeypatch):
    runtime, asset = _runtime_with_asset(tmp_path)
    _store_current(runtime.repository, asset)
    with runtime.repository._connect() as connection:
        before = tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM asset_embeddings ORDER BY asset_id"
            ).fetchall()
        )
    _run_search(runtime.service)
    with runtime.repository._connect() as connection:
        after = tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM asset_embeddings ORDER BY asset_id"
            ).fetchall()
        )
    assert after == before

    def fail_connect():
        raise StorageFailure("database unavailable")

    monkeypatch.setattr(runtime.repository, "_connect", fail_connect)
    with pytest.raises(StorageFailure):
        runtime.repository.list_embeddings_for_search(MODEL)


def test_repository_read_cancellation_propagates(tmp_path, monkeypatch):
    runtime, _ = _runtime_with_asset(tmp_path)

    def cancel_read():
        raise asyncio.CancelledError()

    monkeypatch.setattr(runtime.repository, "list_assets_for_search", cancel_read)
    with pytest.raises(asyncio.CancelledError):
        _run_search(runtime.service)


def test_reindex_and_search_share_explicit_provider_instance(tmp_path):
    provider = QueryProvider()
    runtime = create_local_runtime(tmp_path / "explicit", vector_provider=provider)
    content = _png()
    created = runtime.service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="semantic.png",
            title="Initial",
            tags=("Travel",),
        )
    ).asset
    asset = runtime.service.update_metadata(
        UpdateMetadataRequest(
            asset_id=created.asset_id,
            title="Mountain",
            description="Landscape",
        )
    )
    reindexed = asyncio.run(
        runtime.service.reindex_embeddings(ReindexEmbeddingsRequest())
    )
    assert reindexed.indexed == 1
    result = _run_search(runtime.service)
    assert result.results[0].asset.asset_id == asset.asset_id
    assert result.results[0].semantic_score == 1.0
    assert provider.calls == [canonical_index_text(asset), "ocean"]
    assert runtime.service.vector_provider is provider

    first_default = create_local_runtime(tmp_path / "default-one")
    second_default = create_local_runtime(tmp_path / "default-two")
    assert isinstance(first_default.service.vector_provider, NullVectorProvider)
    assert isinstance(second_default.service.vector_provider, NullVectorProvider)
    assert first_default.service.vector_provider is not second_default.service.vector_provider
    assert first_default.repository is not second_default.repository


class FakeSearchService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def search_assets(self, request):
        self.calls.append(request)
        return self.result


def test_mcp_search_delegates_once_and_preserves_schema(tmp_path):
    asset = _asset()
    service = FakeSearchService(
        SearchAssetsResult(
            total=1,
            offset=0,
            limit=20,
            results=(
                SearchResultItem(
                    asset=asset,
                    match_reasons=("semantic",),
                    semantic_score=1.0,
                ),
            ),
        )
    )
    runtime = SimpleNamespace(service=service)
    mcp_runtime = create_mcp_runtime(
        runtime,
        StandaloneConfig(data_root=tmp_path),
    )
    tool = mcp_runtime.server._tool_manager.get_tool("rm_asset_search").fn
    response = asyncio.run(tool(query="ocean"))
    assert len(service.calls) == 1
    assert response.structuredContent["items"][0]["asset_id"] == asset.asset_id
    assert "semantic_score" not in response.structuredContent["items"][0]
    assert MCP_TOOL_NAMES == (
        "rm_asset_upload_link",
        "rm_asset_upload_status",
        "rm_asset_get",
        "rm_asset_update_metadata",
        "rm_asset_reindex_embeddings",
        "rm_asset_search",
        "rm_asset_download_link",
        "rm_asset_view",
        "rm_asset_inspect",
    )


def test_mcp_keyword_fallback_is_exact_for_null_and_failing_providers(tmp_path):
    request = {"query": "mountain", "limit": 20, "offset": 0}
    responses = []
    for name, provider in (
        ("null", NullVectorProvider()),
        ("failure", QueryProvider(RuntimeError("private backend detail"))),
    ):
        runtime, _ = _runtime_with_asset(tmp_path / name, provider)
        mcp_runtime = create_mcp_runtime(
            runtime,
            StandaloneConfig(data_root=tmp_path / name),
        )
        tool = mcp_runtime.server._tool_manager.get_tool("rm_asset_search").fn
        responses.append(asyncio.run(tool(**request)))
    assert responses[0] == responses[1]
    assert set(responses[0].structuredContent) == {
        "ok",
        "total",
        "limit",
        "offset",
        "items",
    }


def test_mcp_search_contains_no_vector_or_repository_orchestration():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "remember_me" / "mcp" / "tools.py"
    ).read_text(encoding="utf-8")
    block = source.split("    async def rm_asset_search", 1)[1].split(
        "    def rm_asset_download_link",
        1,
    )[0]
    assert "await runtime.service.search_assets" in block
    for forbidden in (
        "vector_provider",
        "list_embeddings_for_search",
        "cosine_similarity",
    ):
        assert forbidden not in block


@pytest.mark.parametrize("spelling,counterpart,key", UNICODE_CASES)
@pytest.mark.parametrize("reverse", [False, True])
def test_semantic_metadata_tag_filter_canonicalizes_both_sides(tmp_path, spelling, counterpart, key, reverse):
    stored, query_tag = (counterpart, spelling) if reverse else (spelling, counterpart)
    provider = QueryProvider()
    runtime, asset = _runtime_with_asset(tmp_path, provider, _asset(tags=(stored,)))
    _store_current(runtime.repository, asset)
    result = _run_search(runtime.service, SearchAssetsRequest(query="ocean", tags=(query_tag,)))
    assert result.total == 1
    assert result.results[0].asset == asset
    assert result.results[0].match_reasons == ("semantic",)
    assert provider.calls == ["ocean"]
    assert _run_search(runtime.service, SearchAssetsRequest(query="ocean", tags=("unrelated",))).total == 0
