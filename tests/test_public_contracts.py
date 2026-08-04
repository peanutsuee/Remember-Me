# SPDX-License-Identifier: CPAL-1.0
import inspect
from dataclasses import fields
from pathlib import Path

from remember_me.core.contracts import RememberMeCore
from remember_me.core.models import IngestImageRequest
from remember_me.transport.contracts import PublicUploadRequest, UploadReceiver


ROOT = Path(__file__).resolve().parents[1]


def test_public_core_operations_are_declared():
    expected = {
        "ingest_image",
        "get_asset",
        "update_metadata",
        "delete_asset",
        "search_assets",
        "resolve_asset",
        "begin_asset_verification",
        "list_asset_verification_page",
        "verify_asset_blob",
        "complete_asset_verification",
    }
    assert expected.issubset(set(RememberMeCore.__dict__))


def test_public_upload_requests_do_not_accept_client_hashes():
    assert {field.name for field in fields(PublicUploadRequest)} == {
        "expected_bytes",
        "filename",
        "mime_type",
    }
    assert "expected_sha256" not in {
        field.name for field in fields(IngestImageRequest)
    }
    assert "expected_sha256" not in inspect.signature(
        UploadReceiver.receive_upload
    ).parameters


def test_public_upload_documentation_rejects_client_hash_input():
    text = (ROOT / "docs" / "public-api-contract.md").read_text(encoding="utf-8")
    assert "does not accept `expected_sha256`" in text
    assert "must not" in text
    assert "Historical diagnostic probes" in text


def test_core_has_no_host_dependencies():
    forbidden = [
        "ombre brain",
        "ombre_brain",
        "fastmcp",
        "mcp",
        "mcp sdk",
        "starlette",
        "fastapi",
        "cookie",
        "csrf",
        "render",
    ]
    core_root = ROOT / "src" / "remember_me" / "core"
    source = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in sorted(core_root.glob("*.py"))
    )
    for term in forbidden:
        assert term not in source
