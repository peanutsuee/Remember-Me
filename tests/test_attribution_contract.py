# SPDX-License-Identifier: CPAL-1.0
from pathlib import Path
import re

import yaml

from remember_me import metadata


ROOT = Path(__file__).resolve().parents[1]
IGNORED_REPOSITORY_PARTS = {
    ".pytest_cache",
    ".stage7e-venv",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "venv",
}


def _is_ignored_repository_path(path: Path) -> bool:
    return bool(IGNORED_REPOSITORY_PARTS.intersection(path.parts)) or any(
        part.endswith(".egg-info") for part in path.parts
    )


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_required_identity_files_exist():
    for name in [
        "LICENSE",
        "NOTICE",
        "ORIGIN.md",
        "AUTHORS.md",
        "CITATION.cff",
        "TRADEMARKS.md",
        "CONTRIBUTING.md",
    ]:
        assert (ROOT / name).is_file()


def test_citation_is_parseable_and_consistent():
    citation = yaml.safe_load(_read("CITATION.cff"))
    assert citation["title"] == metadata.PROJECT_NAME
    assert citation["version"] == metadata.PROJECT_VERSION
    assert citation["repository-code"] == metadata.OFFICIAL_REPOSITORY
    assert citation["authors"][0]["family-names"] == metadata.ORIGINAL_CREATOR
    assert citation["authors"][0]["alias"] == metadata.ORIGINAL_CREATOR_HANDLE


def test_identity_is_consistent_across_public_files():
    for name in ["README.md", "NOTICE", "ORIGIN.md"]:
        text = _read(name)
        assert "Ting (peanutsuee)" in text
    assert metadata.OFFICIAL_REPOSITORY in _read("README.md")
    assert metadata.OFFICIAL_REPOSITORY in _read("NOTICE")
    assert metadata.ATTRIBUTION_LINE in _read("README.md")


def test_readme_stage_and_claude_network_disclosures():
    readme = _read("README.md")
    for phrase in [
        "Allow network egress",
        "Additional allowed domains",
        "All domains",
        "Manual uploads through the Dashboard do not require Claude network access",
        "not deployable",
    ]:
        assert phrase in readme


def test_upstream_attribution_is_not_reassigned():
    for name in ["README.md", "NOTICE", "AUTHORS.md", "docs/licensing-and-origin.md"]:
        text = _read(name)
        assert "Copyright (c) 2026 P0lar1zzZ" in text
        assert "MIT" in text


def test_cpal_license_and_exhibits_are_present():
    license_text = _read("LICENSE")
    assert license_text.startswith("Common Public Attribution License Version 1.0")
    assert "EXHIBIT A." in license_text
    assert "EXHIBIT B." in license_text
    assert "Copyright © 2026 Ting (peanutsuee)" in license_text
    assert "Remember-Me was originally created by Ting." in license_text
    assert "Display of Attribution Information is required" in license_text


def test_repository_contains_no_asset_or_database_payloads():
    forbidden_suffixes = {
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
    files = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and not _is_ignored_repository_path(path)
    ]
    assert not [path for path in files if path.suffix.lower() in forbidden_suffixes]
    assert max(path.stat().st_size for path in files) < 100_000


def test_repository_text_has_no_credentials_or_private_absolute_paths():
    text_files = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and not _is_ignored_repository_path(path)
        and path.suffix.lower()
        in {".cff", ".md", ".py", ".toml", ""}
    ]
    contents = []
    allowed_project_path = "D:" + r"\Codex\projects\Remember-Me"
    for path in text_files:
        text = path.read_text(encoding="utf-8")
        if path.name == "README.md" or path.name == "dashboard.md":
            text = text.replace(allowed_project_path, "<PROJECT_PATH>")
        contents.append(text)
    combined = "\n".join(contents)
    secret_patterns = [
        r"gh[opurs]_[A-Za-z0-9_]{20,}",
        r"sk-[A-Za-z0-9]{20,}",
        r"(?i)api[_-]?key\s*[:=]\s*['\"][^'\"]+",
        r"(?i)bearer\s+[A-Za-z0-9._-]{20,}",
        r"(?i)cookie\s*[:=]\s*['\"][^'\"]+",
        r"(?i)[A-Z]:\\Users\\",
        r"(?i)[A-Z]:\\Codex\\projects\\",
    ]
    for pattern in secret_patterns:
        assert re.search(pattern, combined) is None
