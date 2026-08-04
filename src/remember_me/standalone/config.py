# SPDX-License-Identifier: CPAL-1.0
"""Immutable standalone configuration with secure defaults."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from .errors import ConfigurationError


ENV_PREFIX = "REMEMBER_ME_"
VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}
OBVIOUS_TOKENS = {"changeme", "token", "password", "example"}


def parse_bool(value, name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ConfigurationError("Invalid boolean value for {}.".format(name))


def is_loopback_host(host: str) -> bool:
    normalized = str(host).strip().casefold()
    if normalized == "localhost":
        return True
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validate_token(token: Optional[str]) -> Optional[str]:
    if token is None:
        return None
    if not isinstance(token, str):
        raise ConfigurationError("Bearer Token must be text.")
    if "\r" in token or "\n" in token:
        raise ConfigurationError("Bearer Token must not contain newlines.")
    normalized = token.strip()
    if len(normalized) < 32:
        raise ConfigurationError("Bearer Token must be at least 32 characters.")
    lowered = normalized.casefold()
    obvious_pattern = "(?:{})+".format(
        "|".join(sorted(OBVIOUS_TOKENS, key=len, reverse=True))
    )
    if lowered in OBVIOUS_TOKENS or re.fullmatch(obvious_pattern, lowered):
        raise ConfigurationError("Bearer Token uses a prohibited example value.")
    return normalized


@dataclass(frozen=True)
class StandaloneConfig:
    data_root: Path = field(
        default_factory=lambda: Path.home() / ".remember-me"
    )
    host: str = "127.0.0.1"
    port: int = 8787
    auth_token: Optional[str] = field(default=None, repr=False)
    auth_token_file: Optional[Path] = None
    allow_network: bool = False
    enable_docs: bool = False
    log_level: str = "INFO"
    public_base_url: Optional[str] = None
    resolved_auth_token: Optional[str] = field(init=False, repr=False)
    resolved_public_base_url: Optional[str] = field(init=False)

    def __post_init__(self):
        data_root = Path(self.data_root).expanduser()
        host = str(self.host).strip()
        if not host:
            raise ConfigurationError("Host must not be empty.")
        if isinstance(self.port, bool):
            raise ConfigurationError("Port must be an integer.")
        try:
            port = int(self.port)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("Port must be an integer.") from exc
        if not 1 <= port <= 65535:
            raise ConfigurationError("Port must be between 1 and 65535.")
        log_level = str(self.log_level).strip().upper()
        if log_level not in VALID_LOG_LEVELS:
            raise ConfigurationError("Invalid log level.")
        allow_network = parse_bool(self.allow_network, "allow_network")
        enable_docs = parse_bool(self.enable_docs, "enable_docs")
        public_base_url = self._normalize_public_base_url(
            self.public_base_url,
            host,
            port,
        )

        token = self.auth_token
        token_file_value = self.auth_token_file
        if isinstance(token, str) and not token.strip():
            token = None
        if (
            isinstance(token_file_value, str)
            and not token_file_value.strip()
        ):
            token_file_value = None
        if token is not None and token_file_value is not None:
            raise ConfigurationError(
                "Configure either auth_token or auth_token_file, not both."
            )
        token_file = None
        if token_file_value is not None:
            token_file = Path(token_file_value).expanduser()
            if token_file.is_symlink() or not token_file.is_file():
                raise ConfigurationError("Bearer Token file is unavailable.")
            try:
                token = token_file.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ConfigurationError(
                    "Bearer Token file is unavailable."
                ) from exc
        token = _validate_token(token)
        if not is_loopback_host(host) and (not allow_network or token is None):
            raise ConfigurationError(
                "Non-loopback binding requires allow_network and a valid "
                "Bearer Token."
            )

        object.__setattr__(self, "data_root", data_root)
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "port", port)
        object.__setattr__(self, "auth_token_file", token_file)
        object.__setattr__(self, "allow_network", allow_network)
        object.__setattr__(self, "enable_docs", enable_docs)
        object.__setattr__(self, "log_level", log_level)
        object.__setattr__(self, "resolved_auth_token", token)
        object.__setattr__(self, "public_base_url", public_base_url)
        object.__setattr__(self, "resolved_public_base_url", public_base_url)

    @staticmethod
    def _normalize_public_base_url(
        value,
        host: str,
        port: int,
    ) -> Optional[str]:
        if value is None or not str(value).strip():
            return (
                "http://127.0.0.1:{}".format(port)
                if is_loopback_host(host)
                else None
            )
        candidate = str(value).strip()
        parsed = urlsplit(candidate)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError("Public base URL is invalid.")
        if not is_loopback_host(host) and parsed.scheme != "https":
            raise ConfigurationError(
                "Non-loopback public base URL must use HTTPS."
            )
        path = parsed.path.rstrip("/")
        return urlunsplit(
            (parsed.scheme, parsed.netloc, path, "", "")
        )

    @classmethod
    def from_sources(
        cls,
        cli_values=None,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "StandaloneConfig":
        environment = os.environ if environ is None else environ
        values = {
            "data_root": environment.get(ENV_PREFIX + "DATA_ROOT"),
            "host": environment.get(ENV_PREFIX + "HOST"),
            "port": environment.get(ENV_PREFIX + "PORT"),
            "auth_token": environment.get(ENV_PREFIX + "AUTH_TOKEN"),
            "auth_token_file": environment.get(ENV_PREFIX + "AUTH_TOKEN_FILE"),
            "allow_network": environment.get(ENV_PREFIX + "ALLOW_NETWORK"),
            "enable_docs": environment.get(ENV_PREFIX + "ENABLE_DOCS"),
            "log_level": environment.get(ENV_PREFIX + "LOG_LEVEL"),
            "public_base_url": environment.get(
                ENV_PREFIX + "PUBLIC_BASE_URL"
            ),
        }
        allowed = {
            "data_root",
            "host",
            "port",
            "auth_token",
            "auth_token_file",
            "allow_network",
            "enable_docs",
            "log_level",
            "public_base_url",
        }
        overrides = {
            key: value
            for key, value in dict(cli_values or {}).items()
            if key in allowed and value is not None
        }
        values.update(overrides)
        return cls(**{key: value for key, value in values.items() if value is not None})
