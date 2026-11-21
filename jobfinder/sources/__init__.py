from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Source

REGISTRY: dict[str, Source] = {}


def register(source: Source) -> Source:
    """Add a source instance to REGISTRY under its name."""
    REGISTRY[source.name] = source
    return source
