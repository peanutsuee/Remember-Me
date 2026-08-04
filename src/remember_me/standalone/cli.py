# SPDX-License-Identifier: CPAL-1.0
"""Command-line interface for the optional standalone host."""

from __future__ import annotations

import argparse
import logging
import sys

from remember_me.metadata import (
    ATTRIBUTION_LINE,
    DATA_COMPATIBILITY_VERSION,
    HTTP_API_VERSION,
    MCP_API_VERSION,
    OFFICIAL_REPOSITORY,
    ORIGINAL_CREATOR_HANDLE,
    PROJECT_LICENSE,
    PROJECT_NAME,
    PROJECT_VERSION,
)

from .config import StandaloneConfig
from .errors import ConfigurationError


def version_text() -> str:
    return "{} {} - originally created by Ting ({})".format(
        PROJECT_NAME,
        PROJECT_VERSION,
        ORIGINAL_CREATOR_HANDLE,
    )


def about_text() -> str:
    return "\n".join(
        [
            "{} {}".format(PROJECT_NAME, PROJECT_VERSION),
            ATTRIBUTION_LINE,
            "Official repository: {}".format(OFFICIAL_REPOSITORY),
            "License: {}".format(PROJECT_LICENSE),
            "HTTP API: {}".format(HTTP_API_VERSION),
            "MCP API: {}".format(MCP_API_VERSION),
            "Data compatibility: {}".format(DATA_COMPATIBILITY_VERSION),
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="remember-me", allow_abbrev=False)
    parser.add_argument(
        "--version",
        action="version",
        version=version_text(),
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "about",
        help="show project identity and versions",
        allow_abbrev=False,
    )
    serve = subparsers.add_parser(
        "serve",
        help="run the standalone HTTP host",
        allow_abbrev=False,
    )
    serve.add_argument("--data-root")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--auth-token-file")
    serve.add_argument("--allow-network", action="store_true", default=None)
    serve.add_argument("--enable-docs", action="store_true", default=None)
    serve.add_argument("--log-level")
    serve.add_argument("--public-base-url")
    return parser


def _serve(args) -> int:
    try:
        config = StandaloneConfig.from_sources(vars(args))
    except ConfigurationError as exc:
        print("Configuration error: {}".format(exc), file=sys.stderr)
        return 2
    try:
        import uvicorn

        from .app import create_app
    except ImportError:
        print(
            'Standalone dependencies are missing. Install "remember-me'
            '[standalone]".',
            file=sys.stderr,
        )
        return 2

    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(levelname)s %(name)s %(message)s",
    )
    for noisy_logger in (
        "httpcore",
        "httpx",
        "multipart",
        "python_multipart",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    logging.getLogger(__name__).info(
        "%s %s host=%s port=%s auth=%s network=%s docs=%s",
        PROJECT_NAME,
        PROJECT_VERSION,
        config.host,
        config.port,
        config.resolved_auth_token is not None,
        config.allow_network,
        config.enable_docs,
    )
    app = create_app(config)
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        access_log=False,
        proxy_headers=False,
        server_header=False,
        date_header=False,
    )
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "about":
        print(about_text())
        return 0
    if args.command == "serve":
        return _serve(args)
    parser.print_help()
    return 0
