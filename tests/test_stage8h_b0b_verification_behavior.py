# SPDX-License-Identifier: CPAL-1.0
"""Behavior, concurrency, compatibility, and security verification tests."""

import asyncio
import concurrent.futures
import hashlib
import inspect
import io
import sqlite3
import threading
from dataclasses import fields
from enum import IntEnum
from pathlib import Path

import pytest
from PIL import Image

from remember_me import PROJECT_VERSION, __version__
from remember_me.core import (
    AssetBlobVerificationResult,
    AssetVerificationCompletion,
    AssetVerificationPage,
    AssetVerificationRecord,
    AssetVerificationSnapshot,
    AssetVerificationTag,
    BeginAssetVerificationRequest,
    CompleteAssetVerificationRequest,
    DeleteAssetRequest,
    GetAssetRequest,
    IngestImageRequest,
    ImportAssetDisposition,
    ImportAssetRequest,
    ImportAssetTag,
    InvalidVerificationCursor,
    InvalidVerificationLimit,
    ListAssetVerificationPageRequest,
    ReindexEmbeddingsRequest,
    RememberMeCore,
    RememberMeService,
    ResolveAssetRequest,
    SearchAssetsRequest,
    UpdateMetadataRequest,
    VerificationAssetNotScanned,
    VerificationBlobBytesMismatch,
    VerificationBlobChecksumMismatch,
    VerificationBlobMissing,
    VerificationBlobSizeMismatch,
    VerificationBlobUnreadable,
    VerificationIncomplete,
    VerificationInternalError,
    VerificationPageOutOfOrder,
    VerificationRecordInvalid,
    VerificationSnapshotChanged,
    VerificationSnapshotClosed,
    VerificationSnapshotExpired,
    VerificationSnapshotInvalid,
    VerificationUnavailable,
    VerifyAssetBlobRequest,
)
from remember_me.core.contracts import AssetRepository
from remember_me.core.errors import StorageFailure
from remember_me.factory import create_local_runtime
from remember_me.imaging import PillowImageSanitizer
from remember_me.storage import SQLiteAssetRepository


CREATED = "2026-07-01T01:02:03+00:00"
UPDATED = "2026-07-02T04:05:06+00:00"
TAG_CREATED = "2026-07-01T02:03:04+00:00"


def _cleaned(color="blue"):
    image = Image.new("RGB", (8, 6), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    return PillowImageSanitizer().sanitize(
        output.getvalue(),
        "image/png",
    ).content


def _request(asset_id="a" * 32, color="blue", **changes):
    content = _cleaned(color)
    values = {
        "asset_id": asset_id,
        "source_sha256": hashlib.sha256(
            ("source-" + asset_id).encode()
        ).hexdigest(),
        "stored_sha256": hashlib.sha256(content).hexdigest(),
        "cleaned_bytes": content,
        "original_filename": asset_id[:4] + ".png",
        "mime_type": "image/png",
        "kind": "image",
        "decoded_bytes": len(content),
        "stored_bytes": len(content),
        "width": 8,
        "height": 6,
        "created_at": CREATED,
        "updated_at": UPDATED,
        "title": "Title " + asset_id[:2],
        "description": "Description",
        "tags": (
            ImportAssetTag("Travel", TAG_CREATED),
            ImportAssetTag("Work", UPDATED),
        ),
        "dry_run": False,
    }
    values.update(changes)
    return ImportAssetRequest(**values)


def _import(runtime, asset_id="a" * 32, color="blue", **changes):
    request = _request(asset_id, color, **changes)
    result = runtime.service.import_asset(request)
    assert result.disposition is ImportAssetDisposition.IMPORTED
    return request, result.asset


def _begin(runtime, kind="image"):
    return runtime.service.begin_asset_verification(
        BeginAssetVerificationRequest(kind=kind)
    )


def _page(runtime, snapshot, cursor="", limit=100):
    return runtime.service.list_asset_verification_page(
        ListAssetVerificationPageRequest(
            snapshot.snapshot_id,
            cursor,
            limit,
        )
    )


def _verify(runtime, snapshot, record, content, exact=True):
    return runtime.service.verify_asset_blob(
        VerifyAssetBlobRequest(
            snapshot.snapshot_id,
            record.asset_id,
            hashlib.sha256(content).hexdigest(),
            len(content),
            content if exact else None,
        )
    )


def _verify_page(runtime, snapshot, page, content_by_id):
    return tuple(
        _verify(runtime, snapshot, record, content_by_id[record.asset_id])
        for record in page.records
    )


def test_public_contract_models_signatures_and_version():
    operations = {
        "begin_asset_verification": (
            BeginAssetVerificationRequest,
            AssetVerificationSnapshot,
        ),
        "list_asset_verification_page": (
            ListAssetVerificationPageRequest,
            AssetVerificationPage,
        ),
        "verify_asset_blob": (
            VerifyAssetBlobRequest,
            AssetBlobVerificationResult,
        ),
        "complete_asset_verification": (
            CompleteAssetVerificationRequest,
            AssetVerificationCompletion,
        ),
    }
    for name, (request_type, result_type) in operations.items():
        assert name in RememberMeCore.__dict__
        assert tuple(
            inspect.signature(getattr(RememberMeService, name)).parameters
        ) == ("self", "request")
        assert request_type.__module__ == "remember_me.core.models"
        assert result_type.__module__ == "remember_me.core.models"
    assert PROJECT_VERSION == __version__ == "0.1.0"
    assert {
        "get_asset_verification_state",
        "count_assets_for_verification",
        "list_assets_for_verification_after",
        "get_asset_verification_integrity",
    }.issubset(AssetRepository.__dict__)
    assert "expected_bytes=" not in repr(
        VerifyAssetBlobRequest(
            "snapshot", "a" * 32, "b" * 64, 1, b"private bytes"
        )
    )


def test_verification_record_has_no_storage_locator():
    assert {item.name for item in fields(AssetVerificationRecord)} == {
        "asset_id", "source_sha256", "stored_sha256", "original_filename",
        "mime_type", "kind", "decoded_bytes", "stored_bytes", "width",
        "height", "created_at", "updated_at", "title", "description", "tags",
    }
    forbidden = {"stored_relpath", "blob_key", "data_root", "path"}
    for model in (
        AssetVerificationSnapshot,
        AssetVerificationRecord,
        AssetVerificationPage,
        AssetBlobVerificationResult,
        AssetVerificationCompletion,
    ):
        assert forbidden.isdisjoint({item.name for item in fields(model)})


def test_empty_inventory_and_one_asset_complete(tmp_path):
    empty = create_local_runtime(tmp_path / "empty")
    snapshot = _begin(empty)
    assert snapshot.total_count == snapshot.generation == 0
    assert len(snapshot.target_identity) == 64
    assert str(tmp_path) not in repr(snapshot)
    page = _page(empty, snapshot)
    assert page.records == ()
    assert page.has_more is False and page.next_cursor == ""
    completion = empty.service.complete_asset_verification(
        CompleteAssetVerificationRequest(snapshot.snapshot_id)
    )
    assert completion.complete and completion.unchanged
    assert completion.scanned_count == completion.blob_verified_count == 0

    one = create_local_runtime(tmp_path / "one")
    request, _asset = _import(one)
    snapshot = _begin(one)
    page = _page(one, snapshot, limit=1)
    record = page.records[0]
    assert record.tags == (
        AssetVerificationTag("Travel", TAG_CREATED),
        AssetVerificationTag("Work", UPDATED),
    )
    result = _verify(one, snapshot, record, request.cleaned_bytes)
    assert result.readable
    assert result.actual_sha256 == request.stored_sha256
    assert result.actual_size == len(request.cleaned_bytes)
    assert result.matches_expected_bytes is True
    assert _verify(one, snapshot, record, request.cleaned_bytes) == result
    completion = one.service.complete_asset_verification(
        CompleteAssetVerificationRequest(snapshot.snapshot_id)
    )
    assert completion.complete
    assert completion.scanned_count == completion.blob_verified_count == 1


def test_keyset_pages_boundaries_order_and_unexpected_detection(tmp_path):
    runtime = create_local_runtime(tmp_path)
    contents = {}
    for asset_id, color in (
        ("c" * 32, "red"),
        ("a" * 32, "blue"),
        ("d" * 32, "yellow"),
        ("b" * 32, "green"),
    ):
        request, _ = _import(runtime, asset_id, color)
        contents[asset_id] = request.cleaned_bytes
    snapshot = _begin(runtime)
    first = _page(runtime, snapshot, limit=2)
    assert [record.asset_id for record in first.records] == [
        "a" * 32, "b" * 32,
    ]
    assert first.has_more and first.next_cursor
    _verify_page(runtime, snapshot, first, contents)
    second = _page(runtime, snapshot, first.next_cursor, 2)
    assert [record.asset_id for record in second.records] == [
        "c" * 32, "d" * 32,
    ]
    assert not second.has_more and second.next_cursor == ""
    _verify_page(runtime, snapshot, second, contents)
    target = {record.asset_id for record in first.records + second.records}
    assert target - (target - {"d" * 32}) == {"d" * 32}
    completion = runtime.service.complete_asset_verification(
        CompleteAssetVerificationRequest(snapshot.snapshot_id)
    )
    assert completion.complete and completion.total_count == 4


@pytest.mark.parametrize("limit", [True, False, 0, -1, 501, 1.0, "1", None])
def test_invalid_limits_are_stable(tmp_path, limit):
    runtime = create_local_runtime(tmp_path)
    snapshot = _begin(runtime)
    with pytest.raises(InvalidVerificationLimit) as captured:
        _page(runtime, snapshot, limit=limit)
    assert str(captured.value) == "invalid_verification_limit"


def test_cursor_tamper_cross_snapshot_replay_and_order(tmp_path):
    runtime = create_local_runtime(tmp_path)
    contents = {}
    for asset_id, color in (("a" * 32, "blue"), ("b" * 32, "green")):
        request, _ = _import(runtime, asset_id, color)
        contents[asset_id] = request.cleaned_bytes
    first_snapshot = _begin(runtime)
    first = _page(runtime, first_snapshot, limit=1)
    with pytest.raises(VerificationIncomplete):
        _page(runtime, first_snapshot, first.next_cursor, 1)
    _verify_page(runtime, first_snapshot, first, contents)
    with pytest.raises(InvalidVerificationCursor):
        _page(runtime, first_snapshot, first.next_cursor + "x", 1)
    second_snapshot = _begin(runtime)
    with pytest.raises(InvalidVerificationCursor):
        _page(runtime, second_snapshot, first.next_cursor, 1)
    last = _page(runtime, first_snapshot, first.next_cursor, 1)
    _verify_page(runtime, first_snapshot, last, contents)
    with pytest.raises(VerificationPageOutOfOrder):
        _page(runtime, first_snapshot, first.next_cursor, 1)


def test_blob_failures_are_actual_safe_and_idempotent(tmp_path, monkeypatch):
    runtime = create_local_runtime(tmp_path)
    request, asset = _import(runtime)
    snapshot = _begin(runtime)
    record = _page(runtime, snapshot).records[0]
    with pytest.raises(VerificationAssetNotScanned):
        runtime.service.verify_asset_blob(
            VerifyAssetBlobRequest(
                snapshot.snapshot_id, "b" * 32,
                request.stored_sha256, len(request.cleaned_bytes),
            )
        )
    with pytest.raises(VerificationBlobChecksumMismatch):
        runtime.service.verify_asset_blob(
            VerifyAssetBlobRequest(
                snapshot.snapshot_id, record.asset_id,
                "0" * 64, len(request.cleaned_bytes),
            )
        )
    with pytest.raises(VerificationBlobSizeMismatch):
        runtime.service.verify_asset_blob(
            VerifyAssetBlobRequest(
                snapshot.snapshot_id, record.asset_id,
                request.stored_sha256, len(request.cleaned_bytes) + 1,
            )
        )
    with pytest.raises(VerificationBlobBytesMismatch):
        runtime.service.verify_asset_blob(
            VerifyAssetBlobRequest(
                snapshot.snapshot_id, record.asset_id,
                request.stored_sha256, len(request.cleaned_bytes),
                b"x" * len(request.cleaned_bytes),
            )
        )
    runtime.blob_store.delete(asset.stored_relpath)
    with pytest.raises(VerificationBlobMissing) as missing:
        _verify(runtime, snapshot, record, request.cleaned_bytes)
    assert str(tmp_path) not in str(missing.value)
    runtime.blob_store.put(asset.stored_relpath, request.cleaned_bytes)
    monkeypatch.setattr(
        runtime.blob_store,
        "read",
        lambda _key: (_ for _ in ()).throw(StorageFailure("C:\\private")),
    )
    with pytest.raises(VerificationBlobUnreadable) as unreadable:
        _verify(runtime, snapshot, record, request.cleaned_bytes)
    assert str(unreadable.value) == "verification_blob_unreadable"
    assert unreadable.value.__cause__ is None


def test_blob_hash_is_recomputed_from_actual_bytes(tmp_path):
    runtime = create_local_runtime(tmp_path)
    request, asset = _import(runtime)
    snapshot = _begin(runtime)
    record = _page(runtime, snapshot).records[0]
    path, _ = runtime.blob_store._resolve_blob(asset.stored_relpath)
    path.write_bytes(b"x" * len(request.cleaned_bytes))
    with pytest.raises(VerificationBlobChecksumMismatch):
        _verify(runtime, snapshot, record, request.cleaned_bytes)


def test_generation_mutations_noops_and_reads(tmp_path):
    runtime = create_local_runtime(tmp_path)
    identity, generation = runtime.repository.get_asset_verification_state()
    assert generation == 0 and len(identity) == 64
    request, asset = _import(runtime)
    assert runtime.repository.get_asset_verification_state() == (identity, 1)
    assert runtime.service.import_asset(request).disposition is (
        ImportAssetDisposition.SKIPPED_IDEMPOTENT
    )
    assert runtime.repository.get_asset_verification_state()[1] == 1
    runtime.service.update_metadata(
        UpdateMetadataRequest(asset.asset_id, title="Changed")
    )
    assert runtime.repository.get_asset_verification_state()[1] == 2
    runtime.service.update_metadata(
        UpdateMetadataRequest(asset.asset_id, title="Changed")
    )
    assert runtime.repository.get_asset_verification_state()[1] == 2
    before_reads = runtime.repository.get_asset_verification_state()
    runtime.service.get_asset(GetAssetRequest(asset.asset_id))
    runtime.service.resolve_asset(ResolveAssetRequest(asset.asset_id))
    asyncio.run(runtime.service.search_assets(SearchAssetsRequest(query="")))
    asyncio.run(runtime.service.reindex_embeddings(
        ReindexEmbeddingsRequest(asset_id=asset.asset_id)
    ))
    snapshot = _begin(runtime)
    record = _page(runtime, snapshot).records[0]
    _verify(runtime, snapshot, record, request.cleaned_bytes)
    runtime.service.complete_asset_verification(
        CompleteAssetVerificationRequest(snapshot.snapshot_id)
    )
    assert runtime.repository.get_asset_verification_state() == before_reads
    runtime.service.delete_asset(DeleteAssetRequest(asset.asset_id))
    assert runtime.repository.get_asset_verification_state()[1] == 3
    assert runtime.repository.delete(asset.asset_id) is False
    assert runtime.repository.get_asset_verification_state()[1] == 3


def test_ingest_and_dedup_generation_semantics(tmp_path):
    runtime = create_local_runtime(tmp_path)
    content = _cleaned("purple")
    first = runtime.service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="upload.png",
            mime_type="image/png",
        )
    )
    assert first.deduplicated is False
    assert runtime.repository.get_asset_verification_state()[1] == 1
    second = runtime.service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="other.png",
            mime_type="image/png",
        )
    )
    assert second.deduplicated is True
    assert second.asset.asset_id == first.asset.asset_id
    assert runtime.repository.get_asset_verification_state()[1] == 1


def test_generation_rollback_and_concurrent_connections(tmp_path, monkeypatch):
    original = SQLiteAssetRepository._increment_asset_generation

    def fail_generation(connection):
        original(connection)
        raise StorageFailure("forced")

    rollback = create_local_runtime(tmp_path / "rollback")
    state = rollback.repository.get_asset_verification_state()
    monkeypatch.setattr(
        rollback.repository,
        "_increment_asset_generation",
        fail_generation,
    )
    request = _request()
    with pytest.raises(StorageFailure):
        rollback.service.import_asset(request)
    assert rollback.repository.get_asset_verification_state() == state
    assert rollback.repository.get(request.asset_id) is None

    root = tmp_path / "concurrent"
    runtimes = [create_local_runtime(root) for _ in range(8)]

    def import_one(index):
        return runtimes[index].service.import_asset(
            _request(
                "{:032x}".format(index + 1),
                color=(index * 20, 10, 200),
            )
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(import_one, range(8)))
    assert all(
        result.disposition is ImportAssetDisposition.IMPORTED
        for result in results
    )
    assert runtimes[0].repository.get_asset_verification_state()[1] == 8


def test_generation_failure_rolls_back_update_and_delete(tmp_path, monkeypatch):
    runtime = create_local_runtime(tmp_path)
    request, asset = _import(runtime)
    before_state = runtime.repository.get_asset_verification_state()
    before_asset = runtime.repository.get(asset.asset_id)
    original = SQLiteAssetRepository._increment_asset_generation

    def fail_generation(connection):
        original(connection)
        raise StorageFailure("forced")

    monkeypatch.setattr(
        runtime.repository,
        "_increment_asset_generation",
        fail_generation,
    )
    with pytest.raises(StorageFailure):
        runtime.service.update_metadata(
            UpdateMetadataRequest(asset.asset_id, title="Must roll back")
        )
    assert runtime.repository.get_asset_verification_state() == before_state
    assert runtime.repository.get(asset.asset_id) == before_asset
    with pytest.raises(StorageFailure):
        runtime.service.delete_asset(DeleteAssetRequest(asset.asset_id))
    assert runtime.repository.get_asset_verification_state() == before_state
    assert runtime.repository.get(asset.asset_id) == before_asset
    assert runtime.blob_store.read(asset.stored_relpath) == request.cleaned_bytes


def test_old_database_identity_generation_survive_reopen(tmp_path):
    with sqlite3.connect(str(tmp_path / "assets.sqlite3")) as connection:
        connection.execute(
            """
            CREATE TABLE assets (
                asset_id TEXT PRIMARY KEY,
                source_sha256 TEXT NOT NULL,
                stored_sha256 TEXT NOT NULL UNIQUE,
                stored_relpath TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                kind TEXT NOT NULL,
                decoded_bytes INTEGER NOT NULL,
                stored_bytes INTEGER NOT NULL,
                width INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
    first = SQLiteAssetRepository(tmp_path)
    state = first.get_asset_verification_state()
    assert state[1] == 0
    assert SQLiteAssetRepository(tmp_path).get_asset_verification_state() == state


def test_existing_asset_tag_and_embedding_survive_state_initialization(tmp_path):
    runtime = create_local_runtime(tmp_path)
    request, asset = _import(runtime)
    runtime.repository.store_embedding(
        asset.asset_id,
        (0.25, 0.75),
        "model",
        "f" * 64,
        asset.updated_at,
    )
    with runtime.repository._connect() as connection:
        before = {
            table: connection.execute(
                "SELECT * FROM " + table + " ORDER BY 1"
            ).fetchall()
            for table in ("assets", "asset_tags", "asset_embeddings")
        }
        connection.execute("DROP TABLE asset_verification_state")
    reopened = SQLiteAssetRepository(tmp_path)
    with reopened._connect() as connection:
        after = {
            table: connection.execute(
                "SELECT * FROM " + table + " ORDER BY 1"
            ).fetchall()
            for table in ("assets", "asset_tags", "asset_embeddings")
        }
    assert {
        table: [tuple(row) for row in rows]
        for table, rows in after.items()
    } == {
        table: [tuple(row) for row in rows]
        for table, rows in before.items()
    }
    assert reopened.get(asset.asset_id).stored_sha256 == request.stored_sha256
    assert reopened.get_asset_verification_state()[1] == 0


def test_incompatible_duplicate_old_database_fails_closed(tmp_path):
    with sqlite3.connect(str(tmp_path / "assets.sqlite3")) as connection:
        connection.execute(
            """
            CREATE TABLE assets (
                asset_id TEXT,
                source_sha256 TEXT NOT NULL,
                stored_sha256 TEXT NOT NULL,
                stored_relpath TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                kind TEXT NOT NULL,
                decoded_bytes INTEGER NOT NULL,
                stored_bytes INTEGER NOT NULL,
                width INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        for asset_id in ("a" * 32, "b" * 32):
            connection.execute(
                """
                INSERT INTO assets VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    asset_id,
                    "c" * 64,
                    "d" * 64,
                    "assets/dd/" + "d" * 64 + ".png",
                    "image.png",
                    "image/png",
                    "image",
                    1,
                    1,
                    1,
                    1,
                    CREATED,
                ),
            )
    with pytest.raises(StorageFailure):
        SQLiteAssetRepository(tmp_path)


def test_snapshot_changes_before_between_and_after_inventory(tmp_path):
    first = create_local_runtime(tmp_path / "before")
    second = create_local_runtime(tmp_path / "before")
    snapshot = _begin(first)
    _import(second)
    with pytest.raises(VerificationSnapshotChanged):
        _page(first, snapshot)
    with pytest.raises(VerificationSnapshotChanged):
        _page(first, snapshot)

    first = create_local_runtime(tmp_path / "between")
    second = create_local_runtime(tmp_path / "between")
    request, _ = _import(first)
    snapshot = _begin(first)
    page = _page(first, snapshot)
    _verify(first, snapshot, page.records[0], request.cleaned_bytes)
    _import(second, "b" * 32, "green")
    with pytest.raises(VerificationSnapshotChanged):
        first.service.complete_asset_verification(
            CompleteAssetVerificationRequest(snapshot.snapshot_id)
        )


def test_begin_detects_mutation_during_count(tmp_path, monkeypatch):
    first = create_local_runtime(tmp_path)
    second = create_local_runtime(tmp_path)
    original = first.repository.count_assets_for_verification

    def mutate_during_count(kind):
        count = original(kind)
        _import(second)
        return count

    monkeypatch.setattr(
        first.repository,
        "count_assets_for_verification",
        mutate_during_count,
    )
    with pytest.raises(VerificationSnapshotChanged):
        _begin(first)


def test_snapshot_changes_during_page_blob_and_finalize(
    tmp_path,
    monkeypatch,
):
    first = create_local_runtime(tmp_path / "page")
    second = create_local_runtime(tmp_path / "page")
    _import(first)
    snapshot = _begin(first)
    original_page = first.repository.list_assets_for_verification_after

    def mutate_after_page(*args):
        page = original_page(*args)
        _import(second, "b" * 32, "green")
        return page

    monkeypatch.setattr(
        first.repository,
        "list_assets_for_verification_after",
        mutate_after_page,
    )
    with pytest.raises(VerificationSnapshotChanged):
        _page(first, snapshot)

    first = create_local_runtime(tmp_path / "blob")
    second = create_local_runtime(tmp_path / "blob")
    request, _ = _import(first)
    snapshot = _begin(first)
    record = _page(first, snapshot).records[0]
    original_read = first.blob_store.read

    def mutate_after_read(key):
        content = original_read(key)
        _import(second, "b" * 32, "green")
        return content

    monkeypatch.setattr(first.blob_store, "read", mutate_after_read)
    with pytest.raises(VerificationSnapshotChanged):
        _verify(first, snapshot, record, request.cleaned_bytes)

    first = create_local_runtime(tmp_path / "finalize")
    second = create_local_runtime(tmp_path / "finalize")
    request, _ = _import(first)
    snapshot = _begin(first)
    record = _page(first, snapshot).records[0]
    _verify(first, snapshot, record, request.cleaned_bytes)
    original_integrity = first.repository.get_asset_verification_integrity

    def mutate_during_integrity(kind):
        result = original_integrity(kind)
        _import(second, "b" * 32, "green")
        return result

    monkeypatch.setattr(
        first.repository,
        "get_asset_verification_integrity",
        mutate_during_integrity,
    )
    with pytest.raises(VerificationSnapshotChanged):
        first.service.complete_asset_verification(
            CompleteAssetVerificationRequest(snapshot.snapshot_id)
        )


def test_session_invalid_expired_closed_and_limit(tmp_path):
    runtime = create_local_runtime(tmp_path)
    with pytest.raises(VerificationSnapshotInvalid):
        runtime.service.list_asset_verification_page(
            ListAssetVerificationPageRequest("x" * 40)
        )
    runtime.service.verification_session_limit = 2
    first = _begin(runtime)
    _begin(runtime)
    with pytest.raises(VerificationUnavailable):
        _begin(runtime)
    runtime.service._verification_sessions[first.snapshot_id].last_used_at -= (
        runtime.service.verification_session_ttl_seconds + 1
    )
    with pytest.raises(VerificationSnapshotExpired):
        _page(runtime, first)

    closed = create_local_runtime(tmp_path / "closed")
    snapshot = _begin(closed)
    _page(closed, snapshot)
    closed.service.complete_asset_verification(
        CompleteAssetVerificationRequest(snapshot.snapshot_id)
    )
    with pytest.raises(VerificationSnapshotClosed):
        closed.service.complete_asset_verification(
            CompleteAssetVerificationRequest(snapshot.snapshot_id)
        )
    with pytest.raises(VerificationSnapshotClosed):
        _page(closed, snapshot)


def test_integrity_counts_and_incomplete_finalization(tmp_path, monkeypatch):
    runtime = create_local_runtime(tmp_path)
    request, _ = _import(runtime)
    snapshot = _begin(runtime)
    page = _page(runtime, snapshot)
    with pytest.raises(VerificationIncomplete):
        runtime.service.complete_asset_verification(
            CompleteAssetVerificationRequest(snapshot.snapshot_id)
        )
    _verify(runtime, snapshot, page.records[0], request.cleaned_bytes)
    monkeypatch.setattr(
        runtime.repository,
        "get_asset_verification_integrity",
        lambda _kind: (1, 0, 1),
    )
    completion = runtime.service.complete_asset_verification(
        CompleteAssetVerificationRequest(snapshot.snapshot_id)
    )
    assert completion.complete is False
    assert completion.duplicate_stored_sha_count == 1


def test_malformed_and_internal_failures_do_not_leak(tmp_path, monkeypatch):
    runtime = create_local_runtime(tmp_path)
    snapshot = _begin(runtime)

    class Hostile:
        def __repr__(self):
            return "C:\\private\\assets.sqlite3 secret body"

    monkeypatch.setattr(
        runtime.repository,
        "list_assets_for_verification_after",
        lambda *_args: ((Hostile(),), False),
    )
    with pytest.raises(VerificationRecordInvalid) as malformed:
        _page(runtime, snapshot)
    assert "private" not in str(malformed.value)
    assert malformed.value.__cause__ is None

    other = create_local_runtime(tmp_path / "internal")
    monkeypatch.setattr(
        other.repository,
        "count_assets_for_verification",
        lambda _kind: (_ for _ in ()).throw(
            sqlite3.OperationalError("C:\\private\\assets.sqlite3 token")
        ),
    )
    with pytest.raises(VerificationInternalError) as internal:
        _begin(other)
    assert str(internal.value) == "verification_internal_error"
    assert internal.value.__cause__ is None


def test_base_exceptions_propagate(tmp_path, monkeypatch):
    runtime = create_local_runtime(tmp_path)
    monkeypatch.setattr(
        runtime.repository,
        "count_assets_for_verification",
        lambda _kind: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        _begin(runtime)

    runtime = create_local_runtime(tmp_path / "blob")
    request, _ = _import(runtime)
    snapshot = _begin(runtime)
    record = _page(runtime, snapshot).records[0]
    monkeypatch.setattr(
        runtime.blob_store,
        "read",
        lambda _key: (_ for _ in ()).throw(SystemExit()),
    )
    with pytest.raises(SystemExit):
        _verify(runtime, snapshot, record, request.cleaned_bytes)


def test_invalid_kind_and_max_limit(tmp_path):
    runtime = create_local_runtime(tmp_path)
    with pytest.raises(VerificationRecordInvalid):
        _begin(runtime, "file")
    snapshot = _begin(runtime)
    page = _page(runtime, snapshot, limit=500)
    assert page.records == ()


def test_repeated_blob_verification_fresh_reads_and_revokes_success(
    tmp_path,
):
    runtime = create_local_runtime(tmp_path)
    request, asset = _import(runtime)
    snapshot = _begin(runtime)
    record = _page(runtime, snapshot).records[0]
    verification_request = VerifyAssetBlobRequest(
        snapshot.snapshot_id,
        record.asset_id,
        record.stored_sha256,
        record.stored_bytes,
        request.cleaned_bytes,
    )
    runtime.service.verify_asset_blob(verification_request)
    path, _ = runtime.blob_store._resolve_blob(asset.stored_relpath)
    path.write_bytes(b"x" * len(request.cleaned_bytes))

    with pytest.raises(VerificationBlobChecksumMismatch):
        runtime.service.verify_asset_blob(verification_request)
    session = runtime.service._verification_sessions[snapshot.snapshot_id]
    assert session.blob_verified_count == 0
    assert record.asset_id not in session.verified_results
    with pytest.raises(VerificationIncomplete):
        runtime.service.complete_asset_verification(
            CompleteAssetVerificationRequest(snapshot.snapshot_id)
        )


@pytest.mark.parametrize("failure", ["corrupt", "missing", "unreadable"])
def test_finalize_fresh_rescan_rejects_changed_blob(
    tmp_path,
    monkeypatch,
    failure,
):
    runtime = create_local_runtime(tmp_path)
    request, asset = _import(runtime)
    snapshot = _begin(runtime)
    record = _page(runtime, snapshot).records[0]
    _verify(runtime, snapshot, record, request.cleaned_bytes)
    path, _ = runtime.blob_store._resolve_blob(asset.stored_relpath)
    if failure == "corrupt":
        path.write_bytes(b"x" * len(request.cleaned_bytes))
        expected = VerificationBlobChecksumMismatch
    elif failure == "missing":
        path.unlink()
        expected = VerificationBlobMissing
    else:
        monkeypatch.setattr(
            runtime.blob_store,
            "read",
            lambda _key: (_ for _ in ()).throw(
                StorageFailure("C:\\private\\secret")
            ),
        )
        expected = VerificationBlobUnreadable

    with pytest.raises(expected) as captured:
        runtime.service.complete_asset_verification(
            CompleteAssetVerificationRequest(snapshot.snapshot_id)
        )
    assert "private" not in str(captured.value)
    with pytest.raises(VerificationSnapshotClosed):
        runtime.service.complete_asset_verification(
            CompleteAssetVerificationRequest(snapshot.snapshot_id)
        )


def test_finalize_fresh_rescan_checks_prior_pages_and_is_bounded(
    tmp_path,
    monkeypatch,
):
    runtime = create_local_runtime(tmp_path)
    contents = {}
    assets = {}
    for index in range(503):
        asset_id = "{:032x}".format(index + 1)
        request, asset = _import(
            runtime,
            asset_id,
            (
                index % 256,
                (index // 256) % 256,
                (index * 17) % 256,
            ),
        )
        contents[asset_id] = request.cleaned_bytes
        assets[asset_id] = asset
    snapshot = _begin(runtime)
    cursor = ""
    first_asset_id = ""
    while True:
        page = _page(runtime, snapshot, cursor, 250)
        if not first_asset_id:
            first_asset_id = page.records[0].asset_id
        _verify_page(runtime, snapshot, page, contents)
        if not page.has_more:
            break
        cursor = page.next_cursor
    first = assets[first_asset_id]
    path, _ = runtime.blob_store._resolve_blob(first.stored_relpath)
    path.write_bytes(b"x" * len(contents[first_asset_id]))
    limits = []
    original = runtime.repository.list_assets_for_verification_after

    def bounded(*args):
        limits.append(args[2])
        return original(*args)

    monkeypatch.setattr(
        runtime.repository,
        "list_assets_for_verification_after",
        bounded,
    )
    with pytest.raises(VerificationBlobChecksumMismatch):
        runtime.service.complete_asset_verification(
            CompleteAssetVerificationRequest(snapshot.snapshot_id)
        )
    assert limits
    assert max(limits) <= 500


def test_verification_exact_builtin_types_are_enforced(tmp_path):
    runtime = create_local_runtime(tmp_path)
    request, _asset = _import(runtime)
    snapshot = _begin(runtime)
    record = _page(runtime, snapshot).records[0]

    class LimitEnum(IntEnum):
        ONE = 1

    class IntSubclass(int):
        pass

    class HostileStr(str):
        calls = 0

        def _fail(self, *_args, **_kwargs):
            type(self).calls += 1
            raise RuntimeError("C:\\private\\TOKEN")

        __len__ = _fail
        __str__ = _fail
        __repr__ = _fail
        strip = _fail

    class HostileBytes(bytes):
        calls = 0

        def _fail(self, *_args, **_kwargs):
            type(self).calls += 1
            raise RuntimeError("BODY_SECRET")

        __len__ = _fail
        __bytes__ = _fail
        __repr__ = _fail

    for limit in (True, LimitEnum.ONE, IntSubclass(1)):
        fresh = _begin(runtime)
        with pytest.raises(InvalidVerificationLimit):
            _page(runtime, fresh, limit=limit)

    hostile_text_cases = (
        ListAssetVerificationPageRequest(HostileStr("x" * 43)),
        ListAssetVerificationPageRequest(
            snapshot.snapshot_id,
            HostileStr("cursor"),
        ),
    )
    for candidate in hostile_text_cases:
        with pytest.raises(
            (VerificationSnapshotInvalid, InvalidVerificationCursor)
        ) as captured:
            runtime.service.list_asset_verification_page(candidate)
        assert "private" not in str(captured.value)
    for changes, expected in (
        ({"asset_id": HostileStr(record.asset_id)},
         VerificationAssetNotScanned),
        ({"expected_sha256": HostileStr(record.stored_sha256)},
         VerificationBlobChecksumMismatch),
        ({"expected_bytes": HostileBytes(request.cleaned_bytes)},
         VerificationBlobBytesMismatch),
        ({"expected_bytes": bytearray(request.cleaned_bytes)},
         VerificationBlobBytesMismatch),
        ({"expected_bytes": memoryview(request.cleaned_bytes)},
         VerificationBlobBytesMismatch),
    ):
        values = {
            "snapshot_id": snapshot.snapshot_id,
            "asset_id": record.asset_id,
            "expected_sha256": record.stored_sha256,
            "expected_size": record.stored_bytes,
            "expected_bytes": request.cleaned_bytes,
        }
        values.update(changes)
        with pytest.raises(expected) as captured:
            runtime.service.verify_asset_blob(
                VerifyAssetBlobRequest(**values)
            )
        assert "private" not in str(captured.value)
        assert "BODY_SECRET" not in str(captured.value)
    assert HostileStr.calls == 0
    assert HostileBytes.calls == 0


def test_begin_third_state_check_rejects_post_count_mutation(
    tmp_path,
    monkeypatch,
):
    first = create_local_runtime(tmp_path)
    second = create_local_runtime(tmp_path)
    original = first.service._read_asset_verification_state
    calls = {"count": 0}

    def mutate_after_second_state():
        calls["count"] += 1
        state = original()
        if calls["count"] == 2:
            _import(second)
        return state

    monkeypatch.setattr(
        first.service,
        "_read_asset_verification_state",
        mutate_after_second_state,
    )
    with pytest.raises(VerificationSnapshotChanged):
        _begin(first)
    assert first.service._verification_sessions == {}


def test_finalize_state_is_exclusive_but_other_session_can_progress(
    tmp_path,
    monkeypatch,
):
    runtime = create_local_runtime(tmp_path)
    request, _asset = _import(runtime)
    first = _begin(runtime)
    first_page = _page(runtime, first)
    _verify_page(
        runtime,
        first,
        first_page,
        {first_page.records[0].asset_id: request.cleaned_bytes},
    )
    second = _begin(runtime)
    entered = threading.Event()
    release = threading.Event()
    original = runtime.repository.list_assets_for_verification_after

    def block_finalizer(*args):
        if threading.current_thread().name == "finalizer":
            entered.set()
            assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(
        runtime.repository,
        "list_assets_for_verification_after",
        block_finalizer,
    )
    results = {}

    def finalize():
        try:
            results["first"] = runtime.service.complete_asset_verification(
                CompleteAssetVerificationRequest(first.snapshot_id)
            )
        except BaseException as exc:
            results["first"] = exc

    thread = threading.Thread(target=finalize, name="finalizer")
    thread.start()
    assert entered.wait(5)
    second_page = _page(runtime, second)
    assert len(second_page.records) == 1
    with pytest.raises(VerificationIncomplete):
        runtime.service.complete_asset_verification(
            CompleteAssetVerificationRequest(first.snapshot_id)
        )
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert results["first"].complete is True


def test_process_affinity_and_fresh_rescan_are_documented():
    text = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "public-api-contract.md"
    ).read_text(encoding="utf-8")
    text = " ".join(text.split())
    for phrase in (
        "exact `RememberMeService` instance",
        "same service/process",
        "sticky routing",
        "offline single-process",
        "`verification_snapshot_invalid`",
        "fresh bounded keyset rescan",
        "single-writer or maintenance window",
        "future external filesystem write",
    ):
        assert phrase in text
