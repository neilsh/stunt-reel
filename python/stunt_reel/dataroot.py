"""Locate the shared, read-only data root that every checkout borrows.

``corpus/``, the reference captures and ``target_bin/`` are gitignored, so each
checkout would otherwise need its own copy.  They live once per machine, outside
every checkout: ``<parent-of-primary>/<repo-name>.data`` unless ``STUNT_DATA_ROOT``
names another place.  ``mise run init`` links them in, and ``ensure_links`` links
them in again wherever the corpus is read, so a checkout made by any tool works on
first use rather than reading an empty placeholder.

The shared tool cache works the same way, and so does the Python environment: a
worktree's ``.venv`` is a junction at ``<cache>/venvs/<checkout>-<digest>``, because uv
can only hardlink an environment out of the cache when both sit on one volume, and
a checkout usually does not (ADR 0019).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

__all__ = [
    "CACHE_DIRNAME",
    "DATA_ENV",
    "ENV_DIRNAME",
    "ENV_MARKER",
    "LINK_TARGETS",
    "REPO_ROOT",
    "VENV_DIRNAME",
    "WRITE_ENV",
    "SharedDataError",
    "SharedWriteError",
    "cache_root",
    "create_link",
    "data_root",
    "discard_env",
    "ensure_cache_link",
    "ensure_links",
    "ensure_links_or_report",
    "ensure_venv_link",
    "env_root",
    "env_target",
    "is_link",
    "is_placeholder",
    "is_shared",
    "link_points_at",
    "orphan_envs",
    "primary_checkout",
    "remove_link",
    "require_shared_write",
    "sweep_orphan_envs",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ENV = "STUNT_DATA_ROOT"
WRITE_ENV = "STUNT_DATA_WRITE"
DATA_SUFFIX = ".data"
#: The writable tool cache every checkout of one primary checkout borrows.
CACHE_DIRNAME = ".cache"
#: The directory inside that cache holding one Python environment per checkout, the
#: marker file naming the checkout an environment serves, and the link that borrows
#: it.  The environment stays per checkout because uv installs this checkout's
#: project into it.
ENV_DIRNAME = "venvs"
ENV_MARKER = ".checkout"
VENV_DIRNAME = ".venv"

#: (directory inside the data root, path inside the checkout that borrows it).
#: The names may differ: the data root keeps the historical ``si_archive``
#: directory while the checkout calls it ``siarchive``, the collector's spelling.
LINK_TARGETS: tuple[tuple[str, str], ...] = (
    ("stisldem", "corpus/stisldem"),
    ("si_archive", "corpus/siarchive"),
    ("oracle", "corpus/oracle"),
    ("target_bin", "target_bin"),
    ("reference", "build/parity/reference"),
)

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class SharedWriteError(RuntimeError):
    """Raised when something would write the shared data root without opting in."""


class SharedDataError(RuntimeError):
    """Raised when a checkout cannot be linked to the shared data root."""


def primary_checkout() -> Path | None:
    """The checkout that owns ``.git``, or ``None`` outside a git checkout.

    A linked worktree carries a ``.git`` *file* naming its git directory, and that
    directory sits under ``<primary>/.git/worktrees/<name>``, so walking the parents
    until the ``.git`` directory gives the checkout the data root is named after.
    """
    dot_git = REPO_ROOT / ".git"
    if dot_git.is_dir():
        return REPO_ROOT
    if not dot_git.is_file():
        return None
    _, _, raw = dot_git.read_text(encoding="utf-8").strip().partition(":")
    if not raw.strip():
        return None
    for parent in Path(raw.strip()).resolve().parents:
        if parent.name == ".git":
            return parent.parent
    return None


@lru_cache(maxsize=1)
def data_root() -> Path:
    """The one directory holding the corpus, the reference captures and ``target_bin/``."""
    override = os.environ.get(DATA_ENV)
    if override:
        return Path(override).expanduser().resolve()
    primary = primary_checkout()
    if primary is None:
        return REPO_ROOT
    return primary.with_name(primary.name + DATA_SUFFIX)


def cache_root() -> Path:
    """The one writable tool-cache directory every checkout of this repository borrows."""
    primary = primary_checkout()
    return (primary if primary is not None else REPO_ROOT) / CACHE_DIRNAME


def ensure_cache_link() -> str:
    """Make this checkout's .cache resolve to the primary checkout's tool cache.

    A fresh worktree runs uv sync before mise run init, so a cache that
    directory collected is moved into the shared one before the link replaces
    it.  Returns the line init prints: "= .cache" when the link was already
    correct, "+ .cache -> <target>" when this call created it.
    """
    target = cache_root()
    target.mkdir(parents=True, exist_ok=True)
    (target / "tmp").mkdir(exist_ok=True)
    link = REPO_ROOT / CACHE_DIRNAME
    if link == target:
        return "= .cache"
    if is_link(link):
        if link_points_at(link, target):
            return "= .cache"
        remove_link(link)
    elif link.exists():
        if link.is_dir():
            _adopt_partial_cache(link, target)
            link.rmdir()
        else:
            link.unlink()
    create_link(link, target)
    return f"+ .cache -> {target}"


def _adopt_partial_cache(partial: Path, target: Path) -> None:
    """Move a not-yet-linked cache's entries into the shared cache; the shared copy wins."""
    for entry in partial.iterdir():
        destination = target / entry.name
        if destination.exists():
            _discard(entry)
            continue
        shutil.move(str(entry), str(destination))


def _discard(path: Path) -> None:
    """Remove one cache entry: a directory tree, a link, or a file."""
    if is_link(path) or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def env_root() -> Path:
    """The shared cache's directory of per-checkout Python environments."""
    return cache_root() / ENV_DIRNAME


def env_target(checkout: Path) -> Path:
    """Where *checkout*'s Python environment lives inside the shared cache."""
    digest = hashlib.blake2s(os.fsencode(str(checkout).lower()), digest_size=4).hexdigest()
    return env_root() / f"{checkout.name}-{digest}"


def ensure_venv_link() -> str | None:
    """Point this checkout's ``.venv`` at its environment inside the shared cache.

    A worktree usually sits on another volume from the primary checkout, so uv
    cannot hardlink its packages out of the shared cache: a per-checkout ``.venv``
    copies them instead -- 68 MiB, 3.1 s at every fresh ``mise run init``.  The
    environment stays per checkout, because uv installs this checkout's project into
    it, but it can live in the cache, with ``.venv`` a junction at
    ``<cache>/venvs/<checkout>-<digest>`` (ADR 0019).

    Returns the line ``init`` prints.  The primary checkout, whose ``.venv`` already
    sits beside the cache, and a checkout outside git, which owns no shared cache,
    return ``None``.
    """
    primary = primary_checkout()
    if primary is None or primary == REPO_ROOT:
        return None
    target = env_target(REPO_ROOT)
    target.mkdir(parents=True, exist_ok=True)
    marker = target / ENV_MARKER
    checkout = str(REPO_ROOT)
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != checkout:
        marker.write_text(checkout + "\n", encoding="utf-8")
    link = REPO_ROOT / VENV_DIRNAME
    discarded = False
    if is_link(link):
        if link_points_at(link, target):
            return "= .venv"
        remove_link(link)
    elif link.is_dir():
        # A directory here is the copy uv made before this link existed; its absolute
        # paths cannot be moved into the cache, so it is disposable, not adopted.
        shutil.rmtree(link)
        discarded = True
    elif link.exists():
        link.unlink()
        discarded = True
    create_link(link, target)
    suffix = " (per-checkout copy discarded)" if discarded else ""
    return f"+ .venv -> {target}{suffix}"


def discard_env(checkout: Path) -> bool:
    """Remove *checkout*'s environment from the shared cache; True when it went."""
    target = env_target(checkout)
    if is_link(target) or not target.exists():
        return False
    shutil.rmtree(target, ignore_errors=True)
    return not target.exists()


def orphan_envs() -> list[Path]:
    """Environments whose checkout is gone: reaped, or removed by another tool."""
    root = env_root()
    if not root.is_dir():
        return []
    orphans: list[Path] = []
    for child in sorted(root.iterdir()):
        if is_link(child) or not child.is_dir():
            continue
        try:
            checkout = Path((child / ENV_MARKER).read_text(encoding="utf-8").strip())
        except OSError:
            orphans.append(child)
            continue
        if not checkout.is_dir():
            orphans.append(child)
    return orphans


def sweep_orphan_envs() -> list[Path]:
    """Remove every orphaned environment; return the ones that went."""
    removed: list[Path] = []
    for target in orphan_envs():
        shutil.rmtree(target, ignore_errors=True)
        if not target.exists():
            removed.append(target)
    return removed


def is_shared(path: Path) -> bool:
    """True when *path* resolves inside the shared data root, rather than this checkout."""
    root = data_root()
    if root == REPO_ROOT:
        return False
    try:
        return path.resolve().is_relative_to(root)
    except OSError:
        return False


def require_shared_write(what: str) -> None:
    """Refuse a write into the shared root unless the session opted in."""
    if os.environ.get(WRITE_ENV) == "1":
        return
    raise SharedWriteError(
        f"{what} writes the shared data root ({data_root()}); set {WRITE_ENV}=1 to "
        "allow it, and only one session may capture at a time"
    )


def is_link(path: Path) -> bool:
    """True for symbolic links and Windows junctions, which ``is_symlink`` misses."""
    if path.is_symlink():
        return True
    try:
        # lstat, not stat: stat follows the reparse point and reports the target.
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def is_placeholder(path: Path) -> bool:
    """True when git kept the directory alive with a ``.gitkeep`` and no data."""
    return all(entry.name == ".gitkeep" for entry in path.iterdir())


def link_points_at(path: Path, target: Path) -> bool:
    """True when *path* is a link that resolves to *target*."""
    try:
        return Path(os.path.realpath(path)) == target
    except OSError:
        return False


def remove_link(path: Path) -> None:
    """Remove a symbolic link or junction, never the directory it points at."""
    if path.is_symlink():
        path.unlink()
    else:
        path.rmdir()


def create_link(link: Path, target: Path) -> None:
    """Point *link* at *target*, with a junction on Windows and a symlink elsewhere."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.symlink(target, link, target_is_directory=True)
        return
    # A junction needs neither elevation nor Developer Mode, unlike a symlink.
    command = [
        os.environ.get("COMSPEC", "cmd.exe"),
        "/c",
        "mklink",
        "/J",
        str(link),
        str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SharedDataError(f"cannot link {link} -> {target}: {detail}")


def ensure_links() -> list[str]:
    """Link the shared data root into this checkout, repairing what is missing.

    Called where the corpus is read rather than where the worktree is made, so a
    checkout from any tool works on first use: a directory holding nothing but a
    ``.gitkeep`` is a worktree whose ``mise run init`` never ran, and it is replaced
    by the link.  Returns the checkout-relative paths it repaired, so a caller can
    say what it did.  Refuses, rather than moving anything, when the checkout holds
    real data: that is ``mise run init -- --migrate``'s decision, not a read's.
    """
    root = data_root()
    if root == REPO_ROOT:
        return []
    if not root.is_dir():
        raise SharedDataError(
            f"no shared data root at {root}; run `mise run init -- --migrate` in the "
            f"primary checkout, or set {DATA_ENV}"
        )
    # Refuse before touching anything: a half-repaired checkout reads as a worktree
    # whose corpus is half present, which is worse than the empty placeholder.
    for _shared, relative in LINK_TARGETS:
        link = REPO_ROOT / relative
        if link.is_dir() and not is_link(link) and not is_placeholder(link):
            raise SharedDataError(
                f"{relative} holds data of its own; run `mise run init -- --migrate` "
                "to move it into the shared root"
            )
    repaired: list[str] = []
    for shared, relative in LINK_TARGETS:
        target = root / shared
        link = REPO_ROOT / relative
        if is_link(link) and link_points_at(link, target):
            if not target.exists():
                raise SharedDataError(f"{relative} links to a missing {target}")
            continue
        if is_link(link):
            remove_link(link)
        elif link.is_dir():
            for entry in link.iterdir():
                entry.unlink()
            link.rmdir()
        elif link.exists():
            link.unlink()
        target.mkdir(parents=True, exist_ok=True)
        create_link(link, target)
        repaired.append(relative)
    return repaired


def ensure_links_or_report(program: str) -> bool:
    """``ensure_links`` for a command's first lines: say what it did, or why it refused."""
    try:
        for relative in ensure_links():
            sys.stderr.write(f"{program}: linked {relative}\n")
    except SharedDataError as err:
        sys.stderr.write(f"{program}: {err}\n")
        return False
    return True
