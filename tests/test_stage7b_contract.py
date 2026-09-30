# SPDX-License-Identifier: CPAL-1.0
import inspect
import sqlite3
from dataclasses import fields
from pathlib import Path

import PIL
from packaging.version import Version

import remember_me
from remember_me.core import RememberMeService
from remember_me.core.models import IngestImageRequest
from remember_me.imaging import (
    PILLOW_BASELINE_VERSION,
    PILLOW_VERSION_RANGE,
    SANITIZER_ID,
)
from remember_me.transport.contracts import PublicUploadRequest


ROOT = Path(__file__).resolve().parents[1]
IGNORED_REPOSITORY_PARTS = {
    ".pytest_cache",
    ".stage7e-smoke",
    ".stage7e-venv",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "venv",
}
PUBLIC_TEXT_DIRECTORIES = (
    ".github",
    "docs",
    "LICENSES",
    "src",
    "tests",
)
PUBLIC_TEXT_SUFFIXES = {
    ".cff",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".tsv",
    ".txt",
}
CORE_REWRITE_FILES = (
    "src/remember_me/imaging/pillow_sanitizer.py",
    "src/remember_me/storage/content_store.py",
    "src/remember_me/core/normalization.py",
    "src/remember_me/search/keyword.py",
    "src/remember_me/storage/sqlite_repository.py",
    "src/remember_me/core/service.py",
)
PROVENANCE_DOCUMENT_EXPECTATIONS = (
    ("AUTHORS.md", "six independently"),
    ("NOTICE", "independently reimplemented"),
    ("ORIGIN.md", "reimplemented CPAL-1.0 versions"),
    ("README.en.md", "independently reimplemented"),
    ("README.md", "Common Public Attribution License Version 1.0"),
    ("docs/licensing-and-origin.md", "independently reimplemented"),
    ("docs/source-provenance.md", "independently reimplemented"),
    ("docs/versioning.md", "Historical private integration labels"),
)


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _public_text_files():
    for path in ROOT.iterdir():
        if path.is_file() and path.suffix.lower() in PUBLIC_TEXT_SUFFIXES:
            yield path
    for relative_directory in PUBLIC_TEXT_DIRECTORIES:
        directory = ROOT / relative_directory
        for path in directory.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in PUBLIC_TEXT_SUFFIXES
                and not IGNORED_REPOSITORY_PARTS.intersection(path.parts)
                and not any(part.endswith(".egg-info") for part in path.parts)
            ):
                yield path


def test_stage7b_version_and_readme_status():
    assert remember_me.__version__ == "0.1.0.dev8"
    readme = _read("README.md")
    assert "`0.1.0.dev8`" in readme
    assert "privacy-safe image core" in readme
    assert "not deployable as a complete" in readme
    for name in ["Dashboard", "HTTP", "MCP", "Standalone Host"]:
        assert name in readme
    assert "Ting (peanutsuee)" in readme
    assert "Copyright (c) 2026 P0lar1zzZ" in readme


def test_public_upload_contract_still_has_no_client_hash():
    assert "expected_sha256" not in {
        field.name for field in fields(IngestImageRequest)
    }
    assert "expected_sha256" not in {
        field.name for field in fields(PublicUploadRequest)
    }
    assert "expected_sha256" not in inspect.signature(
        RememberMeService.ingest_image
    ).parameters


def test_pillow_output_contract_is_explicit():
    assert SANITIZER_ID == "remember-me-pillow-v1"
    assert PILLOW_VERSION_RANGE == "Pillow>=10.4,<13"
    assert PILLOW_BASELINE_VERSION == "10.4.0"
    assert Version("10.4") <= Version(PIL.__version__) < Version("13")


def test_independent_core_rewrite_provenance():
    provenance = _read("docs/source-provenance.md")
    legacy_identity = "ALL" + "FORTING"
    legacy_repository = legacy_identity + "/Ombre-" + "Brain"
    legacy_source_shas = (
        "0e5021307e2e" + "bacbcb23a3d01d6d85b7f9138bcd",
        "e3b5e0a409a2" + "9f104cdc34c4efcaacdb7cdbe9f0",
    )
    legacy_tag = "remember-me-integrated-" + "v1.0.0"
    prohibited_repository_markers = (
        legacy_identity,
        legacy_repository,
        *legacy_source_shas,
        legacy_tag,
        "rm-" + "stage7b-",
        "rm-ob-" + "provenance-audit",
    )
    prohibited_provenance_markers = (
        *prohibited_repository_markers,
        "fork-" + "only",
        "adapted " + "from",
        "derived " + "from",
        "D:" + "\\Codex",
    )
    for relative_path in CORE_REWRITE_FILES:
        text = _read(relative_path)
        assert text.splitlines()[0] == "# SPDX-License-Identifier: CPAL-1.0"
        assert "SPDX-License-Identifier: MIT" not in text
        assert "Copyright (c) 2026 P0lar1zzZ" not in text
        for marker in prohibited_provenance_markers:
            assert marker not in text
        assert relative_path in provenance

    assert "independently reimplemented" in provenance
    assert "`SPDX-License-Identifier: CPAL-1.0`" in provenance
    assert "do not by themselves" in provenance
    assert "determine copyright ownership" in provenance

    mit_license_path = ROOT / "LICENSES" / "MIT-Ombre-Brain.txt"
    assert mit_license_path.is_file()
    mit_license = _read("LICENSES/MIT-Ombre-Brain.txt")
    assert mit_license.startswith("MIT License\n")
    assert "Copyright (c) 2026 P0lar1zzZ" in mit_license

    root_license = _read("LICENSE")
    package_metadata = _read("pyproject.toml")
    notice = _read("NOTICE")
    assert root_license.startswith(
        "Common Public Attribution License Version 1.0 (CPAL)\n"
    )
    assert 'license = { file = "LICENSE" }' in package_metadata
    assert 'license-files = ["LICENSE", "LICENSES/*.txt", "NOTICE"]' in (
        package_metadata
    )
    assert "independently reimplemented" in notice
    assert "SPDX-License-Identifier: CPAL-1.0" not in mit_license
    assert "applicable upstream MIT rights and attribution" in notice
    assert "Copyright (c) 2026 P0lar1zzZ" in notice
    assert legacy_identity not in notice

    for relative_path, expected_text in PROVENANCE_DOCUMENT_EXPECTATIONS:
        text = _read(relative_path)
        assert expected_text in text
        assert legacy_identity not in text
        if "Copyright (c) 2026 P0lar1zzZ" in text:
            assert "MIT" in text

    provenance_text = "\n".join(
        _read(relative_path)
        for relative_path in (
            *CORE_REWRITE_FILES,
            *(path for path, _ in PROVENANCE_DOCUMENT_EXPECTATIONS),
            "LICENSE",
            "LICENSES/MIT-Ombre-Brain.txt",
            "pyproject.toml",
        )
    )
    for marker in prohibited_provenance_markers:
        assert marker not in provenance_text

    repository_text = "\n".join(
        _read(path.relative_to(ROOT)) for path in _public_text_files()
    )
    for marker in prohibited_repository_markers:
        assert marker not in repository_text
    for guarantee in [
        "legally proven " + "independent",
        "no copyright risk " + "exists",
        "legal " + "guarantee",
        "lawyer-" + "approved",
    ]:
        assert guarantee not in repository_text.casefold()


def test_independent_files_keep_cpal_identity():
    for relative_path in [
        "src/remember_me/core/clock.py",
        "src/remember_me/factory.py",
        "tests/test_stage7b_contract.py",
    ]:
        assert "SPDX-License-Identifier: CPAL-1.0" in _read(relative_path)
    assert "Original concept, product design" in _read(
        "docs/source-provenance.md"
    )


def test_no_real_asset_database_is_part_of_the_repository():
    forbidden = {
        ".bmp",
        ".db",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".sqlite",
        ".sqlite3",
        ".webp",
    }
    ignored = {
        ".git",
        ".stage7e-venv",
        ".venv",
        "__pycache__",
        ".pytest_cache",
    }
    files = [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not ignored.intersection(path.parts)
    ]
    assert not [path for path in files if path.suffix.lower() in forbidden]


def test_compatibility_documents_keep_single_writer_and_no_rehash_rules():
    compatibility = _read("docs/data-compatibility.md")
    assert "must not write the same SQLite database" in compatibility
    assert "do not enable WAL by default" in compatibility
    assert "recompute existing hashes" in compatibility
    assert "asset_embeddings" in compatibility
