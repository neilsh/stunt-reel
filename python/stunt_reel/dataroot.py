"""Locate the shared data root that every checkout borrows.

The original game files (``corpus/``) and the captures are gitignored, so each
checkout would otherwise need its own copy.  They live once per machine, outside
every checkout: ``<parent-of-primary>/<repo-name>.data`` unless ``STUNT_DATA_ROOT``
names another place.  Nothing this project runs writes ``corpus/``, and a capture adds
a new directory under ``captures/`` and never changes one (ADR 0022).  ``mise run init`` links them in, and ``ensure_links`` links
them in again wherever the corpus is read, so a checkout made by any tool works on
first use rather than reading an empty placeholder.  ``ensure_links`` is the one
policy for those links: it returns one outcome per target, and its callers only
render them.

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
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from stunt_reel import parity_layout

__all__ = [
    "CACHE_DIRNAME",
    "DATA_ENV",
    "ENV_DIRNAME",
    "ENV_MARKER",
    "LEGACY_CAPTURE_ID",
    "LINK_TARGETS",
    "REPO_ROOT",
    "VENV_DIRNAME",
    "LinkOutcome",
    "LinkStatus",
    "SharedDataError",
    "cache_root",
    "convert_layout",
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
    "link_points_at",
    "orphan_envs",
    "primary_checkout",
    "remove_link",
    "shared_target",
    "sweep_orphan_envs",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ENV = "STUNT_DATA_ROOT"
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
#: Each corpus folder is its own link, because ``corpus/README.md`` and
#: ``corpus/siarchive.md`` are tracked and ``corpus/`` cannot itself be one.
LINK_TARGETS: tuple[tuple[str, str], ...] = (
    ("corpus/stisldem", "corpus/stisldem"),
    ("corpus/siarchive", "corpus/siarchive"),
    ("corpus/stuntisl", "corpus/stuntisl"),
    ("corpus/patches", "corpus/patches"),
    ("captures", parity_layout.capture_root().as_posix()),
)

#: The capture id the captures of the old data-root layout take when they are converted.
LEGACY_CAPTURE_ID = "legacy-2026-10-24"
#: Top-level names of the old layout (ADR 0008); ``reference`` held ``<film>/`` directly.
_OLD_NAMES = ("stisldem", "si_archive", "oracle", "target_bin", "reference")

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class SharedDataError(RuntimeError):
    """Raised when a checkout cannot be linked to the shared data root."""


#: What one checkout-relative link came to.  ``ok`` and ``repaired`` describe a link
#: that points at an existing shared target; ``created-empty`` says the target itself
#: was missing and was created empty first, which is a valid starting point for the
#: captures (ADR 0008); ``refused`` says this call left
#: the target alone and ``reason`` says why.
LinkStatus = Literal["ok", "repaired", "created-empty", "refused"]


@dataclass(frozen=True)
class LinkOutcome:
    """One ``LINK_TARGETS`` entry after :func:`ensure_links`, for a caller to render."""

    relative: str
    status: LinkStatus
    target: Path
    reason: str | None = None


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
    """The one directory holding the corpus and the captures."""
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


def ensure_cache_link() -> LinkOutcome:
    """Make this checkout's .cache resolve to the primary checkout's tool cache.

    A fresh worktree runs uv sync before mise run init, so a cache that
    directory collected is moved into the shared one before the link replaces
    it.  Returns the outcome init renders: ok when the link was already correct,
    repaired when this call made it.
    """
    target = cache_root()
    target.mkdir(parents=True, exist_ok=True)
    (target / "tmp").mkdir(exist_ok=True)
    link = REPO_ROOT / CACHE_DIRNAME
    if link == target:
        return LinkOutcome(CACHE_DIRNAME, "ok", target)
    if is_link(link):
        if link_points_at(link, target):
            return LinkOutcome(CACHE_DIRNAME, "ok", target)
        remove_link(link)
    elif link.exists():
        if link.is_dir():
            _adopt_partial_cache(link, target)
            link.rmdir()
        else:
            link.unlink()
    create_link(link, target)
    return LinkOutcome(CACHE_DIRNAME, "repaired", target)


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
        link.symlink_to(target, target_is_directory=True)
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


def shared_target(relative: str) -> Path:
    """The data-root directory a checkout-relative link borrows.

    The two names live only in :data:`LINK_TARGETS`, so a caller that needs the shared
    side of one link (``mise run clean`` restores the capture link) asks here instead of
    spelling it again.
    """
    for shared, subject in LINK_TARGETS:
        if subject == relative:
            return data_root() / shared
    raise KeyError(f"{relative} is not one of LINK_TARGETS")


def _holds_files(path: Path) -> bool:
    """True when *path* is a file or a directory tree containing one."""
    return path.is_file() or (path.is_dir() and any(item.is_file() for item in path.rglob("*")))


def convert_layout(root: Path) -> list[str]:
    """Convert an old-layout data root to the corpus/captures layout (ADR 0022); say what moved.

    ``stisldem`` and ``si_archive`` move under ``corpus/`` (the second as ``siarchive``),
    ``target_bin/StuntIsl`` becomes ``corpus/stuntisl`` and ``target_bin/patch`` becomes
    ``corpus/patches``.  The top-level ``target_bin/PLAYONE.EXE`` is dropped when it is
    byte-identical to ``StuntIsl``'s, and ``oracle`` is deleted: it was generated, not
    evidence.  ``reference/<film>`` becomes ``captures/<film>/`` + :data:`LEGACY_CAPTURE_ID`.
    A root already in the new layout is left alone; one holding both an old name and a new
    name with files in it is refused before anything moves, because merging them would guess which side is right.
    """
    old = [name for name in _OLD_NAMES if (root / name).exists()]
    if not old:
        return []
    # A read before the migration (capture-ref, parity) makes ensure_links create the new
    # directories empty; those are not data, so only a new name holding files is a conflict.
    new = [name for name in ("corpus", "captures") if _holds_files(root / name)]
    if new:
        raise SharedDataError(
            f"{root} holds both old names ({', '.join(old)}) and new ones ({', '.join(new)}); "
            "merge them by hand"
        )
    for name in ("corpus", "captures"):
        if (root / name).is_dir():
            shutil.rmtree(root / name)
    moves: list[tuple[Path, Path]] = []
    for name, destination in (("stisldem", "stisldem"), ("si_archive", "siarchive")):
        if (root / name).exists():
            moves.append((root / name, root / "corpus" / destination))
    for name, destination in (("StuntIsl", "stuntisl"), ("patch", "patches")):
        if (root / "target_bin" / name).exists():
            moves.append((root / "target_bin" / name, root / "corpus" / destination))
    moves.extend(
        (film, root / "captures" / film.name / LEGACY_CAPTURE_ID)
        for film in sorted(entry for entry in (root / "reference").glob("*") if entry.is_dir())
    )
    moved: list[str] = []
    for source, target in moves:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved.append(
            f"{source.relative_to(root).as_posix()} -> {target.relative_to(root).as_posix()}"
        )
    duplicate = root / "target_bin" / "PLAYONE.EXE"
    kept = root / "corpus" / "stuntisl" / "PLAYONE.EXE"
    if duplicate.is_file() and kept.is_file() and duplicate.read_bytes() == kept.read_bytes():
        duplicate.unlink()
        moved.append("target_bin/PLAYONE.EXE dropped (a copy of corpus/stuntisl/PLAYONE.EXE)")
    generated = root / "oracle" / "intro_trajectory.json"
    if generated.is_file():
        generated.unlink()
        moved.append("oracle/intro_trajectory.json removed (a synthetic build output now)")
    for name in ("target_bin", "reference", "oracle"):
        directory = root / name
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
        elif directory.exists():
            moved.append(f"{name} still holds files this conversion does not know; left alone")
    return moved


def ensure_links() -> list[LinkOutcome]:
    """Link the shared data root into this checkout; this is the one link policy.

    Called where the corpus is read rather than where the worktree is made, so a
    checkout from any tool works on first use: a directory holding nothing but a
    ``.gitkeep`` is a worktree whose ``mise run init`` never ran, and it is replaced
    by the link.  A shared directory that does not exist yet is created empty first,
    because the captures are populated later (ADR 0008).

    Returns one outcome per :data:`LINK_TARGETS` entry, which is all a caller needs to
    render what happened: a target already in place is ``ok``, not absent from the list.
    The walk is two passes, and the first refuses before anything is touched when the
    checkout holds real data of its own.  Moving that data is
    ``mise run init -- --migrate``'s decision, not a read's, and a half-repaired checkout
    reads as a worktree whose corpus is half present, which is worse than the empty
    placeholder: a refused run returns only the refused outcomes and touched nothing.
    """
    root = data_root()
    if root == REPO_ROOT:
        return []
    if not root.is_dir():
        raise SharedDataError(
            f"no shared data root at {root}; run `mise run init -- --migrate` in the "
            f"primary checkout, or set {DATA_ENV}"
        )
    refused: list[LinkOutcome] = []
    for shared, relative in LINK_TARGETS:
        link = REPO_ROOT / relative
        if not link.is_dir() or is_link(link) or is_placeholder(link):
            continue
        refused.append(
            LinkOutcome(
                relative=relative,
                status="refused",
                target=root / shared,
                reason=(
                    f"{relative} holds data of its own; run `mise run init -- --migrate` "
                    "to move it into the shared root"
                ),
            )
        )
    if refused:
        return refused
    outcomes: list[LinkOutcome] = []
    for shared, relative in LINK_TARGETS:
        target = root / shared
        link = REPO_ROOT / relative
        created_empty = not target.exists()
        if created_empty:
            target.mkdir(parents=True, exist_ok=True)
        if is_link(link) and link_points_at(link, target):
            outcomes.append(
                LinkOutcome(relative, "created-empty" if created_empty else "ok", target)
            )
            continue
        if is_link(link):
            remove_link(link)
        elif link.is_dir():
            for entry in link.iterdir():
                entry.unlink()
            link.rmdir()
        elif link.exists():
            link.unlink()
        create_link(link, target)
        outcomes.append(
            LinkOutcome(relative, "created-empty" if created_empty else "repaired", target)
        )
    return outcomes


def ensure_links_or_report(program: str) -> bool:
    """``ensure_links`` for a command's first lines: say what it did, or why it refused."""
    try:
        outcomes = ensure_links()
    except SharedDataError as err:
        sys.stderr.write(f"{program}: {err}\n")
        return False
    refused = [outcome for outcome in outcomes if outcome.status == "refused"]
    for outcome in refused:
        sys.stderr.write(f"{program}: {outcome.reason or outcome.relative}\n")
    if refused:
        return False
    for outcome in outcomes:
        if outcome.status != "ok":
            sys.stderr.write(f"{program}: linked {outcome.relative}\n")
    return True
