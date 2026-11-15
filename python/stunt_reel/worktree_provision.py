"""``init``: provision this checkout eagerly, then report old links and missing data.

``ensure`` with its full report, then ``uv sync``; ``--migrate`` moves old in-checkout data into the
data root (ADR 0036). Links an older ``init`` made are reported and left for ``reap`` to unlink
(ADR 0018), and a machine with no game files fails here, not at its first capture.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

from stunt_reel.dataroot import (
    CACHE_DIRNAME,
    DATA_ENV,
    LINK_TARGETS,
    REPO_ROOT,
    VENV_DIRNAME,
    SharedDataError,
    convert_layout,
    corpus_root,
    data_root,
    is_link,
    is_placeholder,
    require_corpus,
)
from stunt_reel.worktree_ensure import _ensure

if TYPE_CHECKING:
    from pathlib import Path


def _migrate(relative: str, target: Path) -> None:
    """Move an existing in-checkout directory into the data root, once."""
    link = REPO_ROOT / relative
    if is_link(link) or not link.is_dir() or is_placeholder(link):
        return
    if target.exists():
        print(f"  ! {relative}: both the checkout and {target} hold data; left alone")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(link), str(target))
    print(f"  > {relative} -> {target}")


def _uv_sync() -> int:
    """Run ``uv sync`` for this checkout into its own ``.venv`` (ADR 0036)."""
    uv = shutil.which("uv")
    if uv is None:
        print("  ! uv is not on PATH; run this through mise")
        return 1
    print("  uv sync --locked --all-groups")
    result = subprocess.run(  # noqa: S603
        [uv, "sync", "--locked", "--all-groups"],
        check=False,
    )
    if result.returncode != 0:
        print(f"  ! uv sync failed (exit {result.returncode})")
    return int(result.returncode)


#: The checkout paths the old layout linked (ADR 0008, ADR 0013, ADR 0019); init reports them.
_LEGACY_LINKS: tuple[str, ...] = (
    *(relative for _, relative in LINK_TARGETS),
    CACHE_DIRNAME,
    VENV_DIRNAME,
)


def _init(migrate: bool) -> int:
    """``ensure`` with its full report, then ``uv sync``; links nothing (ADR 0036).

    ``--migrate`` still moves an in-checkout corpus into the data root, which code reads
    directly now. Links an older ``init`` made are reported and left for ``reap``, and real
    data at one of their paths is named, because nothing reads it there any more. A machine
    with no game files fails here, not at its first capture.
    """
    root = data_root()
    source = DATA_ENV if DATA_ENV in os.environ else "derived"
    print(f"worktree   {REPO_ROOT}")
    print(f"data root  {root} ({source})")
    if migrate:
        if root != REPO_ROOT and root.is_dir():
            try:
                for line in convert_layout(root):
                    print(f"  > {line}")
            except SharedDataError as err:
                print(f"  ! {err}")
                return 1
        for shared, relative in LINK_TARGETS:
            _migrate(relative, root / shared)
    _ensure(report=True)
    code = _uv_sync()
    if code:
        return code
    for relative in _LEGACY_LINKS:
        if is_link(REPO_ROOT / relative):
            print(f"  ~ {relative} is a link from the old layout; reap unlinks it")
    for relative in _stranded_data():
        print(
            f"  ! {relative} holds data the data root does not read; run mise run init -- --migrate"
        )
    try:
        require_corpus()
    except SharedDataError as err:
        print(f"  ! {err}")
        return 1
    return 0


def _stranded_data() -> list[str]:
    """The old link paths that hold real data in this checkout, which no code reads now."""
    corpus = corpus_root()
    stranded: list[str] = []
    for _, relative in LINK_TARGETS:
        path = REPO_ROOT / relative
        if is_link(path) or not path.is_dir() or is_placeholder(path):
            continue
        # The primary checkout's own corpus is read when the data root has none.
        if path.resolve().is_relative_to(corpus.resolve()):
            continue
        stranded.append(relative)
    return stranded
