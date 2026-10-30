"""Temporary directories a sandboxed process can reopen.

tempfile.TemporaryDirectory creates its directory with mode 0o700.  Under DSH's
Windows sandbox such a directory cannot be listed, written or removed by the
process that created it, so tooling that shells out builds its scratch space with
the default mode instead.
"""

from __future__ import annotations

import secrets
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def scratch_dir(prefix: str) -> Iterator[Path]:
    """Yield a fresh scratch directory under the temp root, removed on exit."""
    base = Path(tempfile.gettempdir())
    for _ in range(100):
        path = base / f"{prefix}{secrets.token_hex(6)}"
        try:
            path.mkdir()
        except FileExistsError:
            continue
        break
    else:
        raise OSError(f"could not create a scratch directory for {prefix!r}")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
