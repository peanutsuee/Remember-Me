# SPDX-License-Identifier: CPAL-1.0
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from packaging.version import Version

import PIL

from remember_me import metadata
from remember_me.imaging import (
    PILLOW_BASELINE_VERSION,
    PILLOW_VERSION_RANGE,
    SANITIZER_ID,
)
from remember_me.mcp.server import MCP_TOOL_NAMES


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_stage7f_package_and_pillow_contract():
    assert metadata.PROJECT_VERSION == "0.1.0"
    assert metadata.HTTP_API_VERSION == "v1alpha1"
    assert metadata.DASHBOARD_VERSION == "v1alpha1"
    assert metadata.MCP_API_VERSION == "v1alpha1"
    assert metadata.DATA_COMPATIBILITY_VERSION == "ombre-brain-assets-v1"
    assert PILLOW_VERSION_RANGE == "Pillow>=10.4,<13"
    assert PILLOW_BASELINE_VERSION == "10.4.0"
    assert SANITIZER_ID == "remember-me-pillow-v1"
    assert Version("10.4") <= Version(PIL.__version__) < Version("13")
    pyproject = _read("pyproject.toml")
    assert '"Pillow>=10.4,<13"' in pyproject
    assert '"mcp>=1.28.1,<1.29"' in pyproject


def test_stage7f_probe_executes_fixed_core_and_mcp_contracts():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "stage7f_compatibility_probe.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["same_version_deterministic"] is True
    assert payload["service"]["crud"] is True
    assert payload["service"]["deduplicated"] is True
    assert payload["mcp"]["names"] == list(MCP_TOOL_NAMES)
    assert payload["mcp"]["expected_sha256_absent"] is True
    assert set(payload["sanitizer"]) == {
        "png_metadata",
        "jpeg_exif",
        "jpeg_oriented",
        "png_transparent",
    }
    assert all(
        item["metadata_clean"]
        for item in payload["sanitizer"].values()
    )


def test_stage7f_documented_runtime_policy_and_no_protocol_drift():
    readme = _read("README.md")
    compatibility = _read("docs/data-compatibility.md")
    security = _read("docs/security.md")
    architecture = _read("docs/architecture.md")
    versioning = _read("docs/versioning.md")
    combined = "\n".join(
        (readme, compatibility, security, architecture, versioning)
    )
    for required in (
        "Pillow 10.4",
        "12.x",
        "Pillow 12.3.0",
        "pin",
        "ombre-brain-assets-v1",
    ):
        assert required in combined
    assert tuple(MCP_TOOL_NAMES) == (
        "rm_asset_upload_link",
        "rm_asset_upload_status",
        "rm_asset_get",
        "rm_asset_update_metadata",
        "rm_asset_reindex_embeddings",
        "rm_asset_search",
        "rm_asset_download_link",
        "rm_asset_view",
        "rm_asset_inspect",
    )
