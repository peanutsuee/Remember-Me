# SPDX-License-Identifier: CPAL-1.0
import io
import re
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image

from remember_me import metadata
from remember_me.standalone.app import DASHBOARD_CSP, create_app
from remember_me.standalone.config import StandaloneConfig


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = (
    ROOT / "src" / "remember_me" / "standalone" / "dashboard"
)
STATIC_FILES = ("styles.css", "app.js", "api.js", "ui.js")


def _read(name):
    return (DASHBOARD_ROOT / name).read_text(encoding="utf-8")


def _client(tmp_path, token=None):
    return TestClient(
        create_app(
            StandaloneConfig(
                data_root=tmp_path,
                auth_token=token,
            )
        )
    )


def _png():
    image = Image.new("RGB", (8, 6), "purple")
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


def test_dashboard_routes_and_static_content_types(tmp_path):
    client = _client(tmp_path, token="dashboard-" + ("x" * 32))
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/dashboard"

    for path in ["/dashboard", "/dashboard/"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["content-security-policy"] == DASHBOARD_CSP
        assert "Remember-Me" in response.text
        assert "originally created by Ting (peanutsuee)" in response.text
        assert "set-cookie" not in response.headers

    content_types = {
        "styles.css": "text/css",
        "app.js": "application/javascript",
        "api.js": "application/javascript",
        "ui.js": "application/javascript",
    }
    for name, content_type in content_types.items():
        response = client.get("/dashboard/static/" + name)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(content_type)
    blocked_html = client.get("/dashboard/static/index.html")
    assert blocked_html.status_code == 404
    assert blocked_html.json()["error"]["code"] == (
        "dashboard_resource_unavailable"
    )


def test_dashboard_security_headers_and_csp(tmp_path):
    response = _client(tmp_path).get(
        "/dashboard",
        headers={"Origin": "https://example.invalid"},
    )
    assert response.headers["content-security-policy"] == DASHBOARD_CSP
    csp = response.headers["content-security-policy"]
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert "http://" not in csp
    assert "https://" not in csp
    assert "*" not in csp
    for directive in [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' blob: data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ]:
        assert directive in csp
    assert response.headers["permissions-policy"] == (
        "camera=(), microphone=(), geolocation=()"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in response.headers
    assert "access-control-allow-origin" not in response.headers
    assert "set-cookie" not in response.headers


def test_dashboard_html_has_no_inline_script_or_style():
    html = _read("index.html")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert "<style" not in html.casefold()
    assert not re.search(r"\sstyle\s*=", html, flags=re.IGNORECASE)
    assert '<script type="module" src="/dashboard/static/app.js">' in html
    assert 'href="/dashboard/static/styles.css"' in html


def test_dashboard_static_resources_are_self_contained_and_private():
    combined = "\n".join(
        _read(name) for name in ("index.html", *STATIC_FILES)
    )
    assert "http://" not in combined
    assert "https://" not in combined
    for forbidden in [
        "localStorage",
        "document.cookie",
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "new Function",
        "credentials: \"include\"",
        "console.log",
        "expected_sha256",
        "source_sha256",
        "stored_sha256",
        "stored_relpath",
        "blob_key",
        "data_root",
    ]:
        assert forbidden not in combined
    assert not re.search(r"\beval\s*\(", combined)


def test_dashboard_api_client_contract():
    api = _read("api.js")
    app = _read("app.js")
    assert 'const API_ROOT = "/api/v1"' in api
    for route_fragment in [
        "/about",
        "/assets",
        "/content",
    ]:
        assert route_fragment in api
    assert "Authorization" in api
    assert "Bearer ${token}" in api
    assert "sessionStorage" in api
    assert "remember_me_session_token" in api
    assert 'credentials: "omit"' in api
    assert 'cache: "no-store"' in api
    assert "authenticated: false" in api
    assert "URL.createObjectURL" in app
    assert "URL.revokeObjectURL" in app
    assert "IntersectionObserver" in app
    assert "THUMBNAIL_CONCURRENCY = 4" in app
    assert "expected_bytes" in api
    assert "form.append(\"tag\"" in api
    assert "location.search" not in app
    assert "history." not in app


def test_dashboard_interaction_bindings():
    app = _read("app.js")
    ui = _read("ui.js")
    for binding in [
        'dom.searchInput.addEventListener("input"',
        'dom.previousButton.addEventListener("click"',
        'dom.nextButton.addEventListener("click"',
        'dom.uploadForm.addEventListener("submit", submitUpload)',
        'dom.metadataForm.addEventListener("submit", saveMetadata)',
        'dom.openDeleteButton.addEventListener("click"',
        'dom.confirmDeleteButton.addEventListener("click", confirmDelete)',
        'dom.aboutButton.addEventListener("click", showAbout)',
    ]:
        assert binding in app
    assert 'card.addEventListener("click", open)' in ui
    assert 'card.addEventListener("keydown"' in ui


def test_dashboard_accessibility_and_responsive_contracts():
    html = _read("index.html")
    css = _read("styles.css")
    assert '<html lang="en">' in html
    assert 'aria-live="polite"' in html
    assert 'aria-live="assertive"' in html
    assert 'aria-label="Close upload"' in html
    assert 'aria-label="Close details"' in html
    assert 'alt="Selected image preview"' in html
    assert 'alt="Selected archive image"' in html
    for input_id in [
        "search-input",
        "tags-filter",
        "mime-filter",
        "created-from",
        "created-to",
        "limit-select",
        "file-input",
        "upload-title-input",
        "upload-description",
        "upload-tags",
        "detail-title-input",
        "detail-description",
        "detail-tags",
        "token-input",
    ]:
        assert 'for="{}"'.format(input_id) in html
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "@media (max-width: 960px)" in css
    assert "@media (max-width: 720px)" in css
    assert "@media (max-width: 480px)" in css
    assert "min-width: 320px" in css
    mobile_css = css.split("@media (max-width: 480px)", 1)[1].split(
        "@media (prefers-reduced-motion: reduce)",
        1,
    )[0]
    assert "grid-template-columns: 1fr" in mobile_css
    assert ".asset-card" in mobile_css
    assert "grid-template-columns: 124px minmax(0, 1fr)" in mobile_css
    assert "height: 164px" in mobile_css
    assert ".card-image-wrap" in mobile_css
    assert "width: 124px" in mobile_css
    assert "height: 124px" in mobile_css
    assert "aspect-ratio: auto" in mobile_css
    assert ".card-image" in mobile_css
    assert "object-fit: cover" in mobile_css
    assert "object-position: center" in mobile_css
    assert "-webkit-line-clamp: 2" in mobile_css
    assert "max-height: 42px" in mobile_css
    assert ".card-meta span:nth-child(2)" in mobile_css
    desktop_css = css.split("@media (max-width: 480px)", 1)[0]
    assert (
        "grid-template-columns: repeat(auto-fill, "
        "minmax(min(250px, 100%), 1fr))"
    ) in desktop_css
    assert "aspect-ratio: 4 / 3" in desktop_css
    assert "text-overflow: ellipsis" in desktop_css
    assert "white-space: nowrap" in desktop_css
    assert "overflow: hidden" in mobile_css
    assert "minmax(0, 1fr)" in mobile_css


def test_dashboard_card_preview_state_contract():
    css = _read("styles.css")
    ui = _read("ui.js")
    assert "[hidden]" in css
    assert "display: none !important" in css
    assert 'addEventListener("load", handleLoad' in ui
    assert 'addEventListener("error", handleError' in ui
    assert 'removeEventListener("error", handleError)' in ui
    assert 'removeEventListener("load", handleLoad)' in ui
    assert "parts.imageError.hidden = true" in ui
    assert "parts.imageError.hidden = false" in ui
    assert 'parts.image.classList.add("loaded")' in ui
    assert 'parts.image.classList.remove("loaded")' in ui


def test_dashboard_identity_and_package_data():
    html = _read("index.html")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert metadata.PROJECT_VERSION == "0.1.0.dev7"
    assert metadata.DASHBOARD_VERSION == "v1alpha1"
    assert "Remember-Me" in html
    assert "originally created by Ting (peanutsuee)" in html
    for pattern in [
        "standalone/dashboard/*.html",
        "standalone/dashboard/*.css",
        "standalone/dashboard/*.js",
    ]:
        assert pattern in pyproject
    for name in ("index.html", *STATIC_FILES):
        assert (DASHBOARD_ROOT / name).is_file()
        assert "SPDX-License-Identifier: CPAL-1.0" in _read(name)


def test_dashboard_files_are_in_built_wheel(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".dashboard-preview",
            ".pytest_cache",
            "__pycache__",
            "build",
            "dist",
            "*.egg-info",
        ),
    )
    output = tmp_path / "dist"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(output),
        ],
        cwd=source,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheel = next(output.glob("*.whl"))
    expected = {
        "remember_me/mcp/asset-viewer.html",
        "remember_me/standalone/dashboard/index.html",
        "remember_me/standalone/dashboard/styles.css",
        "remember_me/standalone/dashboard/app.js",
        "remember_me/standalone/dashboard/api.js",
        "remember_me/standalone/dashboard/ui.js",
    }
    with ZipFile(wheel) as archive:
        assert expected <= set(archive.namelist())


def test_about_uses_canonical_dashboard_metadata(tmp_path):
    payload = _client(tmp_path).get("/api/v1/about").json()
    assert payload["project_name"] == metadata.PROJECT_NAME
    assert payload["project_version"] == metadata.PROJECT_VERSION
    assert payload["dashboard_version"] == metadata.DASHBOARD_VERSION
    assert payload["http_api_version"] == metadata.HTTP_API_VERSION
    assert payload["official_repository"] == metadata.OFFICIAL_REPOSITORY
    assert payload["attribution"] == metadata.ATTRIBUTION_LINE


def test_xss_metadata_remains_plain_api_text(tmp_path):
    client = _client(tmp_path)
    content = _png()
    title = '<script>alert("stage7d")</script>'
    description = '<img src=x onerror=alert(1)> & "quoted"'
    response = client.post(
        "/api/v1/assets",
        data={
            "expected_bytes": str(len(content)),
            "title": title,
            "description": description,
            "tag": ["<b>tag</b>", "safe\u2060text"],
        },
        files={"file": ("xss.png", content, "image/png")},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == title
    assert payload["description"] == description
    assert "<b>tag</b>" in payload["tags"]
    assert all(isinstance(value, str) for value in payload["tags"])
    assert "textContent" in _read("ui.js")
    assert "textContent" in _read("app.js")
