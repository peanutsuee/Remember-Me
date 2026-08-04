# SPDX-License-Identifier: CPAL-1.0
"""Safe MCP-facing schemas that never expose storage internals."""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict

from remember_me.core import AssetRecord


PRIVATE_FIELD_NAMES = {
    "source_sha256",
    "stored_sha256",
    "stored_relpath",
    "blob_key",
    "data_root",
    "db_path",
}


class McpToolOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool


def asset_to_public_dict(asset: AssetRecord) -> Dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        "title": asset.title,
        "description": asset.description,
        "tags": list(asset.tags),
        "original_filename": asset.original_filename,
        "mime_type": asset.mime_type,
        "kind": asset.kind,
        "decoded_bytes": asset.decoded_bytes,
        "stored_bytes": asset.stored_bytes,
        "width": asset.width,
        "height": asset.height,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
    }


def ok_payload(**values: Any) -> Dict[str, Any]:
    return {"ok": True, **values}


def error_payload(code: str, message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
