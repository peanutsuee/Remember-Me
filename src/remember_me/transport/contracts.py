# SPDX-License-Identifier: CPAL-1.0
"""Public upload request and result contracts."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PublicUploadRequest:
    expected_bytes: int
    filename: str
    mime_type: str = "application/octet-stream"


@dataclass(frozen=True)
class PublicUploadResult:
    asset_id: str
    source_sha256: str
    stored_bytes: int
    deduplicated: bool


class UploadReceiver(Protocol):
    def receive_upload(
        self,
        request: PublicUploadRequest,
        content: bytes,
    ) -> PublicUploadResult:
        ...
