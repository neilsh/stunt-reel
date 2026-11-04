"""The SHA-256 identity a film, an archive or a game file is pinned by."""

from __future__ import annotations

import hashlib
lazy from pathlib import Path

__all__ = ["file_sha256"]


def file_sha256(path: Path) -> str:
    """The lowercase hex SHA-256 of *path*'s bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
