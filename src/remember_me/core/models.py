# SPDX-License-Identifier: CPAL-1.0
"""Immutable request and result models for the public core API."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    source_sha256: str
    stored_sha256: str
    stored_relpath: str
    original_filename: str
    mime_type: str
    kind: str
    decoded_bytes: int
    stored_bytes: int
    width: int
    height: int
    created_at: str
    updated_at: str
    title: str = ""
    description: str = ""
    tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EmbeddingRecord:
    asset_id: str
    embedding: Tuple[float, ...]
    model_id: str
    content_hash: str
    updated_at: str


@dataclass(frozen=True)
class ReindexEmbeddingsRequest:
    asset_id: str = ""
    limit: int = 100


@dataclass(frozen=True)
class ReindexEmbeddingsResult:
    enabled: bool
    model_id: str
    scanned: int
    indexed: int
    skipped: int
    failed: int

    def __post_init__(self) -> None:
        counters = (
            self.scanned,
            self.indexed,
            self.skipped,
            self.failed,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for value in counters
        ) or self.scanned != self.indexed + self.skipped + self.failed:
            raise ValueError("invalid_reindex_counters")


@dataclass(frozen=True)
class IngestImageRequest:
    content: bytes
    expected_bytes: int
    filename: str
    mime_type: str = "application/octet-stream"
    title: str = ""
    description: str = ""
    tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SanitizedImage:
    content: bytes
    mime_type: str
    extension: str
    width: int
    height: int


@dataclass(frozen=True)
class IngestImageResult:
    asset: AssetRecord
    deduplicated: bool


class ImportAssetDisposition(str, Enum):
    IMPORTED = "imported"
    SKIPPED_IDEMPOTENT = "skipped_idempotent"
    WOULD_IMPORT = "would_import"
    WOULD_SKIP_IDEMPOTENT = "would_skip_idempotent"


@dataclass(frozen=True)
class ImportAssetTag:
    value: str
    created_at: str


@dataclass(frozen=True)
class ImportAssetRequest:
    asset_id: str
    source_sha256: str
    stored_sha256: str
    cleaned_bytes: bytes = field(repr=False)
    original_filename: str = ""
    mime_type: str = "application/octet-stream"
    kind: str = "image"
    decoded_bytes: int = 0
    stored_bytes: int = 0
    width: int = 0
    height: int = 0
    created_at: str = ""
    updated_at: str = ""
    title: str = ""
    description: str = ""
    tags: Tuple[ImportAssetTag, ...] = ()
    dry_run: bool = False


@dataclass(frozen=True)
class ImportAssetResult:
    asset: AssetRecord
    tags: Tuple[ImportAssetTag, ...]
    disposition: ImportAssetDisposition


@dataclass(frozen=True)
class GetAssetRequest:
    asset_id: str


@dataclass(frozen=True)
class UpdateMetadataRequest:
    asset_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[Tuple[str, ...]] = None


@dataclass(frozen=True)
class DeleteAssetRequest:
    asset_id: str


@dataclass(frozen=True)
class DeleteAssetResult:
    asset_id: str
    deleted: bool
    cleanup_pending: bool = False


@dataclass(frozen=True)
class SearchAssetsRequest:
    query: str = ""
    tags: Tuple[str, ...] = ()
    kind: str = ""
    mime_type: str = ""
    created_from: str = ""
    created_to: str = ""
    limit: int = 20
    offset: int = 0


@dataclass(frozen=True)
class SearchResultItem:
    asset: AssetRecord
    match_reasons: Tuple[str, ...] = ()
    semantic_score: Optional[float] = None


@dataclass(frozen=True)
class SearchAssetsResult:
    total: int
    offset: int
    limit: int
    results: Tuple[SearchResultItem, ...]


@dataclass(frozen=True)
class ResolveAssetRequest:
    asset_id: str


@dataclass(frozen=True)
class ResolvedAsset:
    asset: AssetRecord
    blob_key: str


@dataclass(frozen=True)
class AssetVerificationTag:
    value: str
    created_at: str


@dataclass(frozen=True)
class BeginAssetVerificationRequest:
    kind: Optional[str] = "image"


@dataclass(frozen=True)
class AssetVerificationSnapshot:
    snapshot_id: str
    generation: int
    total_count: int
    target_identity: str
    kind: Optional[str]


@dataclass(frozen=True)
class ListAssetVerificationPageRequest:
    snapshot_id: str
    cursor: str = ""
    limit: int = 100


@dataclass(frozen=True)
class AssetVerificationRecord:
    asset_id: str
    source_sha256: str
    stored_sha256: str
    original_filename: str
    mime_type: str
    kind: str
    decoded_bytes: int
    stored_bytes: int
    width: int
    height: int
    created_at: str
    updated_at: str
    title: str
    description: str
    tags: Tuple[AssetVerificationTag, ...]


@dataclass(frozen=True)
class AssetVerificationPage:
    snapshot_id: str
    records: Tuple[AssetVerificationRecord, ...]
    next_cursor: str
    has_more: bool
    total_count: int
    generation: int


@dataclass(frozen=True)
class VerifyAssetBlobRequest:
    snapshot_id: str
    asset_id: str
    expected_sha256: str
    expected_size: int
    expected_bytes: Optional[bytes] = field(default=None, repr=False)


@dataclass(frozen=True)
class AssetBlobVerificationResult:
    snapshot_id: str
    asset_id: str
    readable: bool
    actual_sha256: str
    actual_size: int
    matches_expected_sha256: bool
    matches_expected_size: bool
    matches_expected_bytes: Optional[bool]
    generation: int


@dataclass(frozen=True)
class CompleteAssetVerificationRequest:
    snapshot_id: str


@dataclass(frozen=True)
class AssetVerificationCompletion:
    snapshot_id: str
    target_identity: str
    generation: int
    total_count: int
    scanned_count: int
    blob_verified_count: int
    duplicate_asset_count: int
    duplicate_stored_sha_count: int
    unchanged: bool
    complete: bool
