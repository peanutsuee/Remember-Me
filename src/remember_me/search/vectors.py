# SPDX-License-Identifier: CPAL-1.0
"""Optional vector provider contract."""

from __future__ import annotations

from typing import Protocol


class VectorProvider(Protocol):
    @property
    def enabled(self) -> bool:
        ...

    @property
    def model_id(self) -> str:
        ...

    async def embed(self, text: str) -> list[float]:
        ...


class NullVectorProvider:
    """A stable, network-free provider for keyword-only operation."""

    @property
    def enabled(self) -> bool:
        return False

    @property
    def model_id(self) -> str:
        return "remember-me/null-vector-provider-v1"

    async def embed(self, text: str) -> list[float]:
        return []
