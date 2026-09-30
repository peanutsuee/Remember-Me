# SPDX-License-Identifier: CPAL-1.0
import ast
import importlib.metadata
from pathlib import Path

import fastapi
import httpx
import python_multipart
import pydantic
import starlette
import uvicorn

from remember_me import metadata


ROOT = Path(__file__).resolve().parents[1]
STANDALONE_FILES = (
    "src/remember_me/__main__.py",
    "src/remember_me/standalone/__init__.py",
    "src/remember_me/standalone/app.py",
    "src/remember_me/standalone/auth.py",
    "src/remember_me/standalone/cli.py",
    "src/remember_me/standalone/config.py",
    "src/remember_me/standalone/errors.py",
    "src/remember_me/standalone/middleware.py",
    "src/remember_me/standalone/schemas.py",
)
CORE_REWRITE_FILES = (
    "src/remember_me/imaging/pillow_sanitizer.py",
    "src/remember_me/storage/content_store.py",
    "src/remember_me/core/normalization.py",
    "src/remember_me/search/keyword.py",
    "src/remember_me/storage/sqlite_repository.py",
    "src/remember_me/core/service.py",
)


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_stage7c_versions_and_dependency_stack():
    assert metadata.PROJECT_VERSION == "0.1.0.dev8"
    assert metadata.HTTP_API_VERSION == "v1alpha1"
    assert metadata.HTTP_ROUTE_PREFIX == "/api/v1"
    assert fastapi.__version__ == "0.115.14"
    assert starlette.__version__ == "0.46.2"
    assert uvicorn.__version__ == "0.33.0"
    assert pydantic.__version__ == "2.12.5"
    assert httpx.__version__ == "0.28.1"
    assert python_multipart.__version__ == "0.0.32"
    assert importlib.metadata.version("mcp") == "1.28.1"


def test_standalone_files_are_independent_cpal_work():
    provenance = _read("docs/source-provenance.md")
    for relative_path in STANDALONE_FILES:
        assert "SPDX-License-Identifier: CPAL-1.0" in _read(relative_path)
        assert relative_path in provenance
    assert "does not use or copy Ombre-Brain `server.py`" in provenance
    assert "Original concept, product design" in provenance
    for relative_path in [
        "docs/standalone-host.md",
        "docs/http-api.md",
        "docs/security.md",
    ]:
        assert "SPDX-License-Identifier: CPAL-1.0" in _read(relative_path)


def test_independent_core_files_keep_cpal_identity():
    for relative_path in CORE_REWRITE_FILES:
        text = _read(relative_path)
        assert text.startswith("# SPDX-License-Identifier: CPAL-1.0\n")
        assert "SPDX-License-Identifier: MIT" not in text
        assert "Copyright (c) 2026 P0lar1zzZ" not in text


def test_core_does_not_import_standalone_or_web_dependencies():
    forbidden = {
        "fastapi",
        "starlette",
        "uvicorn",
        "pydantic",
        "remember_me.standalone",
    }
    for path in (ROOT / "src" / "remember_me" / "core").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        assert not {
            name
            for name in imports
            if any(name == item or name.startswith(item + ".") for item in forbidden)
        }


def test_readme_and_security_contracts():
    readme = _read("README.md")
    for phrase in [
        "`0.1.0.dev8`",
        "Standalone HTTP Host",
        "127.0.0.1",
        "REMEMBER_ME_ALLOW_NETWORK",
        "Bearer Token",
        "does not provide TLS",
        "Dashboard is available for local preview",
        "MCP address is `/mcp`",
        "Claude one-click attachment saving has not been implemented",
        "not deployable as a complete",
        "does not accept `expected_sha256`",
        "Allow network egress",
        "Additional allowed domains",
        "All domains",
        "Manual uploads through the Dashboard do not require Claude network access",
        "Ting (peanutsuee)",
        "Copyright (c) 2026 P0lar1zzZ",
    ]:
        assert phrase in readme
    security = _read("docs/security.md")
    for phrase in [
        "does not implement CSRF",
        "does not enable wildcard CORS",
        "11 MiB",
        "64 KiB",
        "does not provide TLS",
        "single-user",
        "does not implement accounts",
    ]:
        assert phrase in security


def test_standalone_dependencies_are_optional():
    pyproject = _read("pyproject.toml")
    assert "standalone = [" in pyproject
    assert '"fastapi>=' in pyproject
    assert '"uvicorn>=' in pyproject
    assert '"python-multipart>=' in pyproject
    core_section = pyproject.split("[project.optional-dependencies]", 1)[0]
    assert "fastapi" not in core_section.casefold()
