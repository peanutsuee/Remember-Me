# SPDX-License-Identifier: CPAL-1.0
"""Original MCP App viewer resource for one cleaned Remember-Me image."""

from pathlib import Path


VIEWER_RESOURCE_URI = "ui://remember-me/asset-viewer.html"
VIEWER_MIME_TYPE = "text/html;profile=mcp-app"
VIEWER_TOOL_META = {
    "ui": {
        "resourceUri": VIEWER_RESOURCE_URI,
    }
}
VIEWER_RESOURCE_META = {
    "ui": {
        "csp": {
            "connectDomains": [],
            "resourceDomains": [],
            "frameDomains": [],
        },
        "prefersBorder": True,
    }
}


def load_viewer_html() -> str:
    return Path(__file__).with_name("asset-viewer.html").read_text(
        encoding="utf-8"
    )
