# SPDX-License-Identifier: CPAL-1.0
"""Public HTTP schemas kept separate from internal Core records."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from remember_me.core import AssetRecord


class PublicAsset(BaseModel):
    asset_id: str
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
    tags: List[str]


class UploadAssetResponse(PublicAsset):
    deduplicated: bool


class SearchAssetsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: List[PublicAsset]


class MetadataPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class DeleteAssetResponse(BaseModel):
    asset_id: str
    deleted: bool
    cleanup_pending: bool


class AboutResponse(BaseModel):
    project_name: str
    project_version: str
    http_api_version: str
    dashboard_version: str
    mcp_api_version: str
    attribution: str
    original_creator: str
    official_repository: str
    license: str
    data_compatibility_version: str


def asset_to_public_response(asset: AssetRecord) -> PublicAsset:
    return PublicAsset(
        asset_id=asset.asset_id,
        original_filename=asset.original_filename,
        mime_type=asset.mime_type,
        kind=asset.kind,
        decoded_bytes=asset.decoded_bytes,
        stored_bytes=asset.stored_bytes,
        width=asset.width,
        height=asset.height,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        title=asset.title,
        description=asset.description,
        tags=list(asset.tags),
    )
