# SPDX-License-Identifier: CPAL-1.0
"""Data-only compatibility contract for the integrated image store."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Dict, Tuple


OB_COMPATIBILITY_VERSION = "ombre-brain-assets-v1"
DATABASE_FILENAME = "assets.sqlite3"
ASSETS_DIRECTORY = "assets"
ASSET_ID_PATTERN = r"[0-9a-f]{32}"
SHA256_PATTERN = r"[0-9a-f]{64}"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
SUPPORTED_IMAGE_FORMATS = ("PNG", "JPEG")
SUPPORTED_IMAGE_MIME_TYPES = ("image/png", "image/jpeg")
TRANSPORT_MIME_TYPES = (
    "application/octet-stream",
    "image/jpeg",
    "image/png",
)
TITLE_MAX_CHARS = 200
DESCRIPTION_MAX_CHARS = 4000
TAG_MAX_CHARS = 64
TAG_MAX_COUNT = 30
TIME_FORMAT = "UTC ISO 8601 with an explicit offset, stored to whole seconds"

ASSET_COLUMNS = (
    "asset_id",
    "source_sha256",
    "stored_sha256",
    "stored_relpath",
    "original_filename",
    "mime_type",
    "kind",
    "decoded_bytes",
    "stored_bytes",
    "width",
    "height",
    "created_at",
    "title",
    "description",
    "updated_at",
)
ASSET_TAG_COLUMNS = (
    "asset_id",
    "tag_normalized",
    "tag_display",
    "created_at",
)
ASSET_EMBEDDING_COLUMNS = (
    "asset_id",
    "embedding",
    "model",
    "content_hash",
    "updated_at",
)

TABLE_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "assets": ASSET_COLUMNS,
    "asset_tags": ASSET_TAG_COLUMNS,
    "asset_embeddings": ASSET_EMBEDDING_COLUMNS,
}

OB_SCHEMA_SQL = (
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
        created_at TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE asset_tags (
        asset_id TEXT NOT NULL,
        tag_normalized TEXT NOT NULL,
        tag_display TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (asset_id, tag_normalized),
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE asset_embeddings (
        asset_id TEXT PRIMARY KEY,
        embedding TEXT NOT NULL,
        model TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
    )
    """,
)


def asset_relative_path(stored_sha256: str, extension: str) -> str:
    """Return the compatible content-addressed path for a cleaned image."""
    digest = (stored_sha256 or "").strip().lower()
    suffix = (extension or "").strip().lower()
    if not re.fullmatch(SHA256_PATTERN, digest):
        raise ValueError("invalid_stored_sha256")
    if suffix not in {".png", ".jpg"}:
        raise ValueError("invalid_image_extension")
    return str(PurePosixPath(ASSETS_DIRECTORY, digest[:2], digest + suffix))
