# SPDX-License-Identifier: CPAL-1.0
import sqlite3
import struct
import zlib
from pathlib import Path

import pytest

from remember_me.compat.ombre_brain import (
    ASSET_ID_PATTERN,
    MAX_IMAGE_PIXELS,
    MAX_UPLOAD_BYTES,
    OB_SCHEMA_SQL,
    SUPPORTED_IMAGE_FORMATS,
    TABLE_COLUMNS,
    asset_relative_path,
)


def _png_chunk(kind, payload):
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _generated_png(width=1, height=1):
    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = b"\x00" + (b"\x00\x00\x00\xff" * width)
    return (
        signature
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(row * height))
        + _png_chunk(b"IEND", b"")
    )


def test_compatibility_constants_and_content_path():
    assert ASSET_ID_PATTERN == r"[0-9a-f]{32}"
    assert MAX_UPLOAD_BYTES == 10 * 1024 * 1024
    assert MAX_IMAGE_PIXELS == 20_000_000
    assert SUPPORTED_IMAGE_FORMATS == ("PNG", "JPEG")
    digest = "a" * 64
    assert asset_relative_path(digest, ".png") == (
        "assets/aa/" + digest + ".png"
    )
    assert asset_relative_path(digest, ".jpg") == (
        "assets/aa/" + digest + ".jpg"
    )
    with pytest.raises(ValueError):
        asset_relative_path("not-a-hash", ".png")


def test_schema_contract_uses_only_temporary_sqlite(tmp_path):
    database = tmp_path / "assets.sqlite3"
    with sqlite3.connect(str(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in OB_SCHEMA_SQL:
            connection.execute(statement)
        for table, expected_columns in TABLE_COLUMNS.items():
            actual = tuple(
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info({})".format(table)
                )
            )
            assert actual == expected_columns
    assert database.parent == tmp_path


def test_image_fixture_is_generated_in_memory(tmp_path):
    payload = _generated_png()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    path = tmp_path / "generated.png"
    path.write_bytes(payload)
    assert path.stat().st_size == len(payload)
    assert list(tmp_path.iterdir()) == [path]
