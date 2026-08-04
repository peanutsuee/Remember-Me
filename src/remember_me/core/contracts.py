# SPDX-License-Identifier: CPAL-1.0
"""Dependency injection and operation protocols for the public core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

from .models import (
    AssetBlobVerificationResult,
    AssetRecord,
    AssetVerificationCompletion,
    AssetVerificationPage,
    AssetVerificationRecord,
    AssetVerificationSnapshot,
    BeginAssetVerificationRequest,
    CompleteAssetVerificationRequest,
    DeleteAssetRequest,
    DeleteAssetResult,
    EmbeddingRecord,
    ReindexEmbeddingsRequest,
    ReindexEmbeddingsResult,
    GetAssetRequest,
    ImportAssetRequest,
    ImportAssetResult,
    ImportAssetTag,
    IngestImageRequest,
    IngestImageResult,
    ResolveAssetRequest,
    ResolvedAsset,
    SanitizedImage,
    SearchAssetsRequest,
    SearchAssetsResult,
    UpdateMetadataRequest,
    VerifyAssetBlobRequest,
    ListAssetVerificationPageRequest,
)


@dataclass(frozen=True)
class ImportClassificationState:
    existing_asset: Optional[AssetRecord]
    existing_tags: tuple[ImportAssetTag, ...]
    stored_sha_owner: Optional[AssetRecord]
    stored_sha_owner_tags: tuple[ImportAssetTag, ...]


class AssetRepository(Protocol):
    def get(self, asset_id: str) -> Optional[AssetRecord]:
        ...

    def add(self, asset: AssetRecord) -> AssetRecord:
        ...

    def add_import(
        self,
        asset: AssetRecord,
        tags: tuple[ImportAssetTag, ...],
    ) -> AssetRecord:
        ...

    def get_import_tags(
        self,
        asset_id: str,
    ) -> tuple[ImportAssetTag, ...]:
        ...

    def find_by_stored_sha256(
        self,
        stored_sha256: str,
    ) -> Optional[AssetRecord]:
        ...

    def read_import_classification_state(
        self,
        asset_id: str,
        stored_sha256: str,
    ) -> ImportClassificationState:
        ...

    def update_metadata(
        self,
        request: UpdateMetadataRequest,
        updated_at: str,
    ) -> AssetRecord:
        ...

    def delete(self, asset_id: str) -> bool:
        ...

    def search(
        self,
        request: SearchAssetsRequest,
        semantic_scores=None,
        assets=None,
    ) -> SearchAssetsResult:
        ...

    def list_assets_for_search(self):
        ...

    def list_for_embedding(self, limit: int = 100):
        ...

    def get_embedding(self, asset_id: str) -> Optional[EmbeddingRecord]:
        ...

    def list_embeddings_for_search(self, model_id: str):
        ...

    def delete_embedding(self, asset_id: str) -> bool:
        ...

    def store_embedding_if_asset_current(
        self,
        expected_asset: AssetRecord,
        embedding_record: EmbeddingRecord,
    ) -> bool:
        ...

    def store_embedding(
        self,
        asset_id: str,
        embedding,
        model: str,
        content_hash: str,
        updated_at: str,
    ) -> None:
        ...

    def get_asset_verification_state(self) -> tuple[str, int]:
        ...

    def count_assets_for_verification(self, kind: Optional[str]) -> int:
        ...

    def list_assets_for_verification_after(
        self,
        kind: Optional[str],
        last_asset_id: str,
        limit: int,
    ) -> tuple[tuple[AssetVerificationRecord, ...], bool]:
        ...

    def get_asset_verification_integrity(
        self,
        kind: Optional[str],
    ) -> tuple[int, int, int]:
        ...


class BlobStore(Protocol):
    def put(self, blob_key: str, content: bytes) -> bool:
        ...

    def read(self, blob_key: str) -> bytes:
        ...

    def delete(self, blob_key: str) -> None:
        ...

    def exists(self, blob_key: str) -> bool:
        ...

    def quarantine(self, blob_key: str) -> str:
        ...

    def restore_quarantined(
        self,
        quarantine_key: str,
        blob_key: str,
    ) -> None:
        ...

    def finalize_quarantined(self, quarantine_key: str) -> bool:
        ...


class ImageSanitizer(Protocol):
    def sanitize(self, content: bytes, claimed_mime_type: str) -> SanitizedImage:
        ...

    def validate_cleaned(
        self,
        content: bytes,
        claimed_mime_type: str,
    ) -> SanitizedImage:
        ...


class Clock(Protocol):
    def now(self) -> datetime:
        ...


class RememberMeCore(Protocol):
    def ingest_image(self, request: IngestImageRequest) -> IngestImageResult:
        ...

    def import_asset(self, request: ImportAssetRequest) -> ImportAssetResult:
        ...

    def get_asset(self, request: GetAssetRequest) -> AssetRecord:
        ...

    def update_metadata(self, request: UpdateMetadataRequest) -> AssetRecord:
        ...

    def delete_asset(self, request: DeleteAssetRequest) -> DeleteAssetResult:
        ...

    async def search_assets(
        self,
        request: SearchAssetsRequest,
    ) -> SearchAssetsResult:
        ...

    async def reindex_embeddings(
        self,
        request: ReindexEmbeddingsRequest,
    ) -> ReindexEmbeddingsResult:
        ...

    def resolve_asset(self, request: ResolveAssetRequest) -> ResolvedAsset:
        ...

    def begin_asset_verification(
        self,
        request: BeginAssetVerificationRequest,
    ) -> AssetVerificationSnapshot:
        ...

    def list_asset_verification_page(
        self,
        request: ListAssetVerificationPageRequest,
    ) -> AssetVerificationPage:
        ...

    def verify_asset_blob(
        self,
        request: VerifyAssetBlobRequest,
    ) -> AssetBlobVerificationResult:
        ...

    def complete_asset_verification(
        self,
        request: CompleteAssetVerificationRequest,
    ) -> AssetVerificationCompletion:
        ...
