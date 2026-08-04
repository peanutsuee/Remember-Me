# SPDX-License-Identifier: CPAL-1.0
"""Public error boundary for the image core."""


class RememberMeError(Exception):
    """Base class for expected core failures with a stable public code."""

    code = "remember_me_error"

    def __init__(self, message=None):
        super().__init__(message or self.code)


class ImageValidationError(RememberMeError):
    """The supplied bytes are not an acceptable image."""

    code = "invalid_image"


class AssetNotFoundError(RememberMeError):
    """The requested asset is unavailable."""

    code = "asset_unavailable"


class AssetConflictError(RememberMeError):
    """Stored state conflicts with the requested operation."""

    code = "asset_conflict"


class StorageConsistencyError(RememberMeError):
    """Metadata and blob state could not be changed consistently."""

    code = "storage_failure"


class VectorUnavailableError(RememberMeError):
    """Optional vector functionality is unavailable."""

    code = "vector_unavailable"


class InvalidImage(ImageValidationError):
    code = "invalid_image"


class UnsupportedImageFormat(ImageValidationError):
    code = "unsupported_image_format"


class ImageMimeMismatch(ImageValidationError):
    code = "image_mime_mismatch"


class ImagePixelLimitExceeded(ImageValidationError):
    code = "image_pixel_limit"


class UploadSizeMismatch(RememberMeError):
    code = "upload_size_mismatch"


class UploadTooLarge(RememberMeError):
    code = "upload_too_large"


class InvalidMetadata(RememberMeError):
    code = "invalid_metadata"


class InvalidImportRecord(RememberMeError):
    code = "invalid_import_record"


class UnsupportedAssetKind(RememberMeError):
    code = "unsupported_asset_kind"


class StoredShaMismatch(RememberMeError):
    code = "stored_sha_mismatch"


class ImportMetadataValidationError(RememberMeError):
    code = "import_metadata_invalid"


class AssetIdConflict(AssetConflictError):
    code = "asset_id_conflict"


class StoredShaOwnershipConflict(AssetConflictError):
    code = "stored_sha_ownership_conflict"


class BlobUnavailableOrCorrupt(StorageConsistencyError):
    code = "blob_unavailable_or_corrupt"


class AssetUnavailable(AssetNotFoundError):
    code = "asset_unavailable"


class AssetFileUnavailable(AssetNotFoundError):
    code = "asset_file_unavailable"


class StoredFileConflict(AssetConflictError):
    code = "stored_file_conflict"


class StorageFailure(StorageConsistencyError):
    code = "storage_failure"


class VerificationError(RememberMeError):
    code = "verification_error"


class VerificationSnapshotInvalid(VerificationError):
    code = "verification_snapshot_invalid"


class VerificationSnapshotExpired(VerificationError):
    code = "verification_snapshot_expired"


class VerificationSnapshotChanged(VerificationError):
    code = "verification_snapshot_changed"


class VerificationSnapshotClosed(VerificationError):
    code = "verification_snapshot_closed"


class InvalidVerificationCursor(VerificationError):
    code = "invalid_verification_cursor"


class InvalidVerificationLimit(VerificationError):
    code = "invalid_verification_limit"


class VerificationPageOutOfOrder(VerificationError):
    code = "verification_page_out_of_order"


class VerificationAssetNotScanned(VerificationError):
    code = "verification_asset_not_scanned"


class VerificationAssetMissing(VerificationError):
    code = "verification_asset_missing"


class VerificationBlobMissing(VerificationError):
    code = "verification_blob_missing"


class VerificationBlobUnreadable(VerificationError):
    code = "verification_blob_unreadable"


class VerificationBlobChecksumMismatch(VerificationError):
    code = "verification_blob_checksum_mismatch"


class VerificationBlobSizeMismatch(VerificationError):
    code = "verification_blob_size_mismatch"


class VerificationBlobBytesMismatch(VerificationError):
    code = "verification_blob_bytes_mismatch"


class VerificationRecordInvalid(VerificationError):
    code = "verification_record_invalid"


class VerificationIncomplete(VerificationError):
    code = "verification_incomplete"


class VerificationUnavailable(VerificationError):
    code = "verification_unavailable"


class VerificationInternalError(VerificationError):
    code = "verification_internal_error"
