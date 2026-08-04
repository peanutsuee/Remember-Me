# SPDX-License-Identifier: CPAL-1.0
"""Executable synthetic-image compatibility probe for Pillow 10 through 12."""

from __future__ import annotations

import argparse
import asyncio
import base64
import gc
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from PIL import Image

from remember_me import create_local_runtime
from remember_me.compat import asset_relative_path
from remember_me.core import (
    DeleteAssetRequest,
    GetAssetRequest,
    IngestImageRequest,
    InvalidImage,
    SearchAssetsRequest,
    UpdateMetadataRequest,
    UploadTooLarge,
)
from remember_me.imaging import PillowImageSanitizer


PNG_METADATA = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAA0AAAAJCAIAAABmGDE9AAAAKmlDQ1BJQ0MgUHJv"
    "ZmlsZQAAeJwrrswryUgtyUzWLS5JTE81T9PNTE4GAF1sCBaPzMU3AAAAIXRFWHR"
    "Db21tZW50AHN5bnRoZXRpYyBzdGFnZTdmIGNvbW1lbnQ/Dxb+AAAAFnRFWHRwcml"
    "2YXRlLW5vdGUAcmVtb3ZlIG1lo82G4gAAABZJREFUeJxjFHdOZSACMBGjaFQdTgA"
    "AGOsA0WU3E/cAAAAASUVORK5CYII="
)
JPEG_BASE = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAIBAQEBAQIBAQECAgICAgQDAgICAgUE"
    "BAMEBgUGBgYFBgYGBwkIBgcJBwYGCAsICQoKCgoKBggLDAsKDAkKCgr/2wBDAQIC"
    "AgICAgUDAwUKBwYHCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoK"
    "CgoKCgoKCgoKCgoKCgr/wAARCAAIAA4DASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEA"
    "AAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIh"
    "MUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6"
    "Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZ"
    "mqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx"
    "8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAV"
    "YnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hp"
    "anN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPE"
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDw"
    "uiiiv57P6sP/2Q=="
)


def _jpeg_with_orientation(orientation, include_private_segments=False):
    tiff = (
        b"MM\x00*\x00\x00\x00\x08"
        b"\x00\x01"
        b"\x01\x12\x00\x03\x00\x00\x00\x01"
        + int(orientation).to_bytes(2, "big")
        + b"\x00\x00"
        + b"\x00\x00\x00\x00"
    )
    segments = [b"Exif\x00\x00" + tiff]
    if include_private_segments:
        segments.extend(
            (
                b"ICC_PROFILE\x00\x01\x01synthetic-stage7f-icc",
                b"synthetic stage7f comment",
            )
        )
    encoded = bytearray(JPEG_BASE[:2])
    markers = (b"\xff\xe1", b"\xff\xe2", b"\xff\xfe")
    for marker, payload in zip(markers, segments):
        encoded.extend(marker)
        encoded.extend((len(payload) + 2).to_bytes(2, "big"))
        encoded.extend(payload)
    encoded.extend(JPEG_BASE[2:])
    return bytes(encoded)


JPEG_EXIF = _jpeg_with_orientation(1, include_private_segments=True)
JPEG_ORIENTED = _jpeg_with_orientation(6)
PNG_TRANSPARENT = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAsAAAAGCAYAAAAVMmT4AAAAKUlEQVR4nGOUs4li"
    "IBawwBg9b7gacCkqEfnWwMDAwMBEtLE0VcxIigcBBZ8FdQlyMKEAAAAASUVORK5C"
    "YII="
)
FIXTURES = {
    "png_metadata": (PNG_METADATA, "image/png"),
    "jpeg_exif": (JPEG_EXIF, "image/jpeg"),
    "jpeg_oriented": (JPEG_ORIENTED, "image/jpeg"),
    "png_transparent": (PNG_TRANSPARENT, "image/png"),
}
TOOL_NAMES = (
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


def _inspect_cleaned(content):
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        return {
            "format": image.format,
            "mode": image.mode,
            "size": list(image.size),
            "metadata_clean": (
                not image.getexif()
                and "exif" not in image.info
                and "icc_profile" not in image.info
                and "comment" not in image.info
                and "Comment" not in image.info
                and "private-note" not in image.info
            ),
        }


def _sanitizer_probe():
    sanitizer = PillowImageSanitizer()
    results = {}
    for name, (content, mime_type) in FIXTURES.items():
        first = sanitizer.sanitize(content, mime_type)
        second = sanitizer.sanitize(content, mime_type)
        assert first.content == second.content
        inspected = _inspect_cleaned(first.content)
        assert inspected["metadata_clean"]
        assert first.mime_type in {"image/png", "image/jpeg"}
        assert first.extension in {".png", ".jpg"}
        if name == "jpeg_oriented":
            assert (first.width, first.height) == (8, 14)
        if name == "png_transparent":
            assert inspected["mode"] == "RGBA"
        results[name] = {
            "mime_type": first.mime_type,
            "extension": first.extension,
            "width": first.width,
            "height": first.height,
            "stored_bytes": len(first.content),
            "stored_sha256": hashlib.sha256(first.content).hexdigest(),
            **inspected,
        }

    try:
        sanitizer.sanitize(b"not an image", "application/octet-stream")
    except InvalidImage:
        invalid_rejected = True
    else:
        invalid_rejected = False
    assert invalid_rejected

    boundary = Image.new("RGB", (10, 10), "navy")
    over = Image.new("RGB", (11, 10), "navy")
    boundary_bytes = io.BytesIO()
    over_bytes = io.BytesIO()
    boundary.save(boundary_bytes, format="PNG")
    over.save(over_bytes, format="PNG")
    boundary.close()
    over.close()
    limited = PillowImageSanitizer(max_image_pixels=100)
    assert limited.sanitize(
        boundary_bytes.getvalue(), "image/png"
    ).width == 10
    try:
        limited.sanitize(over_bytes.getvalue(), "image/png")
    except Exception as error:
        pixel_error = getattr(error, "code", "")
    else:
        pixel_error = ""
    assert pixel_error == "image_pixel_limit"
    try:
        PillowImageSanitizer(
            max_source_bytes=len(PNG_METADATA) - 1
        ).sanitize(PNG_METADATA, "image/png")
    except UploadTooLarge:
        size_rejected = True
    else:
        size_rejected = False
    assert size_rejected
    return results


def _service_probe():
    with tempfile.TemporaryDirectory(prefix="rm-stage7f-service-") as raw_root:
        runtime = create_local_runtime(raw_root)
        content = PNG_METADATA
        request = IngestImageRequest(
            content=content,
            expected_bytes=len(content),
            filename="synthetic-stage7f.png",
            mime_type="image/png",
            title="Stage 7F",
            description="Synthetic compatibility fixture",
            tags=("Matrix", "matrix"),
        )
        first = runtime.service.ingest_image(request)
        asset = first.asset
        assert first.deduplicated is False
        assert runtime.service.get_asset(GetAssetRequest(asset.asset_id)) == asset
        search = asyncio.run(
            runtime.service.search_assets(
                SearchAssetsRequest(query="stage 7f")
            )
        )
        assert search.total == 1
        updated = runtime.service.update_metadata(
            UpdateMetadataRequest(
                asset_id=asset.asset_id,
                title="Stage 7F updated",
                tags=("Pillow", "Compatibility"),
            )
        )
        duplicate = runtime.service.ingest_image(request)
        assert duplicate.deduplicated is True
        assert duplicate.asset.title == updated.title
        blob = runtime.blob_store.read(updated.stored_relpath)
        assert hashlib.sha256(blob).hexdigest() == updated.stored_sha256
        assert updated.stored_relpath == asset_relative_path(
            updated.stored_sha256, ".png"
        )
        deleted = runtime.service.delete_asset(
            DeleteAssetRequest(updated.asset_id)
        )
        assert deleted.deleted and not deleted.cleanup_pending
        assert runtime.repository.get(updated.asset_id) is None
        result = {
            "crud": True,
            "deduplicated": True,
            "blob_layout": "assets/<prefix>/<sha256>.png",
            "database": "assets.sqlite3",
        }
        del deleted, duplicate, updated, asset, first, runtime
        gc.collect()
        return result


def _mcp_schema_probe(runtime):
    from mcp.server.fastmcp import FastMCP

    from remember_me.mcp.tools import register_tools
    from remember_me.mcp.transfers import (
        DownloadTicketStore,
        UploadTicketStore,
    )

    server = FastMCP(
        "stage7f-probe",
        stateless_http=True,
        json_response=True,
    )
    register_tools(
        server,
        runtime,
        UploadTicketStore("http://127.0.0.1:8787"),
        DownloadTicketStore("http://127.0.0.1:8787"),
    )
    tools = asyncio.run(server.list_tools())
    assert tuple(tool.name for tool in tools) == TOOL_NAMES
    upload = next(
        tool for tool in tools if tool.name == "rm_asset_upload_link"
    )
    assert "expected_sha256" not in json.dumps(upload.inputSchema)
    schema = [
        {
            "name": tool.name,
            "input": tool.inputSchema,
            "output": tool.outputSchema,
            "annotations": (
                tool.annotations.model_dump(
                    by_alias=True,
                    exclude_none=True,
                )
                if tool.annotations
                else None
            ),
            "meta": tool.meta,
        }
        for tool in tools
    ]
    encoded = json.dumps(
        schema,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "names": list(TOOL_NAMES),
        "schema_sha256": hashlib.sha256(encoded).hexdigest(),
        "expected_sha256_absent": True,
    }


def _schema_snapshot(data_root):
    database = Path(data_root) / "assets.sqlite3"
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name NOT LIKE 'sqlite_autoindex%'"
            )
        }
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(assets)")
        }
        empty_updated = connection.execute(
            "SELECT count(*) FROM assets WHERE updated_at = ''"
        ).fetchone()[0]
    return tables, indexes, columns, empty_updated


def _ob_cross_probe(ombre_brain_root):
    ob_root = Path(ombre_brain_root).resolve()
    sys.path.insert(0, str(ob_root))
    try:
        import asset_store as ob_asset_store
    finally:
        sys.path.pop(0)
    if Path(ob_asset_store.__file__).resolve().parent != ob_root:
        raise AssertionError("unexpected_ombre_brain_module")

    rm_sanitizer = PillowImageSanitizer()
    comparisons = {}
    with tempfile.TemporaryDirectory(prefix="rm-stage7f-cross-") as raw_root:
        ob_store = ob_asset_store.AssetStore(Path(raw_root) / "cross")
        for name in ("png_metadata", "jpeg_exif", "jpeg_oriented"):
            content, mime_type = FIXTURES[name]
            source = ob_store.create_temp_path()
            source.write_bytes(content)
            asset = ob_store.persist_upload(
                source,
                hashlib.sha256(content).hexdigest(),
                len(content),
                name,
                mime_type,
                require_image=True,
            )
            ob_content = (
                ob_store.data_root / asset["stored_relpath"]
            ).read_bytes()
            rm_cleaned = rm_sanitizer.sanitize(content, mime_type)
            assert ob_content == rm_cleaned.content
            assert asset["mime_type"] == rm_cleaned.mime_type
            assert (asset["width"], asset["height"]) == (
                rm_cleaned.width,
                rm_cleaned.height,
            )
            assert asset["stored_sha256"] == hashlib.sha256(
                rm_cleaned.content
            ).hexdigest()
            assert asset["stored_relpath"] == asset_relative_path(
                asset["stored_sha256"],
                rm_cleaned.extension,
            )
            assert _inspect_cleaned(ob_content)["metadata_clean"]
            comparisons[name] = {
                "bytes_equal": True,
                "stored_sha256_equal": True,
                "mime_equal": True,
                "dimensions_equal": True,
                "relative_path_equal": True,
            }
        del ob_store
        gc.collect()

    with tempfile.TemporaryDirectory(prefix="rm-stage7f-data-") as raw_root:
        data_root = Path(raw_root) / "shared"
        ob_store = ob_asset_store.AssetStore(data_root)
        created = []
        for name in ("png_metadata", "jpeg_exif"):
            content, mime_type = FIXTURES[name]
            source = ob_store.create_temp_path()
            source.write_bytes(content)
            created.append(
                ob_store.persist_upload(
                    source,
                    hashlib.sha256(content).hexdigest(),
                    len(content),
                    name,
                    mime_type,
                    require_image=True,
                )
        )
        before = _schema_snapshot(data_root)
        del ob_store
        gc.collect()

        runtime = create_local_runtime(data_root)
        after_init = _schema_snapshot(data_root)
        first = runtime.service.get_asset(
            GetAssetRequest(created[0]["asset_id"])
        )
        assert asyncio.run(
            runtime.service.search_assets(
                SearchAssetsRequest(query="png_metadata")
            )
        ).total == 1
        updated = runtime.service.update_metadata(
            UpdateMetadataRequest(
                asset_id=first.asset_id,
                title="RM compatible update",
                description="Synthetic data only",
                tags=("Roundtrip", "Pillow"),
            )
        )
        duplicate = runtime.service.ingest_image(
            IngestImageRequest(
                content=PNG_METADATA,
                expected_bytes=len(PNG_METADATA),
                filename="duplicate.png",
                mime_type="image/png",
            )
        )
        assert duplicate.deduplicated
        assert runtime.blob_store.read(updated.stored_relpath)
        assert runtime.service.delete_asset(
            DeleteAssetRequest(created[1]["asset_id"])
        ).deleted
        del runtime
        gc.collect()

        reopened = ob_asset_store.AssetStore(data_root)
        old_view = reopened.get(updated.asset_id)
        assert old_view["title"] == "RM compatible update"
        assert old_view["tags"] == ["Pillow", "Roundtrip"]
        assert reopened.get(created[1]["asset_id"]) is None
        assert reopened.resolve_file(updated.asset_id)[1].read_bytes()
        assert reopened.search(query="compatible")["total"] == 1
        final = _schema_snapshot(data_root)

        schema_actions = {
            "new_tables": sorted(after_init[0] - before[0]),
            "new_indexes": sorted(after_init[1] - before[1]),
            "altered_asset_columns": sorted(after_init[2] - before[2]),
            "updated_at_backfilled": before[3] - after_init[3],
            "embedding_table_created": (
                "asset_embeddings" in after_init[0]
                and "asset_embeddings" not in before[0]
            ),
            "old_ob_read_after_rm": True,
            "final_tables_stable": final[0] == after_init[0],
        }
        del reopened
        gc.collect()
    return {
        "output_comparisons": comparisons,
        "bidirectional_data": True,
        "schema_actions": schema_actions,
    }


def run_probe(ombre_brain_root=None):
    import PIL

    sanitizer = _sanitizer_probe()
    service = _service_probe()
    with tempfile.TemporaryDirectory(prefix="rm-stage7f-mcp-") as raw_root:
        runtime = create_local_runtime(raw_root)
        mcp = _mcp_schema_probe(runtime)
        del runtime
        gc.collect()
    result = {
        "pillow_version": PIL.__version__,
        "sanitizer": sanitizer,
        "same_version_deterministic": True,
        "service": service,
        "mcp": mcp,
    }
    if ombre_brain_root:
        result["ombre_brain"] = _ob_cross_probe(ombre_brain_root)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ombre-brain-root")
    args = parser.parse_args()
    print(
        json.dumps(
            run_probe(args.ombre_brain_root),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
