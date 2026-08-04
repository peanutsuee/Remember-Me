# SPDX-License-Identifier: CPAL-1.0
"""Search contracts and implementations."""

from .keyword import keyword_search
from .vectors import NullVectorProvider, VectorProvider

__all__ = ["NullVectorProvider", "VectorProvider", "keyword_search"]
