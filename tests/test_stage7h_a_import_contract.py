# SPDX-License-Identifier: CPAL-1.0
import asyncio
import concurrent.futures
import hashlib
import io
import sqlite3
import threading
import traceback
from dataclasses import fields, replace
from datetime import datetime, timezone

import json
from dataclasses import asdict
from test_metadata_normalization import UNICODE_CASES
from remember_me.core.normalization import tag_comparison_key
from remember_me.mcp.schemas import asset_to_public_dict
from remember_me.standalone.schemas import asset_to_public_response

import pytest
from PIL import Image

from remember_me import PROJECT_VERSION, __version__
from remember_me.core.contracts import ImportClassificationState
from remember_me.core import (
    AssetFileUnavailable,
    AssetIdConflict,
    DeleteAssetRequest,
    GetAssetRequest,
    BlobUnavailableOrCorrupt,
    ImageMimeMismatch,
    ImportAssetDisposition,
    ImportAssetRequest,
    ImportAssetResult,
    ImportAssetTag,
    ImportMetadataValidationError,
    InvalidImage,
    InvalidImportRecord,
    ReindexEmbeddingsRequest,
    RememberMeCore,
    RememberMeService,
    ResolveAssetRequest,
    SearchAssetsRequest,
    StoredShaMismatch,
    StoredShaOwnershipConflict,
    StorageFailure,
    UnsupportedAssetKind,
    UnsupportedImageFormat,
    UpdateMetadataRequest,
)
from remember_me.factory import create_local_runtime
from remember_me.imaging import PillowImageSanitizer
from remember_me.search import NullVectorProvider
from remember_me.storage import LocalContentStore, SQLiteAssetRepository


CREATED = "2026-07-01T01:02:03+00:00"
UPDATED = "2026-07-02T04:05:06+00:00"
TAG_CREATED = "2026-07-01T02:03:04+00:00"


def _encoded_image(image_format="PNG", color="blue"):
    image = Image.new("RGB", (8, 6), color)
    output = io.BytesIO()
    image.save(output, format=image_format, quality=95)
    image.close()
    return output.getvalue()


def _cleaned(image_format="PNG", color="blue"):
    mime = "image/png" if image_format == "PNG" else "image/jpeg"
    return PillowImageSanitizer().sanitize(
        _encoded_image(image_format, color),
        mime,
    ).content


def _request(content=None, mime_type="image/png", **changes):
    content = content if content is not None else _cleaned()
    with Image.open(io.BytesIO(content)) as image:
        width, height = image.size
    values = {
        "asset_id": "a" * 32,
        "source_sha256": "1" * 64,
        "stored_sha256": hashlib.sha256(content).hexdigest(),
        "cleaned_bytes": content,
        "original_filename": "legacy.png" if mime_type == "image/png" else "legacy.jpg",
        "mime_type": mime_type,
        "kind": "image",
        "decoded_bytes": 321,
        "stored_bytes": len(content),
        "width": width,
        "height": height,
        "created_at": CREATED,
        "updated_at": UPDATED,
        "title": "Legacy title",
        "description": "Legacy description",
        "tags": (
            ImportAssetTag("Travel", TAG_CREATED),
            ImportAssetTag("Work", UPDATED),
        ),
        "dry_run": False,
    }
    values.update(changes)
    return ImportAssetRequest(**values)


def _counts(repository):
    with repository._connect() as connection:
        return tuple(
            connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in ("assets", "asset_tags", "asset_embeddings")
        )


def _stored_files(blob_store):
    return [
        path
        for path in blob_store.assets_root.rglob("*")
        if path.is_file() and blob_store.temp_root not in path.parents
    ]


def test_public_contract_and_version_are_exported():
    assert "import_asset" in RememberMeCore.__dict__
    assert ImportAssetRequest.__module__ == "remember_me.core.models"
    assert ImportAssetResult.__module__ == "remember_me.core.models"
    assert {field.name for field in fields(ImportAssetRequest)} == {
        "asset_id", "source_sha256", "stored_sha256", "cleaned_bytes",
        "original_filename", "mime_type", "kind", "decoded_bytes",
        "stored_bytes", "width", "height", "created_at", "updated_at",
        "title", "description", "tags", "dry_run",
    }
    assert "cleaned_bytes=" not in repr(_request())
    assert PROJECT_VERSION == __version__ == "0.1.0.dev7"


@pytest.mark.parametrize(
    ("image_format", "mime_type", "suffix"),
    [("PNG", "image/png", ".png"), ("JPEG", "image/jpeg", ".jpg")],
)
def test_import_preserves_identity_bytes_metadata_and_history(
    tmp_path, image_format, mime_type, suffix
):
    runtime = create_local_runtime(tmp_path)
    content = _cleaned(image_format)
    request = _request(
        content,
        mime_type,
        asset_id=("a" if image_format == "PNG" else "b") * 32,
        original_filename="legacy" + suffix,
    )
    result = runtime.service.import_asset(request)

    assert result.disposition is ImportAssetDisposition.IMPORTED
    assert result.asset.asset_id == request.asset_id
    assert result.asset.created_at == CREATED
    assert result.asset.updated_at == UPDATED
    assert result.tags == tuple(sorted(request.tags, key=lambda tag: tag.value.casefold()))
    assert runtime.repository.get_import_tags(request.asset_id) == result.tags
    assert runtime.blob_store.read(result.asset.stored_relpath) == content
    assert result.asset.stored_relpath.endswith(suffix)
    assert result.asset.source_sha256 == "1" * 64
    assert result.asset.source_sha256 != result.asset.stored_sha256
    assert _counts(runtime.repository) == (1, 2, 0)


class _ValidationOnlySanitizer(PillowImageSanitizer):
    def sanitize(self, content, claimed_mime_type):
        raise AssertionError("import_must_not_reencode")


def test_import_never_calls_sanitize_or_reencodes(tmp_path):
    repository = SQLiteAssetRepository(tmp_path)
    blobs = LocalContentStore(tmp_path)
    service = RememberMeService(
        repository,
        blobs,
        _ValidationOnlySanitizer(),
        clock=None,
        vector_provider=NullVectorProvider(),
    )
    request = _request()
    result = service.import_asset(request)
    assert blobs.read(result.asset.stored_relpath) == request.cleaned_bytes


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"asset_id": "A" * 32}, InvalidImportRecord),
        ({"source_sha256": "bad"}, InvalidImportRecord),
        ({"stored_sha256": "0" * 64}, StoredShaMismatch),
        ({"stored_bytes": 1}, InvalidImportRecord),
        ({"decoded_bytes": 0}, InvalidImportRecord),
        ({"width": 99}, ImportMetadataValidationError),
        ({"height": 99}, ImportMetadataValidationError),
        ({"kind": "file"}, UnsupportedAssetKind),
        ({"created_at": "2026-07-01T01:02:03"}, ImportMetadataValidationError),
        ({"updated_at": "2026-06-01T01:02:03+00:00"}, ImportMetadataValidationError),
        ({"original_filename": "../legacy.png"}, ImportMetadataValidationError),
        ({"title": " title "}, ImportMetadataValidationError),
        ({"tags": (
            ImportAssetTag("Travel", TAG_CREATED),
            ImportAssetTag("travel", TAG_CREATED),
        )}, ImportMetadataValidationError),
    ],
)
def test_import_rejects_invalid_records(tmp_path, change, error):
    runtime = create_local_runtime(tmp_path)
    with pytest.raises(error) as raised:
        runtime.service.import_asset(_request(**change))
    assert _counts(runtime.repository) == (0, 0, 0)
    assert not _stored_files(runtime.blob_store)
    assert not list(runtime.blob_store.temp_root.iterdir())
    message = str(raised.value)
    assert str(tmp_path) not in message
    assert "PNG" not in message


def test_import_rejects_mime_mismatch_and_unsupported_format(tmp_path):
    runtime = create_local_runtime(tmp_path)
    with pytest.raises(ImageMimeMismatch):
        runtime.service.import_asset(_request(mime_type="image/jpeg"))

    gif = _encoded_image("GIF")
    request = _request(
        gif,
        "image/gif",
        original_filename="legacy.gif",
        stored_sha256=hashlib.sha256(gif).hexdigest(),
        stored_bytes=len(gif),
    )
    with pytest.raises(UnsupportedImageFormat):
        runtime.service.import_asset(request)


def test_dry_run_is_write_free_and_matches_real_decision(tmp_path):
    runtime = create_local_runtime(tmp_path)
    request = _request(dry_run=True)
    first = runtime.service.import_asset(request)
    assert first.disposition is ImportAssetDisposition.WOULD_IMPORT
    assert _counts(runtime.repository) == (0, 0, 0)
    assert not _stored_files(runtime.blob_store)
    assert not list(runtime.blob_store.temp_root.iterdir())

    imported = runtime.service.import_asset(replace(request, dry_run=False))
    assert imported.disposition is ImportAssetDisposition.IMPORTED
    before = _counts(runtime.repository)
    skipped = runtime.service.import_asset(request)
    assert skipped.disposition is ImportAssetDisposition.WOULD_SKIP_IDEMPOTENT
    assert _counts(runtime.repository) == before


def test_idempotency_and_stable_conflicts(tmp_path):
    runtime = create_local_runtime(tmp_path)
    request = _request()
    first = runtime.service.import_asset(request)
    second = runtime.service.import_asset(request)
    assert first.disposition is ImportAssetDisposition.IMPORTED
    assert second.disposition is ImportAssetDisposition.SKIPPED_IDEMPOTENT

    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(replace(request, title="Different"))
    other = _cleaned(color="red")
    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(_request(other, asset_id=request.asset_id))
    assert len(_stored_files(runtime.blob_store)) == 1

    with pytest.raises(StoredShaOwnershipConflict):
        runtime.service.import_asset(replace(request, asset_id="c" * 32))
    assert _counts(runtime.repository) == (1, 2, 0)


def test_existing_blob_reuse_corruption_and_missing_blob_fail_closed(tmp_path):
    runtime = create_local_runtime(tmp_path)
    request = _request()
    expected_key = "assets/{}/{}.png".format(
        request.stored_sha256[:2], request.stored_sha256
    )
    assert runtime.blob_store.put(expected_key, request.cleaned_bytes) is True
    result = runtime.service.import_asset(request)
    assert result.disposition is ImportAssetDisposition.IMPORTED

    runtime.blob_store.delete(expected_key)
    with pytest.raises(BlobUnavailableOrCorrupt):
        runtime.service.import_asset(request)

    second_root = tmp_path / "corrupt"
    second = create_local_runtime(second_root)
    corrupt_request = _request(asset_id="d" * 32)
    corrupt_path = (
        second.blob_store.data_root
        / "assets"
        / corrupt_request.stored_sha256[:2]
        / (corrupt_request.stored_sha256 + ".png")
    )
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_bytes(b"corrupt")
    with pytest.raises(BlobUnavailableOrCorrupt):
        second.service.import_asset(corrupt_request)
    assert _counts(second.repository) == (0, 0, 0)


def test_repository_failure_cleans_only_new_blob(tmp_path, monkeypatch):
    runtime = create_local_runtime(tmp_path / "new")
    request = _request()
    monkeypatch.setattr(
        runtime.repository,
        "add_import",
        lambda *_args: (_ for _ in ()).throw(StorageFailure("injected")),
    )
    with pytest.raises(StorageFailure, match="injected"):
        runtime.service.import_asset(request)
    assert not _stored_files(runtime.blob_store)
    assert not list(runtime.blob_store.temp_root.iterdir())

    existing = create_local_runtime(tmp_path / "existing")
    key = "assets/{}/{}.png".format(
        request.stored_sha256[:2], request.stored_sha256
    )
    existing.blob_store.put(key, request.cleaned_bytes)
    monkeypatch.setattr(
        existing.repository,
        "add_import",
        lambda *_args: (_ for _ in ()).throw(StorageFailure("injected")),
    )
    with pytest.raises(StorageFailure, match="injected"):
        existing.service.import_asset(request)
    assert existing.blob_store.read(key) == request.cleaned_bytes


def test_identical_imports_are_safe_across_runtime_instances(tmp_path):
    first = create_local_runtime(tmp_path)
    second = create_local_runtime(tmp_path)
    request = _request()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda service: service.import_asset(request),
            (first.service, second.service),
        ))
    assert {result.disposition for result in results} == {
        ImportAssetDisposition.IMPORTED,
        ImportAssetDisposition.SKIPPED_IDEMPOTENT,
    }
    assert _counts(first.repository) == (1, 2, 0)
    assert len(_stored_files(first.blob_store)) == 1
    assert not list(first.blob_store.temp_root.iterdir())


def test_conflicting_imports_are_safe_across_runtime_instances(tmp_path):
    first = create_local_runtime(tmp_path)
    second = create_local_runtime(tmp_path)
    requests = (_request(), _request(_cleaned(color="red")))

    def invoke(pair):
        service, request = pair
        try:
            return service.import_asset(request).disposition.value
        except AssetIdConflict as exc:
            return exc.code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(
            invoke,
            ((first.service, requests[0]), (second.service, requests[1])),
        ))
    assert sorted(outcomes) == ["asset_id_conflict", "imported"]
    assert _counts(first.repository) == (1, 2, 0)
    assert len(_stored_files(first.blob_store)) == 1
    assert not list(first.blob_store.temp_root.iterdir())


def test_tag_timestamps_are_part_of_idempotency(tmp_path):
    runtime = create_local_runtime(tmp_path)
    request = _request()
    runtime.service.import_asset(request)
    changed_tags = (
        ImportAssetTag("Travel", UPDATED),
        ImportAssetTag("Work", UPDATED),
    )
    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(replace(request, tags=changed_tags))


def _acceptance_database_snapshot(repository):
    with repository._connect() as connection:
        return tuple(
            (
                table,
                tuple(
                    tuple(row)
                    for row in connection.execute(
                        "SELECT * FROM {} ORDER BY rowid".format(table)
                    ).fetchall()
                ),
            )
            for table in ("assets", "asset_tags", "asset_embeddings")
        )


def _acceptance_filesystem_snapshot(root):
    return tuple(
        (
            path.relative_to(root).as_posix(),
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _acceptance_assert_no_import_write(runtime, request, error=None):
    before_db = _acceptance_database_snapshot(runtime.repository)
    before_files = _acceptance_filesystem_snapshot(runtime.repository.data_root)
    if error is None:
        result = runtime.service.import_asset(request)
    else:
        with pytest.raises(error):
            runtime.service.import_asset(request)
        result = None
    assert _acceptance_database_snapshot(runtime.repository) == before_db
    assert _acceptance_filesystem_snapshot(runtime.repository.data_root) == before_files
    assert not list(runtime.blob_store.temp_root.iterdir())
    return result


def _acceptance_run_concurrently(calls):
    barrier = threading.Barrier(len(calls))

    def invoke(call):
        barrier.wait(timeout=10)
        try:
            return call().disposition.value
        except (AssetIdConflict, StoredShaOwnershipConflict) as exc:
            return exc.code

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as executor:
        return list(executor.map(invoke, calls))


def _post_conflict_import_fixture(
    tmp_path,
    monkeypatch,
    read_effect,
):
    loser = create_local_runtime(tmp_path)
    winner = create_local_runtime(tmp_path)
    request = _request()
    original_add_import = loser.repository.add_import
    original_read = loser.blob_store.read
    observations = {
        "read_attempts": 0,
        "winner_imports": 0,
        "sleeps": 0,
    }

    def commit_winner_before_loser_insert(asset, tags):
        result = winner.service.import_asset(request)
        assert result.disposition is ImportAssetDisposition.IMPORTED
        observations["winner_imports"] += 1
        return original_add_import(asset, tags)

    def controlled_read(blob_key):
        observations["read_attempts"] += 1
        return read_effect(
            observations["read_attempts"],
            original_read,
            blob_key,
        )

    monkeypatch.setattr(
        loser.repository,
        "add_import",
        commit_winner_before_loser_insert,
    )
    monkeypatch.setattr(loser.blob_store, "read", controlled_read)
    monkeypatch.setattr(
        "remember_me.core.service.time.sleep",
        lambda _seconds: observations.__setitem__(
            "sleeps",
            observations["sleeps"] + 1,
        ),
    )
    return loser, winner, request, observations


def _pre_conflict_import_fixture(
    tmp_path,
    monkeypatch,
    read_effect,
):
    loser = create_local_runtime(tmp_path)
    winner = create_local_runtime(tmp_path)
    observer = create_local_runtime(tmp_path)
    request = _request()
    original_winner_add_import = winner.repository.add_import
    original_loser_add_import = loser.repository.add_import
    original_loser_read = loser.blob_store.read
    winner_ready = threading.Event()
    release_winner = threading.Event()
    winner_done = threading.Event()
    winner_result = {}
    observations = {
        "pre_conflict_reads": 0,
        "sleeps": 0,
        "post_conflict_reads": 0,
        "independent_writes": 0,
    }
    read_phase = {"value": "pre_conflict"}

    def delay_winner_commit(asset, tags):
        winner_ready.set()
        assert release_winner.wait(5)
        return original_winner_add_import(asset, tags)

    monkeypatch.setattr(
        winner.repository,
        "add_import",
        delay_winner_commit,
    )

    def import_winner():
        try:
            winner_result["result"] = winner.service.import_asset(request)
        except BaseException as exc:
            winner_result["error"] = exc
        finally:
            winner_done.set()

    winner_thread = threading.Thread(
        target=import_winner,
        name="pre-conflict-winner",
    )
    winner_thread.start()
    assert winner_ready.wait(5)
    assert loser.repository.get(request.asset_id) is None
    assert loser.repository.find_by_stored_sha256(
        request.stored_sha256
    ) is None
    assert loser.blob_store.exists(
        "assets/{}/{}.png".format(
            request.stored_sha256[:2],
            request.stored_sha256,
        )
    )

    def controlled_read(blob_key):
        counter = read_phase["value"] + "_reads"
        observations[counter] += 1
        return read_effect(
            observations["pre_conflict_reads"],
            original_loser_read,
            blob_key,
        )

    def commit_winner_before_loser_insert(asset, tags):
        release_winner.set()
        assert winner_done.wait(5)
        assert "error" not in winner_result
        read_phase["value"] = "post_conflict"
        return original_loser_add_import(asset, tags)

    def observe_sleep(_seconds):
        with observer.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        observations["independent_writes"] += 1
        observations["sleeps"] += 1

    monkeypatch.setattr(loser.blob_store, "read", controlled_read)
    monkeypatch.setattr(
        loser.repository,
        "add_import",
        commit_winner_before_loser_insert,
    )
    monkeypatch.setattr(
        "remember_me.core.service.time.sleep",
        observe_sleep,
    )

    def cleanup():
        release_winner.set()
        winner_thread.join(5)
        assert not winner_thread.is_alive()

    return (
        loser,
        winner,
        request,
        observations,
        winner_result,
        cleanup,
    )


@pytest.mark.parametrize("transient_failures", [1, 3, 8, 9])
def test_pre_conflict_cas_transition_retries_transient_permission(
    tmp_path,
    monkeypatch,
    transient_failures,
):
    marker = "C:\\private\\PRE_CONFLICT_SECRET"

    def transient(attempt, original_read, blob_key):
        if attempt <= transient_failures:
            try:
                raise PermissionError(marker)
            except PermissionError as exc:
                raise StorageFailure() from exc
        return original_read(blob_key)

    fixture = _pre_conflict_import_fixture(
        tmp_path,
        monkeypatch,
        transient,
    )
    loser, _winner, request, observations, winner_result, cleanup = fixture
    try:
        result = loser.service.import_asset(request)
    finally:
        cleanup()

    assert winner_result["result"].disposition is ImportAssetDisposition.IMPORTED
    assert result.disposition is ImportAssetDisposition.SKIPPED_IDEMPOTENT
    assert observations["pre_conflict_reads"] == transient_failures + 1
    assert observations["post_conflict_reads"] == 1
    assert observations["sleeps"] == transient_failures
    assert observations["independent_writes"] == transient_failures
    assert _counts(loser.repository) == (1, 2, 0)
    assert loser.repository.get_asset_verification_state()[1] == 1
    stored = _stored_files(loser.blob_store)
    assert len(stored) == 1
    assert stored[0].read_bytes() == request.cleaned_bytes


def test_pre_conflict_cas_transition_permission_retry_is_bounded_and_safe(
    tmp_path,
    monkeypatch,
    caplog,
):
    marker = "C:\\private\\PRE_CONFLICT_PERSISTENT_SECRET"

    def persistent(_attempt, _original_read, _blob_key):
        try:
            raise PermissionError(marker)
        except PermissionError as exc:
            raise StorageFailure() from exc

    fixture = _pre_conflict_import_fixture(
        tmp_path,
        monkeypatch,
        persistent,
    )
    loser, _winner, request, observations, winner_result, cleanup = fixture
    try:
        with pytest.raises(BlobUnavailableOrCorrupt) as captured:
            loser.service.import_asset(request)
    finally:
        cleanup()

    formatted = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "blob_unavailable_or_corrupt"
    assert marker not in repr(captured.value)
    assert marker not in formatted
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert captured.value.__suppress_context__ is True
    assert marker not in caplog.text
    assert observations["pre_conflict_reads"] == 10
    assert observations["post_conflict_reads"] == 0
    assert observations["sleeps"] == 9
    assert observations["independent_writes"] == 9
    assert "result" in winner_result
    assert _counts(loser.repository) == (1, 2, 0)
    assert loser.repository.get_asset_verification_state()[1] == 1


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("missing"),
        OSError("other-os-error"),
        AssetFileUnavailable(),
        None,
    ],
)
def test_pre_conflict_cas_transition_does_not_retry_other_failures(
    tmp_path,
    monkeypatch,
    failure,
):
    def fail_once(_attempt, _original_read, _blob_key):
        if failure is None:
            raise StorageFailure()
        if isinstance(failure, AssetFileUnavailable):
            raise failure
        try:
            raise failure
        except OSError as exc:
            raise StorageFailure() from exc

    fixture = _pre_conflict_import_fixture(
        tmp_path,
        monkeypatch,
        fail_once,
    )
    loser, _winner, request, observations, _winner_result, cleanup = fixture
    try:
        with pytest.raises(BlobUnavailableOrCorrupt):
            loser.service.import_asset(request)
    finally:
        cleanup()

    assert observations["pre_conflict_reads"] == 1
    assert observations["post_conflict_reads"] == 0
    assert observations["sleeps"] == 0


@pytest.mark.parametrize("mismatch", ["size", "hash"])
def test_pre_conflict_cas_transition_rejects_blob_mismatch_without_retry(
    tmp_path,
    monkeypatch,
    mismatch,
):
    def wrong_content(_attempt, original_read, blob_key):
        content = original_read(blob_key)
        if mismatch == "size":
            return b"x"
        return bytes((content[0] ^ 1,)) + content[1:]

    fixture = _pre_conflict_import_fixture(
        tmp_path,
        monkeypatch,
        wrong_content,
    )
    loser, _winner, request, observations, _winner_result, cleanup = fixture
    try:
        with pytest.raises(BlobUnavailableOrCorrupt):
            loser.service.import_asset(request)
    finally:
        cleanup()

    assert observations["pre_conflict_reads"] == 1
    assert observations["post_conflict_reads"] == 0
    assert observations["sleeps"] == 0
    assert loser.repository.get_asset_verification_state()[1] == 1


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
def test_pre_conflict_cas_transition_propagates_base_exception(
    tmp_path,
    monkeypatch,
    exception_type,
):
    def interrupt(_attempt, _original_read, _blob_key):
        raise exception_type()

    fixture = _pre_conflict_import_fixture(
        tmp_path,
        monkeypatch,
        interrupt,
    )
    loser, _winner, request, observations, _winner_result, cleanup = fixture
    try:
        with pytest.raises(exception_type):
            loser.service.import_asset(request)
    finally:
        cleanup()

    assert observations["pre_conflict_reads"] == 1
    assert observations["post_conflict_reads"] == 0
    assert observations["sleeps"] == 0


def test_pre_conflict_cas_transition_retries_permission_subclass(
    tmp_path,
    monkeypatch,
):
    class SharingViolation(PermissionError):
        pass

    def transient(attempt, original_read, blob_key):
        if attempt == 1:
            try:
                raise SharingViolation("synthetic")
            except SharingViolation as exc:
                raise StorageFailure() from exc
        return original_read(blob_key)

    fixture = _pre_conflict_import_fixture(
        tmp_path,
        monkeypatch,
        transient,
    )
    loser, _winner, request, observations, _winner_result, cleanup = fixture
    try:
        result = loser.service.import_asset(request)
    finally:
        cleanup()

    assert result.disposition is ImportAssetDisposition.SKIPPED_IDEMPOTENT
    assert observations["pre_conflict_reads"] == 2
    assert observations["post_conflict_reads"] == 1
    assert observations["sleeps"] == 1


@pytest.mark.parametrize("mutation", ["delete", "replace"])
def test_pre_conflict_cas_transition_rejects_blob_filesystem_change(
    tmp_path,
    monkeypatch,
    mutation,
):
    runtime_holder = {}

    def mutate_blob(_attempt, original_read, blob_key):
        runtime = runtime_holder["loser"]
        path, _ = runtime.blob_store._resolve_blob(blob_key)
        if mutation == "delete":
            path.unlink()
        else:
            path.write_bytes(b"replaced")
        return original_read(blob_key)

    fixture = _pre_conflict_import_fixture(
        tmp_path,
        monkeypatch,
        mutate_blob,
    )
    loser, _winner, request, observations, _winner_result, cleanup = fixture
    runtime_holder["loser"] = loser
    try:
        with pytest.raises(BlobUnavailableOrCorrupt):
            loser.service.import_asset(request)
    finally:
        cleanup()

    assert observations["pre_conflict_reads"] == 1
    assert observations["post_conflict_reads"] == 0
    assert observations["sleeps"] == 0
    assert loser.repository.get_asset_verification_state()[1] == 1


def test_existing_import_blob_read_is_one_shot_and_hides_exception_chain(
    tmp_path,
    monkeypatch,
):
    runtime = create_local_runtime(tmp_path)
    request = _request()
    assert (
        runtime.service.import_asset(request).disposition
        is ImportAssetDisposition.IMPORTED
    )
    marker = "C:\\private\\EXISTING_IMPORT_SECRET"
    observations = {"reads": 0, "sleeps": 0}

    def unreadable(_blob_key):
        observations["reads"] += 1
        try:
            raise PermissionError(marker)
        except PermissionError as exc:
            raise StorageFailure() from exc

    monkeypatch.setattr(runtime.blob_store, "read", unreadable)
    monkeypatch.setattr(
        "remember_me.core.service.time.sleep",
        lambda _seconds: observations.__setitem__(
            "sleeps",
            observations["sleeps"] + 1,
        ),
    )
    with pytest.raises(BlobUnavailableOrCorrupt) as captured:
        runtime.service.import_asset(request)

    formatted = "".join(traceback.format_exception(captured.value))
    assert observations == {"reads": 1, "sleeps": 0}
    assert marker not in repr(captured.value)
    assert marker not in formatted
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert captured.value.__suppress_context__ is True


@pytest.mark.parametrize("transient_failures", [1, 3, 8])
def test_post_conflict_reclassification_retries_only_transient_permission(
    tmp_path,
    monkeypatch,
    transient_failures,
):
    marker = "C:\\private\\POST_CONFLICT_SECRET"

    def transient(attempt, original_read, blob_key):
        if attempt <= transient_failures:
            try:
                raise PermissionError(marker)
            except PermissionError as exc:
                raise StorageFailure() from exc
        return original_read(blob_key)

    loser, _winner, request, observations = (
        _post_conflict_import_fixture(
            tmp_path,
            monkeypatch,
            transient,
        )
    )
    result = loser.service.import_asset(request)

    assert result.disposition is ImportAssetDisposition.SKIPPED_IDEMPOTENT
    assert observations == {
        "read_attempts": transient_failures + 1,
        "winner_imports": 1,
        "sleeps": transient_failures,
    }
    assert _counts(loser.repository) == (1, 2, 0)
    assert loser.repository.get_asset_verification_state()[1] == 1
    stored = _stored_files(loser.blob_store)
    assert len(stored) == 1
    assert stored[0].read_bytes() == request.cleaned_bytes


def test_post_conflict_reclassification_permission_retry_is_bounded(
    tmp_path,
    monkeypatch,
):
    marker = "C:\\private\\PERSISTENT_PERMISSION_SECRET"

    def persistent(_attempt, _original_read, _blob_key):
        try:
            raise PermissionError(marker)
        except PermissionError as exc:
            raise StorageFailure() from exc

    loser, _winner, request, observations = (
        _post_conflict_import_fixture(
            tmp_path,
            monkeypatch,
            persistent,
        )
    )
    with pytest.raises(BlobUnavailableOrCorrupt) as captured:
        loser.service.import_asset(request)

    assert str(captured.value) == "blob_unavailable_or_corrupt"
    assert marker not in str(captured.value)
    assert captured.value.__cause__ is None
    assert observations == {
        "read_attempts": 10,
        "winner_imports": 1,
        "sleeps": 9,
    }
    assert _counts(loser.repository) == (1, 2, 0)
    assert loser.repository.get_asset_verification_state()[1] == 1
    assert len(_stored_files(loser.blob_store)) == 1
    assert not [
        thread
        for thread in threading.enumerate()
        if thread is not threading.main_thread() and not thread.daemon
    ]


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("missing"),
        OSError("other-os-error"),
        RuntimeError("other-storage-error"),
        None,
    ],
)
def test_post_conflict_reclassification_does_not_retry_other_failures(
    tmp_path,
    monkeypatch,
    failure,
):
    def fail_once(_attempt, _original_read, _blob_key):
        if failure is None:
            raise StorageFailure()
        try:
            raise failure
        except BaseException as exc:
            raise StorageFailure() from exc

    loser, _winner, request, observations = (
        _post_conflict_import_fixture(
            tmp_path,
            monkeypatch,
            fail_once,
        )
    )
    with pytest.raises(BlobUnavailableOrCorrupt):
        loser.service.import_asset(request)

    assert observations["read_attempts"] == 1
    assert observations["sleeps"] == 0
    assert loser.repository.get_asset_verification_state()[1] == 1


@pytest.mark.parametrize("mismatch", ["size", "hash"])
def test_post_conflict_retry_still_rejects_blob_content_mismatch(
    tmp_path,
    monkeypatch,
    mismatch,
):
    def wrong_content(attempt, original_read, blob_key):
        if attempt == 1:
            try:
                raise PermissionError("transient")
            except PermissionError as exc:
                raise StorageFailure() from exc
        if mismatch == "size":
            return b"x"
        content = original_read(blob_key)
        return bytes((content[0] ^ 1,)) + content[1:]

    loser, _winner, request, observations = (
        _post_conflict_import_fixture(
            tmp_path,
            monkeypatch,
            wrong_content,
        )
    )
    with pytest.raises(BlobUnavailableOrCorrupt):
        loser.service.import_asset(request)

    assert observations["read_attempts"] == 2
    assert observations["sleeps"] == 1
    assert loser.repository.get_asset_verification_state()[1] == 1


def test_post_conflict_malformed_winner_is_not_retried(
    tmp_path,
    monkeypatch,
):
    def readable(_attempt, original_read, blob_key):
        return original_read(blob_key)

    loser, _winner, request, observations = (
        _post_conflict_import_fixture(
            tmp_path,
            monkeypatch,
            readable,
        )
    )
    original_read_state = (
        loser.repository.read_import_classification_state
    )
    snapshot_calls = {"count": 0}

    def malformed_after_conflict(asset_id, stored_sha256):
        snapshot_calls["count"] += 1
        state = original_read_state(asset_id, stored_sha256)
        if snapshot_calls["count"] == 2:
            return replace(
                state,
                existing_asset=replace(
                    state.existing_asset,
                    title="Different",
                ),
            )
        return state

    monkeypatch.setattr(
        loser.repository,
        "read_import_classification_state",
        malformed_after_conflict,
    )
    with pytest.raises(AssetIdConflict):
        loser.service.import_asset(request)

    assert snapshot_calls["count"] == 2
    assert observations["read_attempts"] == 0
    assert observations["sleeps"] == 0
    assert loser.repository.get_asset_verification_state()[1] == 1


def test_post_conflict_retry_sleeps_without_sqlite_write_transaction(
    tmp_path,
    monkeypatch,
):
    observer = create_local_runtime(tmp_path)
    lock_checks = {"count": 0}

    def transient(attempt, original_read, blob_key):
        if attempt == 1:
            try:
                raise PermissionError("transient")
            except PermissionError as exc:
                raise StorageFailure() from exc
        return original_read(blob_key)

    loser, _winner, request, observations = (
        _post_conflict_import_fixture(
            tmp_path,
            monkeypatch,
            transient,
        )
    )

    def acquire_independent_write_transaction(_seconds):
        with observer.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        lock_checks["count"] += 1
        observations["sleeps"] += 1

    monkeypatch.setattr(
        "remember_me.core.service.time.sleep",
        acquire_independent_write_transaction,
    )
    result = loser.service.import_asset(request)

    assert result.disposition is ImportAssetDisposition.SKIPPED_IDEMPOTENT
    assert lock_checks["count"] == 1
    assert observations["read_attempts"] == 2
    assert loser.repository.get_asset_verification_state()[1] == 1


def test_post_conflict_retry_does_not_swallow_base_exception(
    tmp_path,
    monkeypatch,
):
    def interrupt(_attempt, _original_read, _blob_key):
        raise KeyboardInterrupt()

    loser, _winner, request, observations = (
        _post_conflict_import_fixture(
            tmp_path,
            monkeypatch,
            interrupt,
        )
    )
    with pytest.raises(KeyboardInterrupt):
        loser.service.import_asset(request)
    assert observations["read_attempts"] == 1
    assert observations["sleeps"] == 0


@pytest.mark.parametrize("image_format", ["GIF", "WEBP", "BMP"])
def test_acceptance_rejects_each_unsupported_decodable_format(
    tmp_path, image_format
):
    content = _encoded_image(image_format)
    request = _request(
        content,
        "image/{}".format(image_format.lower()),
        original_filename="legacy.{}".format(image_format.lower()),
    )
    with pytest.raises(UnsupportedImageFormat):
        create_local_runtime(tmp_path).service.import_asset(request)


def test_acceptance_rejects_truncated_image(tmp_path):
    content = _cleaned()
    truncated = content[:20]
    request = replace(
        _request(content),
        cleaned_bytes=truncated,
        stored_sha256=hashlib.sha256(truncated).hexdigest(),
        stored_bytes=len(truncated),
    )
    with pytest.raises((InvalidImage, UnsupportedImageFormat)):
        create_local_runtime(tmp_path).service.import_asset(request)


@pytest.mark.parametrize("field", ["source_sha256", "stored_sha256"])
def test_acceptance_rejects_uppercase_hashes(tmp_path, field):
    request = _request()
    value = (
        "a" * 64
        if field == "source_sha256"
        else request.stored_sha256
    ).upper()
    assert value != getattr(request, field)
    with pytest.raises(InvalidImportRecord):
        create_local_runtime(tmp_path).service.import_asset(
            replace(request, **{field: value})
        )


def test_acceptance_dry_run_is_write_free_for_all_states(tmp_path):
    request = _request(dry_run=True)
    fresh = create_local_runtime(tmp_path / "fresh")
    assert _acceptance_assert_no_import_write(fresh, request).disposition is (
        ImportAssetDisposition.WOULD_IMPORT
    )

    existing = create_local_runtime(tmp_path / "existing")
    real = replace(request, dry_run=False)
    existing.service.import_asset(real)
    assert _acceptance_assert_no_import_write(existing, request).disposition is (
        ImportAssetDisposition.WOULD_SKIP_IDEMPOTENT
    )
    _acceptance_assert_no_import_write(
        existing,
        replace(request, title="Different"),
        AssetIdConflict,
    )
    _acceptance_assert_no_import_write(
        existing,
        replace(request, asset_id="b" * 32),
        StoredShaOwnershipConflict,
    )

    missing = create_local_runtime(tmp_path / "missing")
    stored = missing.service.import_asset(real).asset
    missing.blob_store.delete(stored.stored_relpath)
    _acceptance_assert_no_import_write(
        missing, request, BlobUnavailableOrCorrupt
    )

    corrupt = create_local_runtime(tmp_path / "corrupt")
    stored = corrupt.service.import_asset(real).asset
    blob_path = corrupt.blob_store.data_root / stored.stored_relpath
    blob_path.write_bytes(b"corrupt")
    _acceptance_assert_no_import_write(
        corrupt, request, BlobUnavailableOrCorrupt
    )


def test_acceptance_timestamps_preserve_text_and_compare_persisted_value(
    tmp_path,
):
    runtime = create_local_runtime(tmp_path)
    created = "2026-07-01T09:02:03+08:00"
    updated = "2026-07-02T12:05:06+08:00"
    request = _request(created_at=created, updated_at=updated, tags=())
    imported = runtime.service.import_asset(request)
    assert imported.asset.created_at == created
    assert imported.asset.updated_at == updated
    assert runtime.service.import_asset(request).disposition is (
        ImportAssetDisposition.SKIPPED_IDEMPOTENT
    )
    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(replace(
            request,
            created_at="2026-07-01T01:02:03+00:00",
            updated_at="2026-07-02T04:05:06+00:00",
        ))


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("source_sha256", "2" * 64),
        ("stored_sha256", "3" * 64),
        ("stored_relpath", "assets/00/" + "0" * 64 + ".png"),
        ("original_filename", "other.png"),
        ("mime_type", "image/jpeg"),
        ("kind", "file"),
        ("decoded_bytes", 999),
        ("stored_bytes", 999),
        ("width", 99),
        ("height", 99),
        ("created_at", "2026-06-30T01:02:03+00:00"),
        ("updated_at", "2026-07-03T04:05:06+00:00"),
        ("title", "Different"),
        ("description", "Different"),
    ],
)
def test_acceptance_all_persisted_asset_fields_are_idempotency_inputs(
    tmp_path, column, value
):
    runtime = create_local_runtime(tmp_path)
    request = _request()
    runtime.service.import_asset(request)
    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE assets SET {} = ? WHERE asset_id = ?".format(column),
            (value, request.asset_id),
        )
    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(request)


def test_acceptance_tag_set_order_and_persisted_fields_are_deterministic(
    tmp_path,
):
    runtime = create_local_runtime(tmp_path)
    request = _request()
    runtime.service.import_asset(request)
    assert runtime.service.import_asset(
        replace(request, tags=tuple(reversed(request.tags)))
    ).disposition is ImportAssetDisposition.SKIPPED_IDEMPOTENT

    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(replace(request, tags=(
            ImportAssetTag("travel", TAG_CREATED),
            request.tags[1],
        )))
    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(replace(request, tags=(request.tags[0],)))
    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE asset_tags SET created_at = ? "
            "WHERE asset_id = ? AND tag_normalized = ?",
            (UPDATED, request.asset_id, "travel"),
        )
    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(request)
    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE asset_tags SET created_at = ? "
            "WHERE asset_id = ? AND tag_normalized = ?",
            (TAG_CREATED, request.asset_id, "travel"),
        )
        connection.execute(
            "INSERT INTO asset_tags "
            "(asset_id, tag_normalized, tag_display, created_at) "
            "VALUES (?, ?, ?, ?)",
            (request.asset_id, "extra", "Extra", TAG_CREATED),
        )
    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(request)


def test_acceptance_imported_id_works_across_existing_core_operations(tmp_path):
    runtime = create_local_runtime(tmp_path)
    request = _request()
    asset = runtime.service.import_asset(request).asset
    assert runtime.service.get_asset(GetAssetRequest(request.asset_id)) == asset
    assert runtime.service.resolve_asset(
        ResolveAssetRequest(request.asset_id)
    ).asset.asset_id == request.asset_id
    search = asyncio.run(runtime.service.search_assets(
        SearchAssetsRequest(query="Legacy title")
    ))
    assert search.results[0].asset.asset_id == request.asset_id
    reindex = asyncio.run(runtime.service.reindex_embeddings(
        ReindexEmbeddingsRequest(asset_id=request.asset_id)
    ))
    assert reindex.enabled is False
    assert (reindex.scanned, reindex.indexed, reindex.skipped, reindex.failed) == (
        1,
        0,
        1,
        0,
    )
    assert runtime.repository.get_embedding(request.asset_id) is None
    updated = runtime.service.update_metadata(UpdateMetadataRequest(
        asset_id=request.asset_id,
        title="Updated through Core",
    ))
    assert updated.asset_id == request.asset_id
    assert runtime.service.delete_asset(
        DeleteAssetRequest(request.asset_id)
    ).deleted is True


def test_acceptance_cas_corruption_race_maps_to_public_blob_error(
    tmp_path, monkeypatch
):
    runtime = create_local_runtime(tmp_path)
    request = _request()
    path = (
        runtime.blob_store.data_root
        / "assets"
        / request.stored_sha256[:2]
        / (request.stored_sha256 + ".png")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"corrupt")
    monkeypatch.setattr(runtime.blob_store, "exists", lambda _key: False)
    with pytest.raises(BlobUnavailableOrCorrupt):
        runtime.service.import_asset(request)
    assert _counts(runtime.repository) == (0, 0, 0)
    assert path.read_bytes() == b"corrupt"


def test_acceptance_tag_insert_failure_rolls_back_everything(tmp_path):
    runtime = create_local_runtime(tmp_path)
    with runtime.repository._connect() as connection:
        connection.execute(
            "CREATE TRIGGER reject_import_tag BEFORE INSERT ON asset_tags "
            "BEGIN SELECT RAISE(ABORT, 'reject_import_tag'); END"
        )
    with pytest.raises(Exception) as raised:
        runtime.service.import_asset(_request())
    assert getattr(raised.value, "code", "") == "asset_conflict"
    assert _counts(runtime.repository) == (0, 0, 0)
    assert not _stored_files(runtime.blob_store)
    assert not list(runtime.blob_store.temp_root.iterdir())


def test_preflight_classification_uses_one_consistent_snapshot(
    tmp_path,
    monkeypatch,
):
    loser = create_local_runtime(tmp_path)
    winner = create_local_runtime(tmp_path)
    request = _request()
    first_select = threading.Event()
    release_snapshot = threading.Event()
    observations = {"snapshots": 0, "add": 0}
    original_connect = loser.repository._connect
    original_read_state = (
        loser.repository.read_import_classification_state
    )
    original_add = loser.repository.add_import

    class ControlledReadConnection:
        def __init__(self, connection):
            self._connection = connection
            self._blocked = False

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, *args):
            return self._connection.__exit__(*args)

        def execute(self, sql, parameters=()):
            cursor = self._connection.execute(sql, parameters)
            if (
                not self._blocked
                and "WHERE asset_id = ?" in sql
            ):
                self._blocked = True
                first_select.set()
                assert release_snapshot.wait(5)
            return cursor

        def __getattr__(self, name):
            return getattr(self._connection, name)

    connect_calls = {"count": 0}

    def controlled_connect():
        connect_calls["count"] += 1
        connection = original_connect()
        if connect_calls["count"] == 1:
            return ControlledReadConnection(connection)
        return connection

    def count_snapshot(*args):
        observations["snapshots"] += 1
        return original_read_state(*args)

    def count_add(asset, tags):
        observations["add"] += 1
        return original_add(asset, tags)

    monkeypatch.setattr(
        loser.repository,
        "_connect",
        controlled_connect,
    )
    monkeypatch.setattr(
        loser.repository,
        "read_import_classification_state",
        count_snapshot,
    )
    monkeypatch.setattr(loser.repository, "add_import", count_add)
    monkeypatch.setattr(
        loser.repository,
        "get",
        lambda *_args: pytest.fail("classification_must_not_call_get"),
    )
    monkeypatch.setattr(
        loser.repository,
        "find_by_stored_sha256",
        lambda *_args: pytest.fail("classification_must_not_call_find"),
    )

    loser_result = {}

    def import_loser():
        try:
            loser_result["result"] = loser.service.import_asset(request)
        except BaseException as exc:
            loser_result["error"] = exc

    loser_thread = threading.Thread(target=import_loser)
    loser_thread.start()
    assert first_select.wait(5)
    winner_result = {}
    winner_done = threading.Event()

    def import_winner():
        try:
            winner_result["result"] = winner.service.import_asset(request)
        except BaseException as exc:
            winner_result["error"] = exc
        finally:
            winner_done.set()

    winner_thread = threading.Thread(target=import_winner)
    winner_thread.start()
    assert not winner_done.wait(0.05)
    release_snapshot.set()
    loser_thread.join(5)
    winner_thread.join(5)
    assert not loser_thread.is_alive()
    assert not winner_thread.is_alive()

    assert "error" not in winner_result
    assert winner_result["result"].disposition is (
        ImportAssetDisposition.IMPORTED
    )
    assert "error" not in loser_result
    assert loser_result["result"].disposition is (
        ImportAssetDisposition.SKIPPED_IDEMPOTENT
    )
    assert observations == {"snapshots": 2, "add": 1}
    assert loser.repository.get_asset_verification_state()[1] == 1
    assert _counts(winner.repository) == (1, 2, 0)


@pytest.mark.parametrize(
    "state_kind",
    [
        "same_owner_without_existing",
        "existing_without_owner",
        "different_owner_with_existing",
    ],
)
def test_import_classification_snapshot_invariants_fail_closed(
    tmp_path,
    monkeypatch,
    state_kind,
):
    runtime = create_local_runtime(tmp_path)
    request = _request()
    asset, tags = runtime.service._validate_import_request(request)
    if state_kind == "same_owner_without_existing":
        state = ImportClassificationState(None, (), asset, tags)
    elif state_kind == "existing_without_owner":
        state = ImportClassificationState(asset, tags, None, ())
    else:
        owner = replace(asset, asset_id="b" * 32)
        state = ImportClassificationState(asset, tags, owner, tags)
    monkeypatch.setattr(
        runtime.repository,
        "read_import_classification_state",
        lambda *_args: state,
    )

    with pytest.raises(
        StorageFailure,
        match="import_classification_invariant",
    ):
        runtime.service.import_asset(request)

    assert _counts(runtime.repository) == (0, 0, 0)
    assert runtime.repository.get_asset_verification_state()[1] == 0
    assert not _stored_files(runtime.blob_store)


@pytest.mark.parametrize("_round", range(5))
def test_acceptance_identical_imports_have_a_real_cross_runtime_race(
    tmp_path, _round
):
    runtimes = [create_local_runtime(tmp_path) for _ in range(8)]
    request = _request()
    outcomes = _acceptance_run_concurrently([
        lambda runtime=runtime: runtime.service.import_asset(request)
        for runtime in runtimes
    ])
    assert outcomes.count("imported") == 1
    assert outcomes.count("skipped_idempotent") == 7
    assert _counts(runtimes[0].repository) == (1, 2, 0)
    assert runtimes[0].repository.get_asset_verification_state()[1] == 1
    stored = _stored_files(runtimes[0].blob_store)
    assert len(stored) == 1
    assert hashlib.sha256(stored[0].read_bytes()).hexdigest() == (
        request.stored_sha256
    )
    assert not list(runtimes[0].blob_store.temp_root.iterdir())


@pytest.mark.parametrize("_round", range(5))
def test_acceptance_same_sha_different_ids_have_a_real_race(
    tmp_path, _round
):
    first = create_local_runtime(tmp_path)
    second = create_local_runtime(tmp_path)
    request = _request()
    outcomes = _acceptance_run_concurrently([
        lambda: first.service.import_asset(request),
        lambda: second.service.import_asset(replace(request, asset_id="b" * 32)),
    ])
    assert sorted(outcomes) == ["imported", "stored_sha_ownership_conflict"]
    assert _counts(first.repository) == (1, 2, 0)
    assert first.repository.get_asset_verification_state()[1] == 1
    assert len(_stored_files(first.blob_store)) == 1
    assert not list(first.blob_store.temp_root.iterdir())


@pytest.mark.parametrize("_round", range(5))
def test_acceptance_same_id_different_content_has_a_real_race(
    tmp_path, _round
):
    first = create_local_runtime(tmp_path)
    second = create_local_runtime(tmp_path)
    requests = (_request(), _request(_cleaned(color="red")))
    outcomes = _acceptance_run_concurrently([
        lambda: first.service.import_asset(requests[0]),
        lambda: second.service.import_asset(requests[1]),
    ])
    assert sorted(outcomes) == ["asset_id_conflict", "imported"]
    assert _counts(first.repository) == (1, 2, 0)
    assert first.repository.get_asset_verification_state()[1] == 1
    stored = _stored_files(first.blob_store)
    assert len(stored) == 1
    assert hashlib.sha256(stored[0].read_bytes()).hexdigest() in {
        request.stored_sha256 for request in requests
    }
    assert not list(first.blob_store.temp_root.iterdir())


@pytest.mark.parametrize("spelling,counterpart,key", UNICODE_CASES)
def test_unicode_import_public_roundtrip_timestamps_and_identity(tmp_path, spelling, counterpart, key):
    runtime = create_local_runtime(tmp_path / "first")
    request = _request(title=spelling, description=spelling,
        original_filename=spelling + ".png",
        tags=(ImportAssetTag("z", UPDATED), ImportAssetTag(spelling, TAG_CREATED)))
    result = runtime.service.import_asset(request)
    assert result.asset.title == result.asset.description == spelling
    assert result.asset.original_filename == spelling + ".png"
    assert result.tags == tuple(sorted(request.tags, key=lambda tag: tag_comparison_key(tag.value)))
    with runtime.repository._connect() as connection:
        assert tuple(connection.execute(
            "SELECT tag_normalized, tag_display, created_at FROM asset_tags WHERE tag_normalized = ?", (key,)
        ).fetchone()) == (key, spelling, TAG_CREATED)
    for public in (asset_to_public_dict(result.asset), asset_to_public_response(result.asset).model_dump()):
        assert public["title"] == public["description"] == spelling
        assert public["original_filename"] == spelling + ".png"
        assert spelling in public["tags"]
    # Public metadata representation, not a new export API.
    exported = asdict(request)
    content = exported.pop("cleaned_bytes")
    transported = json.loads(json.dumps(exported, ensure_ascii=False))
    transported["tags"] = tuple(ImportAssetTag(**tag) for tag in transported["tags"])
    restored = ImportAssetRequest(cleaned_bytes=content, **transported)
    second = create_local_runtime(tmp_path / "second").service.import_asset(restored)
    assert second.asset == result.asset
    assert second.tags == result.tags
    assert runtime.service.import_asset(restored).disposition is ImportAssetDisposition.SKIPPED_IDEMPOTENT
    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(replace(request, title=counterpart))
    with pytest.raises(AssetIdConflict):
        runtime.service.import_asset(replace(request, tags=(ImportAssetTag(counterpart, TAG_CREATED), ImportAssetTag("z", UPDATED))))
    with pytest.raises(StoredShaOwnershipConflict):
        runtime.service.import_asset(replace(request, asset_id="b" * 32, title=counterpart))
    assert runtime.blob_store.read(result.asset.stored_relpath) == content
    assert (result.asset.asset_id, result.asset.source_sha256, result.asset.stored_sha256) == (
        request.asset_id, request.source_sha256, request.stored_sha256,
    )
    old = create_local_runtime(tmp_path / "old").service.import_asset(replace(request,
        title=counterpart, description=counterpart, original_filename=counterpart + ".png",
        tags=(ImportAssetTag(counterpart, TAG_CREATED),)))
    assert old.asset.title == counterpart


@pytest.mark.parametrize("tags", [
    (ImportAssetTag("Ａ", TAG_CREATED), ImportAssetTag("A", UPDATED)),
    (ImportAssetTag("Straße", TAG_CREATED), ImportAssetTag("STRASSE", UPDATED)),
    (ImportAssetTag("a，b", TAG_CREATED), ImportAssetTag("a,b", UPDATED)),
])
def test_import_canonical_tag_collision_rejected_without_writes(tmp_path, tags):
    runtime = create_local_runtime(tmp_path)
    with pytest.raises(ImportMetadataValidationError):
        runtime.service.import_asset(_request(tags=tags))
    assert _counts(runtime.repository) == (0, 0, 0)
    assert not _stored_files(runtime.blob_store)
