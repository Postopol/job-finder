from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Source

REGISTRY: dict[str, Source] = {}


def register(source: Source) -> Source:
    """Add a source instance to REGISTRY under its name."""
    REGISTRY[source.name] = source
    return source


# Importing the modules registers the sources (kept at the bottom: they import `register`).
from . import himalayas, hn, jobicy, remotefirst, remoteok, workingnomads, wwr  # noqa: E402,F401
