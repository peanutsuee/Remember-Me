# SPDX-License-Identifier: CPAL-1.0
"""Published data compatibility descriptors."""

from .ombre_brain import (
    ASSET_ID_PATTERN,
    ASSETS_DIRECTORY,
    DATABASE_FILENAME,
    MAX_IMAGE_PIXELS,
    MAX_UPLOAD_BYTES,
    OB_COMPATIBILITY_VERSION,
    SUPPORTED_IMAGE_FORMATS,
    SUPPORTED_IMAGE_MIME_TYPES,
    asset_relative_path,
)

__all__ = [
    "ASSET_ID_PATTERN",
    "ASSETS_DIRECTORY",
    "DATABASE_FILENAME",
    "MAX_IMAGE_PIXELS",
    "MAX_UPLOAD_BYTES",
    "OB_COMPATIBILITY_VERSION",
    "SUPPORTED_IMAGE_FORMATS",
    "SUPPORTED_IMAGE_MIME_TYPES",
    "asset_relative_path",
]
