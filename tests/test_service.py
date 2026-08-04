# SPDX-License-Identifier: CPAL-1.0
import asyncio
import hashlib
import io
import re
import concurrent.futures
from datetime import datetime, timezone

import pytest
from PIL import Image

from remember_me.core import (
    AssetFileUnavailable,
    DeleteAssetRequest,
    GetAssetRequest,
    IngestImageRequest,
    InvalidImage,
    RememberMeService,
    ResolveAssetRequest,
    SearchAssetsRequest,
    StorageFailure,
    UpdateMetadataRequest,
    UploadSizeMismatch,
)
from remember_me.imaging import PillowImageSanitizer
from remember_me.search import NullVectorProvider
from remember_me.storage import LocalContentStore, SQLiteAssetRepository


class FakeClock:
    def __init__(self, value):
        self.value = value

    def now(self):
        return self.value


def _png(color="blue"):
    image = Image.new("RGB", (8, 6), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


def _jpeg(color="green"):
    image = Image.new("RGB", (7, 5), color)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=95)
    image.close()
    return output.getvalue()


def _service(tmp_path):
    repository = SQLiteAssetRepository(tmp_path)
    blobs = LocalContentStore(tmp_path)
    clock = FakeClock(datetime(2026, 7, 25, 1, 2, 3, tzinfo=timezone.utc))
    service = RememberMeService(
        repository,
        blobs,
        PillowImageSanitizer(),
        clock,
        NullVectorProvider(),
    )
    return service, repository, blobs, clock


def test_ingest_computes_hashes_path_and_asset_id(tmp_path):
    service, _, blobs, _ = _service(tmp_path)
    content = _png()
    result = service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="../../unsafe\\photo.png",
            mime_type="application/octet-stream",
            title=" first ",
            tags=(" One ", "one"),
        )
    )
    asset = result.asset
    assert result.deduplicated is False
    assert asset.source_sha256 == hashlib.sha256(content).hexdigest()
    stored = blobs.read(asset.stored_relpath)
    assert asset.stored_sha256 == hashlib.sha256(stored).hexdigest()
    assert asset.stored_relpath == "assets/{}/{}.png".format(
        asset.stored_sha256[:2],
        asset.stored_sha256,
    )
    assert re.fullmatch(r"[0-9a-f]{32}", asset.asset_id)
    assert asset.original_filename == "_.._unsafe_photo.png"
    assert asset.title == "first"
    assert asset.tags == ("One",)
    assert asset.created_at == "2026-07-25T01:02:03+00:00"


def test_jpeg_ingest_and_octet_stream_non_image_rejection(tmp_path):
    service, _, blobs, _ = _service(tmp_path)
    content = _jpeg()
    result = service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="photo.jpeg",
            mime_type="image/jpeg",
        )
    )
    assert result.asset.mime_type == "image/jpeg"
    assert result.asset.stored_relpath.endswith(".jpg")
    with Image.open(io.BytesIO(blobs.read(result.asset.stored_relpath))) as image:
        image.load()
        assert image.format == "JPEG"
        assert image.mode == "RGB"

    invalid = b"not a formal image"
    with pytest.raises(InvalidImage) as raised:
        service.ingest_image(
            IngestImageRequest(
                content=invalid,
                expected_bytes=len(invalid),
                filename="not-image.bin",
                mime_type="application/octet-stream",
            )
        )
    assert getattr(raised.value, "code", "") == "invalid_image"


@pytest.mark.parametrize("delta", [-1, 1])
def test_ingest_rejects_short_and_long_expected_sizes(tmp_path, delta):
    service, _, _, _ = _service(tmp_path)
    content = _png()
    with pytest.raises(UploadSizeMismatch):
        service.ingest_image(
            IngestImageRequest(
                content=content,
                expected_bytes=len(content) + delta,
                filename="photo.png",
            )
        )


def test_dedup_does_not_overwrite_existing_metadata(tmp_path):
    service, _, _, clock = _service(tmp_path)
    content = _png()
    first = service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="first.png",
            title="original",
            description="keep",
            tags=("first",),
        )
    )
    clock.value = datetime(2026, 7, 25, 2, 0, 0, tzinfo=timezone.utc)
    duplicate = service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="second.png",
            title="replacement",
            description="overwrite",
            tags=("second",),
        )
    )
    assert duplicate.deduplicated is True
    assert duplicate.asset == first.asset

    changed = service.update_metadata(
        UpdateMetadataRequest(
            asset_id=first.asset.asset_id,
            title="explicit update",
        )
    )
    assert changed.title == "explicit update"
    assert changed.description == "keep"
    assert changed.tags == ("first",)


def test_concurrent_duplicate_ingest_has_one_asset_and_blob(tmp_path):
    service, repository, blobs, _ = _service(tmp_path)
    content = _png()

    def ingest(index):
        return service.ingest_image(
            IngestImageRequest(
                content=content,
                expected_bytes=len(content),
                filename="{}.png".format(index),
            )
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(ingest, range(8)))
    assert len({result.asset.asset_id for result in results}) == 1
    assert sum(not result.deduplicated for result in results) == 1
    assert len(repository.list_for_embedding()) == 1
    stored_files = [
        path
        for path in blobs.assets_root.rglob("*")
        if path.is_file() and blobs.temp_root not in path.parents
    ]
    assert len(stored_files) == 1


def test_get_search_and_resolve_return_public_models(tmp_path):
    service, _, _, _ = _service(tmp_path)
    content = _png()
    created = service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="searchable.png",
            title="Summer",
            description="trip photo",
            tags=("Travel",),
        )
    ).asset
    assert service.get_asset(GetAssetRequest(created.asset_id)) == created
    search = asyncio.run(
        service.search_assets(SearchAssetsRequest(query="summer"))
    )
    assert search.results[0].asset == created
    resolved = service.resolve_asset(ResolveAssetRequest(created.asset_id))
    assert resolved.asset == created
    assert resolved.blob_key == created.stored_relpath
    assert not re.match(r"^[A-Za-z]:[\\/]", resolved.blob_key)


def test_resolve_rejects_missing_blob(tmp_path):
    service, _, blobs, _ = _service(tmp_path)
    content = _png()
    asset = service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="missing.png",
        )
    ).asset
    blobs.delete(asset.stored_relpath)
    with pytest.raises(AssetFileUnavailable):
        service.resolve_asset(ResolveAssetRequest(asset.asset_id))


def test_delete_removes_blob_and_cascades_metadata(tmp_path):
    service, repository, blobs, _ = _service(tmp_path)
    content = _png()
    asset = service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="delete.png",
            tags=("delete",),
        )
    ).asset
    with repository._connect() as connection:
        connection.execute(
            """
            INSERT INTO asset_embeddings (
                asset_id, embedding, model, content_hash, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (asset.asset_id, "[0.1]", "test", "content", asset.updated_at),
        )

    result = service.delete_asset(DeleteAssetRequest(asset.asset_id))
    assert result.deleted is True
    assert result.cleanup_pending is False
    assert repository.get(asset.asset_id) is None
    assert blobs.exists(asset.stored_relpath) is False
    with repository._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM asset_tags"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM asset_embeddings"
        ).fetchone()[0] == 0


def test_delete_database_failure_restores_blob(tmp_path, monkeypatch):
    service, repository, blobs, _ = _service(tmp_path)
    content = _png()
    asset = service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="restore.png",
        )
    ).asset

    def fail_delete(_asset_id):
        raise StorageFailure("simulated_database_failure")

    monkeypatch.setattr(repository, "delete", fail_delete)
    with pytest.raises(StorageFailure, match="simulated_database_failure"):
        service.delete_asset(DeleteAssetRequest(asset.asset_id))
    assert repository.get(asset.asset_id) == asset
    assert blobs.read(asset.stored_relpath)


def test_delete_cleanup_failure_reports_pending(tmp_path, monkeypatch):
    service, repository, blobs, _ = _service(tmp_path)
    content = _png()
    asset = service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="pending.png",
        )
    ).asset
    monkeypatch.setattr(
        blobs,
        "finalize_quarantined",
        lambda _quarantine_key: False,
    )
    result = service.delete_asset(DeleteAssetRequest(asset.asset_id))
    assert result.deleted is True
    assert result.cleanup_pending is True
    assert repository.get(asset.asset_id) is None
    assert blobs.exists(asset.stored_relpath) is False
    assert list(blobs.temp_root.iterdir())


def test_delete_rejects_path_traversal_and_missing_file(tmp_path):
    service, repository, blobs, _ = _service(tmp_path)
    content = _png()
    traversal = service.ingest_image(
        IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="traversal.png",
        )
    ).asset
    with repository._connect() as connection:
        connection.execute(
            "UPDATE assets SET stored_relpath = ? WHERE asset_id = ?",
            ("../outside.png", traversal.asset_id),
        )
    with pytest.raises(StorageFailure, match="invalid_blob_key"):
        service.delete_asset(DeleteAssetRequest(traversal.asset_id))
    assert repository.get(traversal.asset_id) is not None

    other_content = _png("red")
    missing = service.ingest_image(
        IngestImageRequest(
            content=other_content,
            expected_bytes=len(other_content),
            filename="missing.png",
        )
    ).asset
    blobs.delete(missing.stored_relpath)
    with pytest.raises(AssetFileUnavailable):
        service.delete_asset(DeleteAssetRequest(missing.asset_id))
    assert repository.get(missing.asset_id) is not None
