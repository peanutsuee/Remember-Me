# SPDX-License-Identifier: CPAL-1.0
from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from remember_me.core import (
    AssetRecord,
    AssetUnavailable,
    EmbeddingRecord,
    InvalidMetadata,
    ReindexEmbeddingsRequest,
    ReindexEmbeddingsResult,
    UpdateMetadataRequest,
)
from remember_me.core.vector_index import (
    canonical_index_text,
    index_content_hash,
)
from remember_me.factory import create_local_runtime, create_local_service
from remember_me.mcp.server import MCP_TOOL_NAMES, create_mcp_runtime
from remember_me.search import NullVectorProvider
from remember_me.standalone.config import StandaloneConfig
from remember_me.storage import SQLiteAssetRepository


def _asset(asset_id="a" * 32, **changes):
    values = {
        "asset_id": asset_id,
        "source_sha256": "b" * 64,
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
        "title": "Title",
        "description": "Description",
        "tags": ("zeta", "Alpha"),
    }
    values.update(changes)
    return AssetRecord(**values)


class RecordingProvider:
    enabled = True

    def __init__(self, model_id="test/provider-v1", result=None, callback=None):
        self.model_id = model_id
        self.result = [0.25, -0.5] if result is None else result
        self.callback = callback
        self.calls = []

    async def embed(self, text):
        self.calls.append(text)
        if self.callback is not None:
            self.callback(text)
        if isinstance(self.result, Exception):
            raise self.result
        if callable(self.result):
            return self.result(text)
        return self.result


def _runtime(tmp_path, provider=None):
    runtime = create_local_runtime(
        tmp_path,
        vector_provider=provider or RecordingProvider(),
    )
    return runtime


def _run(service, request=None):
    return asyncio.run(
        service.reindex_embeddings(request or ReindexEmbeddingsRequest())
    )


def _assert_counters(result):
    assert result.scanned == result.indexed + result.skipped + result.failed


def test_reindex_result_rejects_invalid_counter_identity():
    with pytest.raises(ValueError, match="invalid_reindex_counters"):
        ReindexEmbeddingsResult(
            enabled=True,
            model_id="test/provider-v1",
            scanned=2,
            indexed=1,
            skipped=0,
            failed=0,
        )


def test_canonical_index_text_is_deterministic_and_core_owned():
    asset = _asset(tags=("zeta", "Alpha", "beta"))
    text = canonical_index_text(asset)
    assert text == "\n".join(
        (
            "Title: Title",
            "Description: Description",
            "Tags: Alpha, beta, zeta",
            "Filename: photo.png",
            "Kind: image",
            "MIME type: image/png",
        )
    )
    assert index_content_hash(text) == index_content_hash(text)
    assert canonical_index_text(
        replace(asset, title="", description="", tags=())
    ) == ""


def test_first_reindex_indexes_and_current_record_skips(tmp_path):
    provider = RecordingProvider()
    runtime = _runtime(tmp_path, provider)
    asset = runtime.repository.add(_asset())

    first = _run(runtime.service)
    assert (first.scanned, first.indexed, first.skipped, first.failed) == (
        1,
        1,
        0,
        0,
    )
    record = runtime.repository.get_embedding(asset.asset_id)
    assert record.embedding == (0.25, -0.5)
    assert record.model_id == provider.model_id
    assert len(provider.calls) == 1

    second = _run(runtime.service)
    assert (second.scanned, second.indexed, second.skipped, second.failed) == (
        1,
        0,
        1,
        0,
    )
    assert len(provider.calls) == 1
    _assert_counters(first)
    _assert_counters(second)


def test_metadata_and_model_changes_rebuild_stale_records(tmp_path):
    first_provider = RecordingProvider("test/provider-v1")
    runtime = _runtime(tmp_path, first_provider)
    asset = runtime.repository.add(_asset())
    _run(runtime.service)

    runtime.repository.update_metadata(
        UpdateMetadataRequest(asset_id=asset.asset_id, title="Changed"),
        "2026-07-28T00:00:01+00:00",
    )
    changed = _run(runtime.service)
    assert changed.indexed == 1
    assert len(first_provider.calls) == 2

    second_provider = RecordingProvider("test/provider-v2")
    runtime.service.vector_provider = second_provider
    changed_model = _run(runtime.service)
    assert changed_model.indexed == 1
    assert len(second_provider.calls) == 1
    assert runtime.repository.get_embedding(asset.asset_id).model_id == (
        "test/provider-v2"
    )


def test_empty_user_metadata_deletes_embedding_and_skips(tmp_path):
    runtime = _runtime(tmp_path)
    asset = runtime.repository.add(_asset())
    _run(runtime.service)
    runtime.repository.update_metadata(
        UpdateMetadataRequest(
            asset_id=asset.asset_id,
            title="",
            description="",
            tags=(),
        ),
        "2026-07-28T00:00:01+00:00",
    )
    result = _run(runtime.service)
    assert (result.scanned, result.indexed, result.skipped, result.failed) == (
        1,
        0,
        1,
        0,
    )
    assert runtime.repository.get_embedding(asset.asset_id) is None


def test_disabled_provider_skips_current_and_missing(tmp_path):
    runtime = _runtime(tmp_path, NullVectorProvider())
    current_asset = runtime.repository.add(_asset(asset_id="a" * 32))
    missing_asset = runtime.repository.add(
        _asset(asset_id="c" * 32, stored_sha256="c" * 64)
    )
    text = canonical_index_text(current_asset)
    runtime.repository.store_embedding(
        current_asset.asset_id,
        [1.0],
        runtime.service.vector_provider.model_id,
        index_content_hash(text),
        current_asset.updated_at,
    )
    result = _run(runtime.service)
    assert result.enabled is False
    assert (result.scanned, result.indexed, result.skipped, result.failed) == (
        2,
        0,
        2,
        0,
    )
    assert runtime.repository.get_embedding(current_asset.asset_id) is not None
    assert runtime.repository.get_embedding(missing_asset.asset_id) is None


@pytest.mark.parametrize(
    "invalid_vector",
    [[], (), [True], ["1"], [float("nan")], [float("inf")]],
)
def test_invalid_provider_vectors_fail_without_persistence(
    tmp_path,
    invalid_vector,
):
    provider = RecordingProvider(result=invalid_vector)
    runtime = _runtime(tmp_path, provider)
    asset = runtime.repository.add(_asset())
    result = _run(runtime.service)
    assert (result.scanned, result.indexed, result.skipped, result.failed) == (
        1,
        0,
        0,
        1,
    )
    assert runtime.repository.get_embedding(asset.asset_id) is None
    _assert_counters(result)


def test_provider_failure_is_per_asset_and_batch_continues(tmp_path):
    provider = RecordingProvider(
        result=lambda text: (
            (_ for _ in ()).throw(RuntimeError("private provider detail"))
            if "First" in text
            else [0.5]
        )
    )
    runtime = _runtime(tmp_path, provider)
    runtime.repository.add(_asset(asset_id="a" * 32, title="First"))
    runtime.repository.add(
        _asset(
            asset_id="c" * 32,
            stored_sha256="c" * 64,
            title="Second",
        )
    )
    result = _run(runtime.service)
    assert (result.scanned, result.indexed, result.skipped, result.failed) == (
        2,
        1,
        0,
        1,
    )
    _assert_counters(result)


def test_metadata_change_during_await_rejects_conditional_store(tmp_path):
    runtime = _runtime(tmp_path)
    asset = runtime.repository.add(_asset())

    def change_metadata(_text):
        runtime.repository.update_metadata(
            UpdateMetadataRequest(asset_id=asset.asset_id, title="Concurrent"),
            asset.updated_at,
        )

    provider = RecordingProvider(callback=change_metadata)
    runtime.service.vector_provider = provider
    result = _run(runtime.service)
    assert result.failed == 1
    assert runtime.repository.get_embedding(asset.asset_id) is None


def test_asset_delete_during_await_rejects_conditional_store(tmp_path):
    runtime = _runtime(tmp_path)
    asset = runtime.repository.add(_asset())
    provider = RecordingProvider(
        callback=lambda _text: runtime.repository.delete(asset.asset_id)
    )
    runtime.service.vector_provider = provider
    result = _run(runtime.service)
    assert result.failed == 1
    assert runtime.repository.get_embedding(asset.asset_id) is None


@pytest.mark.parametrize("limit", [True, "1", 0, 501])
def test_reindex_limit_validation(tmp_path, limit):
    runtime = _runtime(tmp_path)
    with pytest.raises(InvalidMetadata) as raised:
        _run(runtime.service, ReindexEmbeddingsRequest(limit=limit))
    assert raised.value.code == "invalid_metadata"


@pytest.mark.parametrize("asset_id", ["missing", "f" * 32])
def test_reindex_specific_invalid_or_missing_asset_is_unavailable(
    tmp_path,
    asset_id,
):
    runtime = _runtime(tmp_path)
    with pytest.raises(AssetUnavailable):
        _run(
            runtime.service,
            ReindexEmbeddingsRequest(asset_id=asset_id),
        )


def test_repository_get_delete_conditional_store_and_cascade(tmp_path):
    repository = SQLiteAssetRepository(tmp_path)
    asset = repository.add(_asset())
    record = EmbeddingRecord(
        asset_id=asset.asset_id,
        embedding=(0.1, 0.2),
        model_id="test/provider-v1",
        content_hash="d" * 64,
        updated_at=asset.updated_at,
    )
    assert repository.store_embedding_if_asset_current(asset, record) is True
    assert repository.get_embedding(asset.asset_id) == record
    assert repository.delete_embedding(asset.asset_id) is True
    assert repository.delete_embedding(asset.asset_id) is False

    assert repository.store_embedding_if_asset_current(asset, record) is True
    repository.update_metadata(
        UpdateMetadataRequest(asset_id=asset.asset_id, tags=("changed",)),
        asset.updated_at,
    )
    assert repository.store_embedding_if_asset_current(asset, record) is False
    assert repository.delete(asset.asset_id) is True
    assert repository.get_embedding(asset.asset_id) is None


def test_factory_defaults_and_explicit_async_provider(tmp_path):
    default = create_local_runtime(tmp_path / "default")
    assert isinstance(default.service.vector_provider, NullVectorProvider)
    provider = RecordingProvider()
    explicit = create_local_runtime(
        tmp_path / "explicit",
        vector_provider=provider,
    )
    assert explicit.service.vector_provider is provider
    service = create_local_service(
        tmp_path / "service",
        vector_provider=provider,
    )
    assert service.vector_provider is provider


class FakeReindexService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def reindex_embeddings(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def _mcp_reindex_tool(tmp_path, service):
    runtime = SimpleNamespace(service=service)
    mcp_runtime = create_mcp_runtime(
        runtime,
        StandaloneConfig(data_root=tmp_path),
    )
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
    return mcp_runtime.server._tool_manager.get_tool(
        "rm_asset_reindex_embeddings"
    ).fn


@pytest.mark.parametrize("enabled", [False, True])
def test_mcp_reindex_delegates_once_and_preserves_output(tmp_path, enabled):
    core_result = ReindexEmbeddingsResult(
        enabled=enabled,
        model_id="test/provider-v1",
        scanned=3,
        indexed=2 if enabled else 0,
        skipped=0 if enabled else 1,
        failed=1 if enabled else 2,
    )
    service = FakeReindexService(result=core_result)
    tool = _mcp_reindex_tool(tmp_path, service)
    response = asyncio.run(tool(asset_id="a" * 32, limit=7))
    assert len(service.calls) == 1
    assert service.calls[0] == ReindexEmbeddingsRequest(
        asset_id="a" * 32,
        limit=7,
    )
    payload = response.structuredContent
    assert set(payload) == {
        "ok",
        "enabled",
        "model_id",
        "selected",
        "indexed",
        "failed",
    }
    assert payload["selected"] == 3
    assert payload["indexed"] == (2 if enabled else 0)
    assert payload["failed"] == (1 if enabled else 0)


def test_mcp_reindex_error_envelope_does_not_leak_provider_details(tmp_path):
    service = FakeReindexService(
        error=RuntimeError("private path token and network detail")
    )
    tool = _mcp_reindex_tool(tmp_path, service)
    response = asyncio.run(tool())
    assert response.isError is True
    assert response.structuredContent == {
        "ok": False,
        "error": {
            "code": "internal_error",
            "message": "The operation could not be completed.",
        },
    }
    assert "private path" not in response.content[0].text



def test_acceptance_public_imports_remain_available():
    import remember_me.core as public_core
    import remember_me.core.contracts as public_contracts
    import remember_me.core.models as public_models
    import remember_me.factory as public_factory
    import remember_me.search.vectors as public_vectors

    assert public_core.EmbeddingRecord is EmbeddingRecord
    assert public_core.ReindexEmbeddingsRequest is ReindexEmbeddingsRequest
    assert public_core.ReindexEmbeddingsResult is ReindexEmbeddingsResult
    assert public_contracts.RememberMeCore is public_core.RememberMeCore
    assert public_models.AssetRecord is AssetRecord
    assert public_factory.create_local_runtime is create_local_runtime
    assert public_vectors.NullVectorProvider is NullVectorProvider


@pytest.mark.parametrize(
    "changes",
    [
        {"scanned": True, "indexed": 1, "skipped": 0, "failed": 0},
        {"scanned": 1, "indexed": True, "skipped": 0, "failed": 0},
        {"scanned": 1, "indexed": 1, "skipped": False, "failed": 0},
        {"scanned": 1, "indexed": 1, "skipped": 0, "failed": False},
        {"scanned": -1, "indexed": 0, "skipped": 0, "failed": 0},
        {"scanned": 2, "indexed": 1, "skipped": 0, "failed": 0},
    ],
)
def test_acceptance_result_rejects_bool_negative_and_mismatch(changes):
    with pytest.raises(ValueError, match="invalid_reindex_counters"):
        ReindexEmbeddingsResult(
            enabled=True,
            model_id="test/provider-v1",
            **changes,
        )


def test_acceptance_canonical_tags_match_repository_semantics(tmp_path):
    runtime = _runtime(tmp_path)
    stored = runtime.repository.add(
        _asset(tags=(" zeta ", "ALPHA", "alpha", " beta  tag "))
    )
    assert stored.tags == ("ALPHA", "beta tag", "zeta")
    assert "Tags: ALPHA, beta tag, zeta" in canonical_index_text(stored)


def test_acceptance_whitespace_metadata_deletes_without_provider(tmp_path):
    provider = RecordingProvider()
    runtime = _runtime(tmp_path, provider)
    asset = runtime.repository.add(
        _asset(title=" \t ", description="\n ", tags=(" ", "\t"))
    )
    runtime.repository.store_embedding(
        asset.asset_id,
        [1.0],
        provider.model_id,
        "d" * 64,
        asset.updated_at,
    )
    assert canonical_index_text(asset) == ""
    result = _run(runtime.service)
    assert (result.scanned, result.indexed, result.skipped, result.failed) == (
        1,
        0,
        1,
        0,
    )
    assert provider.calls == []
    assert runtime.repository.get_embedding(asset.asset_id) is None


def test_acceptance_disabled_provider_four_quadrants(tmp_path):
    runtime = _runtime(tmp_path, NullVectorProvider())
    current = runtime.repository.add(_asset(asset_id="a" * 32))
    missing = runtime.repository.add(
        _asset(asset_id="c" * 32, stored_sha256="c" * 64)
    )
    stale = runtime.repository.add(
        _asset(asset_id="d" * 32, stored_sha256="d" * 64)
    )
    empty = runtime.repository.add(
        _asset(
            asset_id="e" * 32,
            stored_sha256="e" * 64,
            title="",
            description="",
            tags=(),
        )
    )
    runtime.repository.store_embedding(
        current.asset_id,
        [1.0],
        runtime.service.vector_provider.model_id,
        index_content_hash(canonical_index_text(current)),
        current.updated_at,
    )
    for asset in (stale, empty):
        runtime.repository.store_embedding(
            asset.asset_id,
            [1.0],
            runtime.service.vector_provider.model_id,
            "f" * 64,
            asset.updated_at,
        )
    result = _run(runtime.service)
    assert result.enabled is False
    assert (result.scanned, result.indexed, result.skipped, result.failed) == (
        4,
        0,
        2,
        2,
    )
    assert runtime.repository.get_embedding(current.asset_id) is not None
    assert runtime.repository.get_embedding(missing.asset_id) is None
    assert runtime.repository.get_embedding(stale.asset_id) is None
    assert runtime.repository.get_embedding(empty.asset_id) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Changed title"),
        ("description", "Changed description"),
        ("original_filename", "changed.jpg"),
        ("kind", "changed-kind"),
        ("mime_type", "image/jpeg"),
    ],
)
def test_acceptance_each_scalar_index_field_change_is_stale(
    tmp_path,
    field,
    value,
):
    provider = RecordingProvider()
    runtime = _runtime(tmp_path, provider)
    asset = runtime.repository.add(_asset())
    _run(runtime.service)
    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE assets SET {} = ? WHERE asset_id = ?".format(field),
            (value, asset.asset_id),
        )
    result = _run(runtime.service)
    assert (result.indexed, result.failed) == (1, 0)
    assert len(provider.calls) == 2


def test_acceptance_tag_change_is_stale(tmp_path):
    provider = RecordingProvider()
    runtime = _runtime(tmp_path, provider)
    asset = runtime.repository.add(_asset())
    _run(runtime.service)
    runtime.repository.update_metadata(
        UpdateMetadataRequest(asset_id=asset.asset_id, tags=("changed",)),
        asset.updated_at,
    )
    result = _run(runtime.service)
    assert (result.indexed, result.failed) == (1, 0)
    assert len(provider.calls) == 2


@pytest.mark.parametrize("invalid_vector", [(0.1,), [float("-inf")]])
def test_acceptance_tuple_and_negative_infinity_vectors_fail(
    tmp_path,
    invalid_vector,
):
    runtime = _runtime(tmp_path, RecordingProvider(result=invalid_vector))
    asset = runtime.repository.add(_asset())
    result = _run(runtime.service)
    assert (result.indexed, result.failed) == (0, 1)
    assert runtime.repository.get_embedding(asset.asset_id) is None


def test_acceptance_cancelled_error_propagates(tmp_path):
    class CancelledProvider(RecordingProvider):
        async def embed(self, text):
            raise asyncio.CancelledError()

    runtime = _runtime(tmp_path, CancelledProvider())
    asset = runtime.repository.add(_asset())
    with pytest.raises(asyncio.CancelledError):
        _run(runtime.service)
    assert runtime.repository.get_embedding(asset.asset_id) is None


@pytest.mark.parametrize("failure_point", ["get", "conditional_store"])
def test_acceptance_repository_read_or_store_failure_isolated(
    tmp_path,
    monkeypatch,
    failure_point,
):
    from remember_me.core import StorageFailure

    runtime = _runtime(tmp_path)
    first = runtime.repository.add(_asset(asset_id="a" * 32, title="First"))
    second = runtime.repository.add(
        _asset(asset_id="c" * 32, stored_sha256="c" * 64, title="Second")
    )
    if failure_point == "get":
        original = runtime.repository.get_embedding

        def fail_first(asset_id):
            if asset_id == first.asset_id:
                raise StorageFailure()
            return original(asset_id)

        monkeypatch.setattr(runtime.repository, "get_embedding", fail_first)
    else:
        original = runtime.repository.store_embedding_if_asset_current

        def fail_first(expected_asset, record):
            if expected_asset.asset_id == first.asset_id:
                raise StorageFailure()
            return original(expected_asset, record)

        monkeypatch.setattr(
            runtime.repository,
            "store_embedding_if_asset_current",
            fail_first,
        )
    result = _run(runtime.service)
    assert (result.scanned, result.indexed, result.failed) == (2, 1, 1)
    assert runtime.repository.get_embedding(second.asset_id) is not None


def test_acceptance_repository_delete_failure_isolated(tmp_path, monkeypatch):
    from remember_me.core import StorageFailure

    runtime = _runtime(tmp_path)
    first = runtime.repository.add(_asset(asset_id="a" * 32, title="First"))
    second = runtime.repository.add(
        _asset(asset_id="c" * 32, stored_sha256="c" * 64, title="Second")
    )
    for asset in (first, second):
        runtime.repository.store_embedding(
            asset.asset_id,
            [1.0],
            "stale-model",
            "f" * 64,
            asset.updated_at,
        )
    original = runtime.repository.delete_embedding

    def fail_first(asset_id):
        if asset_id == first.asset_id:
            raise StorageFailure()
        return original(asset_id)

    monkeypatch.setattr(runtime.repository, "delete_embedding", fail_first)
    result = _run(runtime.service)
    assert (result.scanned, result.indexed, result.failed) == (2, 1, 1)
    assert runtime.repository.get_embedding(first.asset_id) is not None
    assert runtime.repository.get_embedding(second.asset_id) is not None


@pytest.mark.parametrize("limit", [False, 1.0, "10"])
def test_acceptance_additional_limit_validation(tmp_path, limit):
    runtime = _runtime(tmp_path)
    with pytest.raises(InvalidMetadata) as raised:
        _run(runtime.service, ReindexEmbeddingsRequest(limit=limit))
    assert raised.value.code == "invalid_metadata"


@pytest.mark.parametrize("asset_id", [None, " "])
def test_acceptance_non_string_or_blank_asset_id_is_unavailable(
    tmp_path,
    asset_id,
):
    runtime = _runtime(tmp_path)
    with pytest.raises(AssetUnavailable):
        _run(
            runtime.service,
            ReindexEmbeddingsRequest(asset_id=asset_id),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("original_filename", "changed.jpg"),
        ("kind", "changed-kind"),
        ("mime_type", "image/jpeg"),
        ("tags", ("changed",)),
    ],
)
def test_acceptance_cas_rejects_each_changed_index_field(
    tmp_path,
    field,
    value,
):
    repository = SQLiteAssetRepository(tmp_path)
    expected = repository.add(_asset())
    if field == "tags":
        with repository._connect() as connection:
            connection.execute(
                "DELETE FROM asset_tags WHERE asset_id = ?",
                (expected.asset_id,),
            )
            connection.execute(
                "INSERT INTO asset_tags "
                "(asset_id, tag_normalized, tag_display, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    expected.asset_id,
                    value[0].casefold(),
                    value[0],
                    expected.created_at,
                ),
            )
    else:
        with repository._connect() as connection:
            connection.execute(
                "UPDATE assets SET {} = ? WHERE asset_id = ?".format(field),
                (value, expected.asset_id),
            )
    record = EmbeddingRecord(
        asset_id=expected.asset_id,
        embedding=(0.1,),
        model_id="test/provider-v1",
        content_hash="d" * 64,
        updated_at=expected.updated_at,
    )
    assert repository.store_embedding_if_asset_current(expected, record) is False
    assert repository.get_embedding(expected.asset_id) is None


@pytest.mark.parametrize("serialized", ["not-json", "[true]", "[\"bad\"]"])
def test_acceptance_corrupt_embedding_storage_fails_closed(
    tmp_path,
    serialized,
):
    from remember_me.core import StorageFailure

    repository = SQLiteAssetRepository(tmp_path)
    asset = repository.add(_asset())
    with repository._connect() as connection:
        connection.execute(
            "INSERT INTO asset_embeddings "
            "(asset_id, embedding, model, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                asset.asset_id,
                serialized,
                "test/provider-v1",
                "d" * 64,
                asset.updated_at,
            ),
        )
    with pytest.raises(StorageFailure) as raised:
        repository.get_embedding(asset.asset_id)
    assert raised.value.code == "storage_failure"


def test_acceptance_factory_legacy_signatures_and_provider_isolation(tmp_path):
    default = create_local_runtime(tmp_path / "default")
    legacy_service = create_local_service(tmp_path / "legacy")
    assert isinstance(default.service.vector_provider, NullVectorProvider)
    assert isinstance(legacy_service.vector_provider, NullVectorProvider)
    assert legacy_service.vector_provider is not default.service.vector_provider
    provider = RecordingProvider()
    explicit = create_local_runtime(
        tmp_path / "explicit",
        vector_provider=provider,
    )
    assert explicit.service.vector_provider is provider
    assert explicit.repository is not provider
    assert explicit.blob_store is not provider


def test_acceptance_all_production_provider_embed_calls_are_awaited():
    import ast
    from pathlib import Path

    source_root = Path(__file__).parents[1] / "src"
    calls = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "embed"
            ):
                calls.append(path)
                assert isinstance(parents.get(node), ast.Await)
    assert calls == [
        source_root / "remember_me" / "core" / "service.py",
        source_root / "remember_me" / "core" / "service.py"
    ]
