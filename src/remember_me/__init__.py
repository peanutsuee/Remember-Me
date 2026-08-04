# SPDX-License-Identifier: CPAL-1.0
"""Remember-Me public package."""

from .metadata import (
    ATTRIBUTION_LINE,
    DASHBOARD_VERSION,
    DATA_COMPATIBILITY_VERSION,
    HTTP_API_VERSION,
    HTTP_ROUTE_PREFIX,
    MCP_API_VERSION,
    OFFICIAL_REPOSITORY,
    ORIGINAL_CREATOR,
    ORIGINAL_CREATOR_HANDLE,
    ORIGINAL_CREATOR_PHRASE,
    PROJECT_NAME,
    PROJECT_LICENSE,
    PROJECT_VERSION,
)
from .factory import LocalRuntime, create_local_runtime, create_local_service

__version__ = PROJECT_VERSION

__all__ = [
    "ATTRIBUTION_LINE",
    "DASHBOARD_VERSION",
    "DATA_COMPATIBILITY_VERSION",
    "HTTP_API_VERSION",
    "HTTP_ROUTE_PREFIX",
    "MCP_API_VERSION",
    "LocalRuntime",
    "OFFICIAL_REPOSITORY",
    "ORIGINAL_CREATOR",
    "ORIGINAL_CREATOR_HANDLE",
    "ORIGINAL_CREATOR_PHRASE",
    "PROJECT_NAME",
    "PROJECT_LICENSE",
    "PROJECT_VERSION",
    "create_local_runtime",
    "create_local_service",
    "__version__",
]
