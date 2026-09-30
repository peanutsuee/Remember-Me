# SPDX-License-Identifier: CPAL-1.0
"""Nine public MCP tools backed by the existing Remember-Me runtime."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from typing import Annotated, Any, Optional

from mcp.types import (
    CallToolResult,
    ImageContent,
    TextContent,
    ToolAnnotations,
)
from PIL import Image, UnidentifiedImageError
from pydantic import Field

from remember_me.core import (
    AssetFileUnavailable,
    AssetUnavailable,
    GetAssetRequest,
    InvalidMetadata,
    RememberMeError,
    ReindexEmbeddingsRequest,
    ResolveAssetRequest,
    SearchAssetsRequest,
    StorageFailure,
    UpdateMetadataRequest,
)

from .schemas import (
    McpToolOutput,
    asset_to_public_dict,
    error_payload,
    ok_payload,
)
from .transfers import TransferError
from .viewer import VIEWER_TOOL_META


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "application/octet-stream",
    "image/jpeg",
    "image/png",
}
READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
NON_DESTRUCTIVE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
LINK_CREATION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)


def _safe_error(error: Exception) -> CallToolResult:
    if isinstance(error, (AssetUnavailable, AssetFileUnavailable)):
        payload = error_payload(
            "asset_unavailable",
            "Asset is unavailable.",
        )
    elif isinstance(error, InvalidMetadata):
        payload = error_payload(
            "validation_error",
            "The request is invalid.",
        )
    elif isinstance(error, TransferError):
        payload = error_payload(
            error.code,
            "The transfer is unavailable.",
        )
    elif isinstance(error, RememberMeError):
        payload = error_payload(
            error.code,
            "The asset operation could not be completed.",
        )
    else:
        payload = error_payload(
            "internal_error",
            "The operation could not be completed.",
        )
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(payload, separators=(",", ":")),
            )
        ],
        structuredContent=payload,
        isError=True,
    )


def _success(
    message: str,
    payload: dict[str, Any],
    *,
    extra_content=None,
    meta=None,
) -> CallToolResult:
    return CallToolResult(
        content=[
            TextContent(type="text", text=message),
            *(extra_content or []),
        ],
        structuredContent=payload,
        isError=False,
        _meta=meta,
    )


def read_cleaned_image(runtime, asset_id: str):
    resolved = runtime.service.resolve_asset(
        ResolveAssetRequest(asset_id)
    )
    content = runtime.blob_store.read(resolved.blob_key)
    asset = resolved.asset
    if (
        len(content) != asset.stored_bytes
        or len(content) > MAX_IMAGE_BYTES
        or hashlib.sha256(content).hexdigest() != asset.stored_sha256
    ):
        raise AssetFileUnavailable()
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            expected_format = (
                "PNG" if asset.mime_type == "image/png" else "JPEG"
            )
            if (
                image.format != expected_format
                or image.size != (asset.width, asset.height)
            ):
                raise AssetFileUnavailable()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AssetFileUnavailable() from exc
    return asset, content


def register_tools(mcp, runtime, uploads, downloads) -> None:
    @mcp.tool(
        name="rm_asset_upload_link",
        description=(
            "Create a single-use five-minute URL for uploading one PNG or "
            "JPEG to Remember-Me."
        ),
        annotations=LINK_CREATION,
        structured_output=True,
    )
    def rm_asset_upload_link(
        expected_bytes: Annotated[int, Field(ge=1, le=MAX_IMAGE_BYTES)],
        filename: str = "",
        mime_type: str = "application/octet-stream",
    ) -> Annotated[CallToolResult, McpToolOutput]:
        try:
            normalized_mime = str(mime_type).strip().casefold()
            if normalized_mime not in ALLOWED_MIME_TYPES:
                raise InvalidMetadata()
            ticket, upload_url = uploads.create(
                expected_bytes,
                str(filename),
                normalized_mime,
            )
            return _success(
                "A short-lived upload link was created.",
                ok_payload(
                    upload_id=ticket.upload_id,
                    upload_url=upload_url,
                    expires_at=ticket.expires_at,
                    max_bytes=MAX_IMAGE_BYTES,
                ),
            )
        except Exception as error:
            return _safe_error(error)

    @mcp.tool(
        name="rm_asset_upload_status",
        description="Read the status of a previously created upload ticket.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def rm_asset_upload_status(
        upload_id: str,
    ) -> Annotated[CallToolResult, McpToolOutput]:
        try:
            ticket = uploads.inspect(str(upload_id))
            values = {
                "upload_id": ticket.upload_id,
                "status": ticket.status,
            }
            if ticket.status == "completed" and ticket.asset is not None:
                values["asset"] = asset_to_public_dict(ticket.asset)
                values["deduplicated"] = bool(ticket.deduplicated)
            if ticket.status == "failed":
                values["error"] = {
                    "code": ticket.error_code or "upload_failed",
                    "message": "The upload could not be completed.",
                }
            return _success(
                "Upload status is {}.".format(ticket.status),
                ok_payload(**values),
            )
        except Exception as error:
            return _safe_error(error)

    @mcp.tool(
        name="rm_asset_get",
        description="Get safe metadata for one Remember-Me image asset.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def rm_asset_get(
        asset_id: str,
    ) -> Annotated[CallToolResult, McpToolOutput]:
        try:
            asset = runtime.service.get_asset(
                GetAssetRequest(str(asset_id))
            )
            return _success(
                "Asset metadata was retrieved.",
                ok_payload(asset=asset_to_public_dict(asset)),
            )
        except Exception as error:
            return _safe_error(error)

    @mcp.tool(
        name="rm_asset_update_metadata",
        description=(
            "Replace selected title, description, or tag metadata without "
            "changing image bytes."
        ),
        annotations=NON_DESTRUCTIVE_WRITE,
        structured_output=True,
    )
    def rm_asset_update_metadata(
        asset_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> Annotated[CallToolResult, McpToolOutput]:
        try:
            if title is None and description is None and tags is None:
                raise InvalidMetadata()
            asset = runtime.service.update_metadata(
                UpdateMetadataRequest(
                    asset_id=str(asset_id),
                    title=title,
                    description=description,
                    tags=tuple(tags) if tags is not None else None,
                )
            )
            return _success(
                "Asset metadata was updated.",
                ok_payload(asset=asset_to_public_dict(asset)),
            )
        except Exception as error:
            return _safe_error(error)

    @mcp.tool(
        name="rm_asset_reindex_embeddings",
        description=(
            "Rebuild a bounded batch of optional vector embeddings without "
            "changing image files or user metadata."
        ),
        annotations=NON_DESTRUCTIVE_WRITE,
        structured_output=True,
    )
    async def rm_asset_reindex_embeddings(
        asset_id: str = "",
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> Annotated[CallToolResult, McpToolOutput]:
        try:
            result = await runtime.service.reindex_embeddings(
                ReindexEmbeddingsRequest(
                    asset_id=str(asset_id),
                    limit=limit,
                )
            )
            if not result.enabled:
                return _success(
                    "Vector indexing is disabled; keyword search remains available.",
                    ok_payload(
                        enabled=False,
                        model_id=result.model_id,
                        selected=result.scanned,
                        indexed=result.indexed,
                        failed=result.failed,
                    ),
                )
            return _success(
                "The bounded embedding batch was processed.",
                ok_payload(
                    enabled=True,
                    model_id=result.model_id,
                    selected=result.scanned,
                    indexed=result.indexed,
                    failed=result.failed,
                ),
            )
        except Exception as error:
            return _safe_error(error)

    @mcp.tool(
        name="rm_asset_search",
        description=(
            "Search Remember-Me image metadata with stable keyword and filter "
            "semantics."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def rm_asset_search(
        query: str = "",
        tags: Optional[list[str]] = None,
        kind: str = "",
        mime_type: str = "",
        created_from: str = "",
        created_to: str = "",
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> Annotated[CallToolResult, McpToolOutput]:
        try:
            result = await runtime.service.search_assets(
                SearchAssetsRequest(
                    query=str(query),
                    tags=tuple(tags or ()),
                    kind=str(kind),
                    mime_type=str(mime_type),
                    created_from=str(created_from),
                    created_to=str(created_to),
                    limit=limit,
                    offset=offset,
                )
            )
            return _success(
                "Asset search completed.",
                ok_payload(
                    total=result.total,
                    limit=result.limit,
                    offset=result.offset,
                    items=[
                        asset_to_public_dict(item.asset)
                        for item in result.results
                    ],
                ),
            )
        except Exception as error:
            return _safe_error(error)

    @mcp.tool(
        name="rm_asset_download_link",
        description=(
            "Create a five-minute link for up to three downloads of the "
            "privacy-cleaned stored image."
        ),
        annotations=LINK_CREATION,
        structured_output=True,
    )
    def rm_asset_download_link(
        asset_id: str,
    ) -> Annotated[CallToolResult, McpToolOutput]:
        try:
            asset, _content = read_cleaned_image(runtime, str(asset_id))
            ticket, download_url = downloads.create(asset.asset_id)
            return _success(
                "A short-lived download link was created.",
                ok_payload(
                    asset_id=asset.asset_id,
                    download_url=download_url,
                    expires_at=ticket.expires_at,
                    max_successful_gets=ticket.remaining_gets,
                ),
            )
        except Exception as error:
            return _safe_error(error)

    @mcp.tool(
        name="rm_asset_view",
        description=(
            "Open an original Remember-Me MCP App viewer for one cleaned "
            "image, with a text fallback."
        ),
        annotations=READ_ONLY,
        meta=VIEWER_TOOL_META,
        structured_output=True,
    )
    def rm_asset_view(
        asset_id: str,
    ) -> Annotated[CallToolResult, McpToolOutput]:
        try:
            asset, content = read_cleaned_image(runtime, str(asset_id))
            public = asset_to_public_dict(asset)
            payload = ok_payload(asset=public)
            return _success(
                "The cleaned image is ready in the Remember-Me viewer. "
                "Clients without MCP Apps can call rm_asset_download_link.",
                payload,
                meta={
                    "remember_me": {
                        "asset": public,
                        "image": {
                            "mime_type": asset.mime_type,
                            "data": base64.b64encode(content).decode("ascii"),
                        },
                    }
                },
            )
        except Exception as error:
            return _safe_error(error)

    @mcp.tool(
        name="rm_asset_inspect",
        description=(
            "Return one verified privacy-cleaned PNG or JPEG as MCP "
            "ImageContent."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def rm_asset_inspect(
        asset_id: str,
    ) -> Annotated[CallToolResult, McpToolOutput]:
        try:
            asset, content = read_cleaned_image(runtime, str(asset_id))
            return _success(
                "A verified privacy-cleaned image is attached.",
                ok_payload(asset=asset_to_public_dict(asset)),
                extra_content=[
                    ImageContent(
                        type="image",
                        data=base64.b64encode(content).decode("ascii"),
                        mimeType=asset.mime_type,
                    )
                ],
            )
        except Exception as error:
            return _safe_error(error)
