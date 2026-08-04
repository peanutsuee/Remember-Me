# SPDX-License-Identifier: CPAL-1.0
"""Standalone configuration and request boundary errors."""


class StandaloneError(Exception):
    """Base error for expected standalone host failures."""


class ConfigurationError(StandaloneError):
    """The standalone host configuration is unsafe or invalid."""


class RequestBodyTooLarge(StandaloneError):
    """The request body exceeded the route-specific limit."""
