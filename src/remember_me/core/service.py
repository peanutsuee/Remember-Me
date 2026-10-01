# SPDX-License-Identifier: CPAL-1.0
"""Host-independent orchestration for Remember-Me assets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import math
import re
import secrets
import threading
import time

from .clock import utc_iso_seconds
from .contracts import ImportClassificationState
from .errors import (
    AssetConflictError,
    AssetFileUnavailable,
    AssetIdConflict,
    AssetUnavailable,
    BlobUnavailableOrCorrupt,
    InvalidImportRecord,
    InvalidMetadata,
    InvalidVerificationCursor,
    InvalidVerificationLimit,
    ImportMetadataValidationError,
    StorageFailure,
    StoredFileConflict,
    StoredShaMismatch,
    StoredShaOwnershipConflict,
    UnsupportedAssetKind,
    UploadSizeMismatch,
    VerificationAssetMissing,
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
)
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
    GetAssetRequest,
    ImportAssetDisposition,
    ImportAssetResult,
    ImportAssetTag,
    IngestImageResult,
    ReindexEmbeddingsResult,
    ResolvedAsset,
    SearchAssetsResult,
    SearchResultItem,
)
from .normalization import (
    normalize_description,
    normalize_filename,
    normalize_import_description,
    normalize_import_title,
    normalize_tags,
    normalize_title,
    tag_comparison_key,
    validate_import_filename,
    validate_import_tags,
)
from .vector_index import (
    canonical_index_text,
    cosine_similarity,
    index_content_hash,
    validate_embedding_vector,
)
from remember_me.search.keyword import keyword_search


_ASSET_ID = re.compile(r"[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MIME_EXTENSION = {"image/png": ".png", "image/jpeg": ".jpg"}


@dataclass
class _VerificationSession:
    snapshot_id: str
    target_identity: str
    generation: int
    total_count: int
    kind: str | None
    last_used_at: float
    closed: bool = False
    finalizing: bool = False
    expected_cursor: str = ""
    consumed_cursors: set[str] = field(default_factory=set)
    cursor_positions: dict[str, str] = field(default_factory=dict)
    pending_asset_ids: set[str] = field(default_factory=set)
    scanned_records: dict[str, AssetVerificationRecord] = field(
        default_factory=dict
    )
    verified_results: dict[str, AssetBlobVerificationResult] = field(
        default_factory=dict
    )
    blob_verified_count: int = 0
    reached_end: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)


class RememberMeService:
    verification_session_limit = 32
    verification_session_ttl_seconds = 15 * 60

    def __init__(
        self,
        repository,
        blob_store,
        image_sanitizer,
        clock,
        vector_provider,
        semantic_min_score=0.42,
    ):
        if isinstance(semantic_min_score, bool) or not isinstance(
            semantic_min_score, (int, float)
        ):
            raise ValueError("invalid_semantic_min_score")
        try:
            threshold = float(semantic_min_score)
        except (OverflowError, TypeError, ValueError):
            raise ValueError("invalid_semantic_min_score") from None
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError("invalid_semantic_min_score")
        self.repository = repository
        self.blob_store = blob_store
        self.image_sanitizer = image_sanitizer
        self.clock = clock
        self.vector_provider = vector_provider
        self.semantic_min_score = threshold
        self._verification_sessions: dict[str, _VerificationSession] = {}
        self._verification_sessions_lock = threading.RLock()

    def _now_text(self):
        if self.clock is None:
            raise StorageFailure()
        return utc_iso_seconds(self.clock.now())

    @staticmethod
    def _blob_key(stored_sha256, extension):
        return "assets/{}/{}{}".format(
            stored_sha256[:2],
            stored_sha256,
            extension,
        )

    def ingest_image(self, request):
        if type(request.content) is not bytes:
            raise UploadSizeMismatch()
        if (
            type(request.expected_bytes) is not int
            or isinstance(request.expected_bytes, bool)
            or request.expected_bytes != len(request.content)
        ):
            raise UploadSizeMismatch()
        cleaned = self.image_sanitizer.sanitize(
            request.content,
            request.mime_type,
        )
        source_sha = hashlib.sha256(request.content).hexdigest()
        stored_sha = hashlib.sha256(cleaned.content).hexdigest()
        existing = self.repository.find_by_stored_sha256(stored_sha)
        if existing is not None:
            return IngestImageResult(existing, True)
        filename = normalize_filename(request.filename)
        title = normalize_title(request.title)
        description = normalize_description(request.description)
        tags = normalize_tags(request.tags)
        timestamp = self._now_text()
        blob_key = self._blob_key(stored_sha, cleaned.extension)
        asset = AssetRecord(
            asset_id=secrets.token_hex(16),
            source_sha256=source_sha,
            stored_sha256=stored_sha,
            stored_relpath=blob_key,
            original_filename=filename,
            mime_type=cleaned.mime_type,
            kind="image",
            decoded_bytes=len(request.content),
            stored_bytes=len(cleaned.content),
            width=cleaned.width,
            height=cleaned.height,
            created_at=timestamp,
            updated_at=timestamp,
            title=title,
            description=description,
            tags=tags,
        )
        created_blob = self.blob_store.put(blob_key, cleaned.content)
        try:
            stored = self.repository.add(asset)
            return IngestImageResult(stored, False)
        except AssetConflictError as conflict:
            winner = self.repository.find_by_stored_sha256(stored_sha)
            if winner is not None:
                return IngestImageResult(winner, True)
            if created_blob:
                self.blob_store.delete(blob_key)
            raise
        except Exception:
            if created_blob:
                self.blob_store.delete(blob_key)
            raise

    @staticmethod
    def _parse_import_time(value):
        if type(value) is not str or not value or "." in value:
            raise ImportMetadataValidationError()
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ImportMetadataValidationError() from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ImportMetadataValidationError()
        return parsed

    def _validate_import_request(self, request):
        if (
            type(request.asset_id) is not str
            or _ASSET_ID.fullmatch(request.asset_id) is None
            or type(request.source_sha256) is not str
            or _SHA256.fullmatch(request.source_sha256) is None
            or type(request.stored_sha256) is not str
            or _SHA256.fullmatch(request.stored_sha256) is None
            or type(request.cleaned_bytes) is not bytes
        ):
            raise InvalidImportRecord()
        actual_sha = hashlib.sha256(request.cleaned_bytes).hexdigest()
        if actual_sha != request.stored_sha256:
            raise StoredShaMismatch()
        for value in (
            request.decoded_bytes,
            request.stored_bytes,
            request.width,
            request.height,
        ):
            if type(value) is not int or value <= 0:
                raise InvalidImportRecord()
        if request.stored_bytes != len(request.cleaned_bytes):
            raise InvalidImportRecord()
        if request.kind != "image":
            raise UnsupportedAssetKind()
        if request.mime_type not in _MIME_EXTENSION:
            # validate_cleaned owns stable image format/mime errors.
            self.image_sanitizer.validate_cleaned(
                request.cleaned_bytes,
                request.mime_type,
            )
            raise ImportMetadataValidationError()
        validate_import_filename(request.original_filename)
        title = normalize_import_title(request.title)
        description = normalize_import_description(request.description)
        created = self._parse_import_time(request.created_at)
        updated = self._parse_import_time(request.updated_at)
        if created > updated:
            raise ImportMetadataValidationError()
        if type(request.tags) is not tuple:
            raise ImportMetadataValidationError()
        tag_values = []
        for tag in request.tags:
            if type(tag) is not ImportAssetTag:
                raise ImportMetadataValidationError()
            tag_time = self._parse_import_time(tag.created_at)
            if tag_time < created or tag_time > updated:
                raise ImportMetadataValidationError()
            tag_values.append(tag.value)
        ordered = validate_import_tags(tuple(tag_values))
        tag_times = {
            tag_comparison_key(tag.value): tag.created_at for tag in request.tags
        }
        tags = tuple(
            ImportAssetTag(display, tag_times[identity])
            for identity, display in ordered
        )
        inspected = self.image_sanitizer.validate_cleaned(
            request.cleaned_bytes,
            request.mime_type,
        )
        if inspected.width != request.width or inspected.height != request.height:
            raise ImportMetadataValidationError()
        extension = _MIME_EXTENSION[request.mime_type]
        asset = AssetRecord(
            asset_id=request.asset_id,
            source_sha256=request.source_sha256,
            stored_sha256=request.stored_sha256,
            stored_relpath=self._blob_key(request.stored_sha256, extension),
            original_filename=request.original_filename,
            mime_type=request.mime_type,
            kind=request.kind,
            decoded_bytes=request.decoded_bytes,
            stored_bytes=request.stored_bytes,
            width=request.width,
            height=request.height,
            created_at=request.created_at,
            updated_at=request.updated_at,
            title=title,
            description=description,
            tags=tuple(tag.value for tag in tags),
        )
        return asset, tags

    @staticmethod
    def _same_import(asset, tags, expected_asset, expected_tags):
        return asset == expected_asset and tags == expected_tags

    @staticmethod
    def _permission_wrapped(error):
        seen = set()
        current = error
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, PermissionError):
                return True
            current = current.__cause__ or current.__context__
        return False

    def _read_blob_verified(self, asset, *, retry_permission):
        attempts = 10 if retry_permission else 1
        failure = False
        for attempt in range(attempts):
            try:
                content = self.blob_store.read(asset.stored_relpath)
            except Exception as error:
                if (
                    retry_permission
                    and self._permission_wrapped(error)
                    and attempt + 1 < attempts
                ):
                    time.sleep(0.01)
                    continue
                failure = True
                break
            if (
                len(content) != asset.stored_bytes
                or hashlib.sha256(content).hexdigest() != asset.stored_sha256
            ):
                failure = True
            else:
                return content
            break
        if failure:
            error = BlobUnavailableOrCorrupt()
            error.__suppress_context__ = True
            raise error
        raise BlobUnavailableOrCorrupt()

    def _classify_import(self, state, asset, tags):
        existing = state.existing_asset
        owner = state.stored_sha_owner
        if existing is not None:
            if not self._same_import(
                existing,
                state.existing_tags,
                asset,
                tags,
            ):
                raise AssetIdConflict()
            if owner is None or owner.asset_id != existing.asset_id:
                raise StorageFailure("import_classification_invariant")
            if state.stored_sha_owner_tags != state.existing_tags:
                raise StorageFailure("import_classification_invariant")
            return "idempotent"
        if state.existing_tags:
            raise StorageFailure("import_classification_invariant")
        if owner is not None:
            if owner.asset_id == asset.asset_id:
                raise StorageFailure("import_classification_invariant")
            raise StoredShaOwnershipConflict()
        if state.stored_sha_owner_tags:
            raise StorageFailure("import_classification_invariant")
        return "new"

    def import_asset(self, request):
        asset, tags = self._validate_import_request(request)
        state = self.repository.read_import_classification_state(
            asset.asset_id,
            asset.stored_sha256,
        )
        classification = self._classify_import(state, asset, tags)
        if classification == "idempotent":
            self._read_blob_verified(asset, retry_permission=False)
            disposition = (
                ImportAssetDisposition.WOULD_SKIP_IDEMPOTENT
                if request.dry_run
                else ImportAssetDisposition.SKIPPED_IDEMPOTENT
            )
            return ImportAssetResult(asset, tags, disposition)
        if request.dry_run:
            if self.blob_store.exists(asset.stored_relpath):
                self._read_blob_verified(asset, retry_permission=False)
            return ImportAssetResult(
                asset,
                tags,
                ImportAssetDisposition.WOULD_IMPORT,
            )
        try:
            created_blob = self.blob_store.put(
                asset.stored_relpath,
                request.cleaned_bytes,
            )
        except StoredFileConflict:
            raise BlobUnavailableOrCorrupt() from None
        if not created_blob:
            self._read_blob_verified(asset, retry_permission=True)
        try:
            stored = self.repository.add_import(asset, tags)
        except AssetConflictError as conflict:
            state = self.repository.read_import_classification_state(
                asset.asset_id,
                asset.stored_sha256,
            )
            try:
                classification = self._classify_import(state, asset, tags)
            except (AssetIdConflict, StoredShaOwnershipConflict):
                if (
                    created_blob
                    and state.stored_sha_owner is None
                ):
                    self.blob_store.delete(asset.stored_relpath)
                raise
            if classification != "idempotent":
                if created_blob:
                    self.blob_store.delete(asset.stored_relpath)
                raise conflict
            self._read_blob_verified(asset, retry_permission=True)
            return ImportAssetResult(
                asset,
                tags,
                ImportAssetDisposition.SKIPPED_IDEMPOTENT,
            )
        except Exception:
            if created_blob:
                self.blob_store.delete(asset.stored_relpath)
            raise
        return ImportAssetResult(
            stored,
            tags,
            ImportAssetDisposition.IMPORTED,
        )

    def get_asset(self, request):
        asset = self.repository.get(request.asset_id)
        if asset is None:
            raise AssetUnavailable()
        return asset

    def update_metadata(self, request):
        return self.repository.update_metadata(request, self._now_text())

    def delete_asset(self, request):
        asset = self.repository.get(request.asset_id)
        if asset is None:
            return DeleteAssetResult(request.asset_id, False, False)
        quarantine = self.blob_store.quarantine(asset.stored_relpath)
        try:
            deleted = self.repository.delete(asset.asset_id)
        except Exception:
            self.blob_store.restore_quarantined(
                quarantine,
                asset.stored_relpath,
            )
            raise
        if not deleted:
            self.blob_store.restore_quarantined(
                quarantine,
                asset.stored_relpath,
            )
            return DeleteAssetResult(asset.asset_id, False, False)
        finalized = self.blob_store.finalize_quarantined(quarantine)
        return DeleteAssetResult(
            asset.asset_id,
            True,
            cleanup_pending=not finalized,
        )

    def resolve_asset(self, request):
        asset = self.repository.get(request.asset_id)
        if asset is None:
            raise AssetUnavailable()
        if not self.blob_store.exists(asset.stored_relpath):
            raise AssetFileUnavailable()
        return ResolvedAsset(asset, asset.stored_relpath)

    async def search_assets(self, request):
        fallback = self.repository.search(request)
        query = request.query.strip() if type(request.query) is str else ""
        if not query:
            return fallback
        try:
            if not self.vector_provider.enabled:
                return fallback
            model_before = self.vector_provider.model_id
            if type(model_before) is not str or not model_before.strip():
                return fallback
        except Exception:
            return fallback
        try:
            query_vector = validate_embedding_vector(
                await self.vector_provider.embed(query)
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return fallback
        if query_vector is None:
            return fallback
        try:
            if self.vector_provider.model_id != model_before:
                return fallback
        except Exception:
            return fallback
        assets = self.repository.list_assets_for_search()
        embeddings = self.repository.list_embeddings_for_search(model_before)
        if not embeddings:
            return fallback
        expanded = replace(request, offset=0, limit=max(1, len(assets)))
        keyword = keyword_search(assets, expanded)
        asset_by_id = {asset.asset_id: asset for asset in assets}
        semantic_scores = {}
        for record in embeddings:
            asset = asset_by_id.get(record.asset_id)
            if asset is None:
                continue
            text = canonical_index_text(asset)
            if (
                not text
                or record.content_hash != index_content_hash(text)
                or record.model_id != model_before
            ):
                continue
            score = cosine_similarity(query_vector, record.embedding)
            if (
                score is not None
                and score > 0.0
                and score >= self.semantic_min_score
            ):
                semantic_scores[asset.asset_id] = score
        combined = []
        for item in keyword.results:
            score = semantic_scores.pop(item.asset.asset_id, None)
            if score is None:
                combined.append(item)
            else:
                combined.append(
                    SearchResultItem(
                        asset=item.asset,
                        match_reasons=item.match_reasons + ("semantic",),
                        semantic_score=score,
                    )
                )
        semantic_only = []
        filtered_ids = {
            item.asset.asset_id
            for item in keyword_search(
                assets,
                replace(expanded, query=""),
            ).results
        }
        for asset_id, score in semantic_scores.items():
            if asset_id in filtered_ids:
                semantic_only.append(
                    SearchResultItem(
                        asset=asset_by_id[asset_id],
                        match_reasons=("semantic",),
                        semantic_score=score,
                    )
                )
        semantic_only.sort(
            key=lambda item: (
                -item.semantic_score,
                -datetime.fromisoformat(item.asset.created_at).timestamp(),
                item.asset.asset_id,
            )
        )
        combined.extend(semantic_only)
        total = len(combined)
        selected = combined[
            max(0, request.offset) : max(0, request.offset)
            + max(0, request.limit)
        ]
        return SearchAssetsResult(
            total=total,
            offset=request.offset,
            limit=request.limit,
            results=tuple(selected),
        )

    async def reindex_embeddings(self, request):
        if type(request.limit) is not int or not 1 <= request.limit <= 500:
            raise InvalidMetadata()
        if request.asset_id == "":
            assets = self.repository.list_for_embedding(request.limit)
        else:
            if (
                type(request.asset_id) is not str
                or not request.asset_id.strip()
            ):
                raise AssetUnavailable()
            asset = self.repository.get(request.asset_id)
            if asset is None:
                raise AssetUnavailable()
            assets = (asset,)
        provider = self.vector_provider
        provider_state_failed = False
        try:
            enabled = bool(provider.enabled)
            model_id = provider.model_id
            if type(model_id) is not str or not model_id.strip():
                provider_state_failed = True
        except Exception:
            provider_state_failed = True
            enabled = False
            model_id = ""

        def provider_unchanged():
            try:
                return (
                    self.vector_provider is provider
                    and bool(provider.enabled) == enabled
                    and provider.model_id == model_id
                )
            except Exception:
                return False

        indexed = skipped = failed = 0
        for asset in assets:
            try:
                text = canonical_index_text(asset)
                content_hash = index_content_hash(text) if text else ""
                existing = self.repository.get_embedding(asset.asset_id)
                current = (
                    existing is not None
                    and existing.model_id == model_id
                    and existing.content_hash == content_hash
                    and bool(text)
                )
                if not text:
                    if existing is not None:
                        self.repository.delete_embedding(asset.asset_id)
                    skipped += 1
                    continue
                if provider_state_failed:
                    failed += 1
                    continue
                if not provider_unchanged():
                    failed += 1
                    continue
                if not enabled:
                    if not current and existing is not None:
                        self.repository.delete_embedding(asset.asset_id)
                    skipped += 1
                    continue
                if current:
                    skipped += 1
                    continue
                try:
                    vector = validate_embedding_vector(
                        await provider.embed(text)
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    failed += 1
                    continue
                if vector is None:
                    failed += 1
                    continue
                if not provider_unchanged():
                    failed += 1
                    continue
                record = EmbeddingRecord(
                    asset_id=asset.asset_id,
                    embedding=vector,
                    model_id=model_id,
                    content_hash=content_hash,
                    updated_at=asset.updated_at,
                )
                if self.repository.store_embedding_if_asset_current(
                    asset,
                    record,
                ):
                    indexed += 1
                else:
                    failed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                failed += 1
        return ReindexEmbeddingsResult(
            enabled=enabled,
            model_id=model_id,
            scanned=len(assets),
            indexed=indexed,
            skipped=skipped,
            failed=failed,
        )

    def _read_asset_verification_state(self):
        return self.repository.get_asset_verification_state()

    def _verification_session(self, snapshot_id):
        if type(snapshot_id) is not str:
            raise VerificationSnapshotInvalid()
        with self._verification_sessions_lock:
            session = self._verification_sessions.get(snapshot_id)
        if session is None:
            raise VerificationSnapshotInvalid()
        with session.lock:
            if session.closed:
                raise VerificationSnapshotClosed()
            now = time.monotonic()
            if now - session.last_used_at > self.verification_session_ttl_seconds:
                session.closed = True
                raise VerificationSnapshotExpired()
            session.last_used_at = now
        return session

    def _assert_generation(self, session):
        if self._read_asset_verification_state() != (
            session.target_identity,
            session.generation,
        ):
            raise VerificationSnapshotChanged()

    def begin_asset_verification(self, request):
        if type(request.kind) not in (str, type(None)):
            raise VerificationRecordInvalid()
        if request.kind not in ("image", None):
            raise VerificationRecordInvalid()
        with self._verification_sessions_lock:
            active = sum(
                not session.closed
                for session in self._verification_sessions.values()
            )
            if active >= self.verification_session_limit:
                raise VerificationUnavailable()
        try:
            first = self._read_asset_verification_state()
            total = self.repository.count_assets_for_verification(request.kind)
            second = self._read_asset_verification_state()
            third = self._read_asset_verification_state()
        except Exception:
            raise VerificationInternalError() from None
        if first != second or second != third:
            raise VerificationSnapshotChanged()
        snapshot_id = secrets.token_urlsafe(32)
        session = _VerificationSession(
            snapshot_id=snapshot_id,
            target_identity=first[0],
            generation=first[1],
            total_count=total,
            kind=request.kind,
            last_used_at=time.monotonic(),
        )
        with self._verification_sessions_lock:
            self._verification_sessions[snapshot_id] = session
        return AssetVerificationSnapshot(
            snapshot_id,
            first[1],
            total,
            first[0],
            request.kind,
        )

    def list_asset_verification_page(self, request):
        if type(request.limit) is not int or not 1 <= request.limit <= 500:
            raise InvalidVerificationLimit()
        if type(request.cursor) is not str:
            raise InvalidVerificationCursor()
        session = self._verification_session(request.snapshot_id)
        with session.lock:
            if request.cursor in session.consumed_cursors:
                raise VerificationPageOutOfOrder()
            if request.cursor != session.expected_cursor:
                raise InvalidVerificationCursor()
            if session.pending_asset_ids - session.verified_results.keys():
                raise VerificationIncomplete()
            last_id = session.cursor_positions.get(request.cursor, "")
            self._assert_generation(session)
            try:
                records, has_more = (
                    self.repository.list_assets_for_verification_after(
                        session.kind,
                        last_id,
                        request.limit,
                    )
                )
            except StorageFailure:
                raise VerificationInternalError() from None
            self._assert_generation(session)
            if not isinstance(records, tuple) or any(
                type(record) is not AssetVerificationRecord
                for record in records
            ):
                raise VerificationRecordInvalid()
            session.consumed_cursors.add(request.cursor)
            for record in records:
                session.scanned_records[record.asset_id] = record
            session.pending_asset_ids = {record.asset_id for record in records}
            if has_more:
                next_cursor = secrets.token_urlsafe(24)
                session.cursor_positions[next_cursor] = (
                    records[-1].asset_id if records else last_id
                )
                session.expected_cursor = next_cursor
            else:
                next_cursor = ""
                session.expected_cursor = secrets.token_urlsafe(24)
                session.reached_end = True
            return AssetVerificationPage(
                session.snapshot_id,
                records,
                next_cursor,
                has_more,
                session.total_count,
                session.generation,
            )

    def _revoke_verification(self, session, asset_id):
        session.verified_results.pop(asset_id, None)
        session.blob_verified_count = len(session.verified_results)

    def _read_verification_blob(self, session, record):
        asset = self.repository.get(record.asset_id)
        if asset is None:
            raise VerificationAssetMissing()
        try:
            if not self.blob_store.exists(asset.stored_relpath):
                raise VerificationBlobMissing()
            return self.blob_store.read(asset.stored_relpath)
        except VerificationBlobMissing:
            raise
        except Exception:
            raise VerificationBlobUnreadable() from None

    def verify_asset_blob(self, request):
        session = self._verification_session(request.snapshot_id)
        if type(request.asset_id) is not str:
            raise VerificationAssetNotScanned()
        if type(request.expected_sha256) is not str:
            raise VerificationBlobChecksumMismatch()
        if type(request.expected_size) is not int:
            raise VerificationBlobSizeMismatch()
        if request.expected_bytes is not None and type(
            request.expected_bytes
        ) is not bytes:
            raise VerificationBlobBytesMismatch()
        with session.lock:
            record = session.scanned_records.get(request.asset_id)
            if record is None:
                raise VerificationAssetNotScanned()
            self._assert_generation(session)
            try:
                content = self._read_verification_blob(session, record)
                actual_sha = hashlib.sha256(content).hexdigest()
                actual_size = len(content)
                if (
                    request.expected_sha256 != record.stored_sha256
                    or actual_sha != record.stored_sha256
                ):
                    raise VerificationBlobChecksumMismatch()
                if (
                    request.expected_size != record.stored_bytes
                    or actual_size != record.stored_bytes
                ):
                    raise VerificationBlobSizeMismatch()
                if (
                    request.expected_bytes is not None
                    and content != request.expected_bytes
                ):
                    raise VerificationBlobBytesMismatch()
                self._assert_generation(session)
            except (
                VerificationBlobChecksumMismatch,
                VerificationBlobSizeMismatch,
                VerificationBlobBytesMismatch,
                VerificationBlobMissing,
                VerificationBlobUnreadable,
            ):
                self._revoke_verification(session, request.asset_id)
                raise
            result = AssetBlobVerificationResult(
                session.snapshot_id,
                record.asset_id,
                True,
                actual_sha,
                actual_size,
                True,
                True,
                (
                    None
                    if request.expected_bytes is None
                    else content == request.expected_bytes
                ),
                session.generation,
            )
            session.verified_results[record.asset_id] = result
            session.blob_verified_count = len(session.verified_results)
            return result

    def _fresh_verification_rescan(self, session):
        last_id = ""
        scanned = 0
        while True:
            records, has_more = self.repository.list_assets_for_verification_after(
                session.kind,
                last_id,
                500,
            )
            for record in records:
                content = self._read_verification_blob(session, record)
                if hashlib.sha256(content).hexdigest() != record.stored_sha256:
                    raise VerificationBlobChecksumMismatch()
                if len(content) != record.stored_bytes:
                    raise VerificationBlobSizeMismatch()
                scanned += 1
                last_id = record.asset_id
            if not has_more:
                return scanned

    def complete_asset_verification(self, request):
        session = self._verification_session(request.snapshot_id)
        with session.lock:
            if session.finalizing:
                raise VerificationIncomplete()
            if (
                not session.reached_end
                or len(session.scanned_records) != session.total_count
                or len(session.verified_results) != session.total_count
            ):
                raise VerificationIncomplete()
            session.finalizing = True
        try:
            self._assert_generation(session)
            rescanned = self._fresh_verification_rescan(session)
            self._assert_generation(session)
            total, duplicate_assets, duplicate_sha = (
                self.repository.get_asset_verification_integrity(session.kind)
            )
            self._assert_generation(session)
            unchanged = total == session.total_count
            complete = (
                unchanged
                and rescanned == session.total_count
                and duplicate_assets == 0
                and duplicate_sha == 0
            )
            return AssetVerificationCompletion(
                session.snapshot_id,
                session.target_identity,
                session.generation,
                session.total_count,
                len(session.scanned_records),
                len(session.verified_results),
                duplicate_assets,
                duplicate_sha,
                unchanged,
                complete,
            )
        except (
            VerificationBlobChecksumMismatch,
            VerificationBlobSizeMismatch,
            VerificationBlobMissing,
            VerificationBlobUnreadable,
            VerificationSnapshotChanged,
        ):
            raise
        except BaseException:
            raise
        finally:
            with session.lock:
                session.finalizing = False
                session.closed = True


__all__ = ["RememberMeService"]
