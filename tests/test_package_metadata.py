# SPDX-License-Identifier: CPAL-1.0
from pathlib import Path

import remember_me
from remember_me import metadata

try:
    import tomllib
except ImportError:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_package_import_and_version():
    assert remember_me.__version__ == "0.1.0"
    assert metadata.PROJECT_VERSION == "0.1.0"


def test_canonical_project_identity():
    assert metadata.PROJECT_NAME == "Remember-Me"
    assert metadata.ORIGINAL_CREATOR == "Ting"
    assert metadata.ORIGINAL_CREATOR_HANDLE == "peanutsuee"
    assert metadata.OFFICIAL_REPOSITORY == (
        "https://github.com/peanutsuee/Remember-Me"
    )
    assert metadata.ATTRIBUTION_LINE == (
        "Remember-Me \u2014 originally created by Ting (peanutsuee)"
    )


def test_pyproject_identity_matches_package():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.1.0"' in text
    assert 'name = "Ting (peanutsuee)"' in text
    assert metadata.OFFICIAL_REPOSITORY in text


def test_pyproject_tables_are_parseable_and_scoped():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["authors"] == [{"name": "Ting (peanutsuee)"}]
    assert project["optional-dependencies"]["test"]
    assert "authors" not in project["optional-dependencies"]


def test_release_asset_provenance_policy_is_consistent():
    for relative_path in (
        "README.md",
        "README.en.md",
        "CHANGELOG.md",
        "docs/versioning.md",
    ):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        for marker in (
            "GitHub Release",
            "remember_me-0.1.0.tar.gz",
            "SHA-256",
            "Source code",
            "PyPI",
        ):
            assert marker in text, (relative_path, marker)

    versioning = (ROOT / "docs/versioning.md").read_text(encoding="utf-8")
    assert "from the final release commit" in versioning
    assert "pins that exact Release asset URL and SHA-256" in versioning
    assert "without rebuilding RM" in versioning
