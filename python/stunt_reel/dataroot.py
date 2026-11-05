"""Locate the shared data root that every checkout borrows.

The original game files (``corpus/``) and the captures are gitignored, so each
checkout would otherwise need its own copy.  They live once per machine, outside
every checkout: ``<parent-of-primary>/<repo-name>.data`` unless ``STUNT_DATA_ROOT``
names another place.  Nothing this project runs writes ``corpus/`` (ADR 0022), and a new
capture of a film replaces its old one by swap (ADR 0028).  Code reads both through
:func:`data_root`, :func:`corpus_root` and :func:`resolve_data_path`, so a checkout made
by any tool works on first use with no link in it (ADR 0033).

Older worktrees still hold the junctions an earlier ``mise run init`` made, including a
``.venv`` parked at ``<cache>/venvs/<checkout>-<digest>`` (ADR 0019, superseded).
``LINK_TARGETS`` names them for ``init``'s report and ``--migrate``; ``reap`` finds and unlinks
any reparse point under a checkout (ADR 0018), and the environment sweep clears the parked
environments.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from stunt_reel import parity_layout

__all__ = [
    "CACHE_DIRNAME",
    "DATA_ENV",
    "ENV_DIRNAME",
    "ENV_MARKER",
    "LINK_TARGETS",
    "REPO_ROOT",
    "VENV_DIRNAME",
    "SharedDataError",
    "cache_root",
    "convert_layout",
    "corpus_of",
    "corpus_root",
    "create_link",
    "data_path_arg",
    "data_root",
    "discard_env",
    "env_marker",
    "env_root",
    "env_target",
    "is_link",
    "is_placeholder",
    "link_points_at",
    "orphan_envs",
    "primary_checkout",
    "remove_link",
    "require_corpus",
    "resolve_data_path",
    "sweep_orphan_envs",
    "use_data_root",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ENV = "STUNT_DATA_ROOT"
DATA_SUFFIX = ".data"
#: The writable tool cache every checkout of one primary checkout borrows.
CACHE_DIRNAME = ".cache"
#: The directory inside that cache holding one Python environment per checkout, the
#: marker file naming the checkout an environment serves, and the link that borrows
#: it.  The environment stays per checkout because uv installs this checkout's
#: project into it.  The marker sits beside the environment, as
#: ``<environment>.checkout``, because uv empties the environment directory whenever
#: it replaces the interpreter.
ENV_DIRNAME = "venvs"
#: Suffix of the marker beside an environment (``<environment>.checkout``), and the
#: name of the legacy marker that older environments still carry inside them.
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
    ("captures", parity_layout.LEGACY_CAPTURE_LINK.as_posix()),
)

#: Top-level names of the old layout (ADR 0008); ``reference`` held ``<film>/`` directly.
_OLD_NAMES = ("stisldem", "si_archive", "oracle", "target_bin", "reference")

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class SharedDataError(RuntimeError):
    """Raised when the shared data root, or something in it, is missing or cannot be used."""


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


def use_data_root(path: Path) -> Path:
    """Make *path* this process's data root, and its children's, as ``STUNT_DATA_ROOT`` would.

    A ``--data-root`` flag calls this, so code that asks :func:`data_root` and the scripts a
    run starts agree with the root the flag named.  Returns the resolved root.
    """
    root = path.expanduser().resolve()
    os.environ[DATA_ENV] = str(root)
    data_root.cache_clear()
    return root


def corpus_root() -> Path:
    """The directory holding the game files: ``corpus/`` under the data root.

    A clone that keeps its game files in the primary checkout's own ``corpus/`` has no
    ``corpus/`` in the data root, so that one is read instead, but only when it holds a
    folder of game files: ``corpus/README.md`` is tracked, so the folder itself exists in
    every checkout, and falling back to it would name the wrong place in every error.  Only
    the corpus falls back: the captures and the stage are written, and the stage must sit
    outside every checkout.
    """
    shared = data_root() / "corpus"
    if shared.is_dir() or os.environ.get(DATA_ENV):
        return shared
    primary = primary_checkout()
    if primary is None:
        return shared
    local = primary / "corpus"
    return local if _holds_folders(local) else shared


def _holds_folders(path: Path) -> bool:
    """True when directory *path* holds at least one directory; false when it is absent.

    Any other error is raised: falling back past an unreadable ``corpus/`` would send the
    user to look for the game files in the wrong place.
    """
    try:
        return any(entry.is_dir() for entry in path.iterdir())
    except FileNotFoundError, NotADirectoryError:
        return False


def require_corpus(root: Path | None = None) -> Path:
    """The corpus of data root *root* (the configured one by default), which must exist.

    A reader of the game files calls this first, so a machine without them is told where
    they were looked for instead of finding no films and reporting success.  The old links
    created ``corpus/<name>`` folders empty, so a corpus must hold a file, not only a folder.
    """
    corpus = corpus_root() if root is None else corpus_of(root)
    if not corpus.is_dir():
        raise SharedDataError(
            f"no game files: {corpus} is missing; set {DATA_ENV} or see corpus/README.md"
        )
    if not _holds_files(corpus):
        raise SharedDataError(
            f"no game files: {corpus} holds no game files; set {DATA_ENV} or see corpus/README.md"
        )
    return corpus


#: The first part of a relative path that names something in the data root.
_DATA_PARTS = ("corpus", parity_layout.capture_root().as_posix())


def corpus_of(root: Path) -> Path:
    """The corpus under the data root *root*: :func:`corpus_root` when *root* is this one.

    A caller handed a root explicitly (``--data-root``, or a test's directory) reads that
    root's ``corpus/``; the configured root keeps :func:`corpus_root`'s fallback to the
    primary checkout.
    """
    return corpus_root() if root == data_root() else root / "corpus"


def resolve_data_path(path: Path) -> Path:
    """*path* read against the data root when it is a relative ``corpus/`` or ``captures/`` path.

    Every task description and note spells a film ``corpus/stisldem/VAULT/CTRY.FLM``, relative
    to a checkout that no longer links the data root in (ADR 0033).  Any other path, absolute
    or relative, is returned unchanged.  The first part matches without regard to case, as
    a Windows path does.
    """
    if path.is_absolute() or not path.parts:
        return path
    first = path.parts[0].lower()
    if first not in _DATA_PARTS:
        return path
    if first == "corpus":
        return corpus_root().joinpath(*path.parts[1:])
    return data_root().joinpath(first, *path.parts[1:])


def data_path_arg(text: str) -> Path:
    """:func:`resolve_data_path` for an ``argparse`` ``type=``; it applies to string defaults too."""
    return resolve_data_path(Path(text))


def cache_root() -> Path:
    """The one writable tool-cache directory every checkout of this repository borrows."""
    primary = primary_checkout()
    return (primary if primary is not None else REPO_ROOT) / CACHE_DIRNAME


def env_root() -> Path:
    """The shared cache's directory of per-checkout Python environments."""
    return cache_root() / ENV_DIRNAME


def env_target(checkout: Path) -> Path:
    """Where *checkout*'s Python environment lives inside the shared cache."""
    digest = hashlib.blake2s(os.fsencode(str(checkout).lower()), digest_size=4).hexdigest()
    return env_root() / f"{checkout.name}-{digest}"


def env_marker(target: Path) -> Path:
    """The file beside environment *target* naming the checkout it serves."""
    return target.with_name(target.name + ENV_MARKER)


def discard_env(checkout: Path) -> bool:
    """Remove *checkout*'s environment from the shared cache; True when it went."""
    target = env_target(checkout)
    if is_link(target):
        return False
    if not target.exists():
        env_marker(target).unlink(missing_ok=True)
        return False
    return _remove_env(target)


def _remove_env(target: Path) -> bool:
    """Delete environment *target* and its marker; True when the environment went."""
    shutil.rmtree(target, ignore_errors=True)
    if target.exists():
        return False
    env_marker(target).unlink(missing_ok=True)
    return True


def _read_marker(marker: Path) -> str | None:
    """The checkout *marker* names, or ``None`` when it is missing, unreadable or empty."""
    try:
        checkout = marker.read_text(encoding="utf-8").strip()
    except OSError, UnicodeError:
        return None
    return checkout or None


def _env_owner(target: Path) -> Path | None:
    """The checkout environment *target* names, or ``None`` when no marker says.

    An environment made before the marker moved beside it still carries one inside.
    """
    for marker in (env_marker(target), target / ENV_MARKER):
        checkout = _read_marker(marker)
        if checkout is not None:
            return Path(checkout)
    return None


def orphan_envs() -> list[Path]:
    """Environments whose checkout is gone: reaped, or removed by another tool.

    An environment with no marker is kept: its owner is unknown, not proven gone.
    """
    root = env_root()
    if not root.is_dir():
        return []
    orphans: list[Path] = []
    for child in sorted(root.iterdir()):
        if is_link(child) or not child.is_dir():
            continue
        checkout = _env_owner(child)
        if checkout is not None and not checkout.is_dir():
            orphans.append(child)
    return orphans


def sweep_orphan_envs() -> list[Path]:
    """Remove every orphaned environment, and any marker left without one.

    Returns the environments that went.  A marker whose environment uv is replacing at
    that moment can go too; the environment is then kept as unknown-owner until its
    checkout's next init writes the marker again.
    """
    removed = [target for target in orphan_envs() if _remove_env(target)]
    for marker in env_root().glob(f"*{ENV_MARKER}"):
        environment = marker.with_name(marker.name.removesuffix(ENV_MARKER))
        if marker.is_file() and not environment.exists():
            marker.unlink(missing_ok=True)
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


#: Environment variable that carries the path into ``cmd``; see :func:`_shell_rmdir`.
_RMDIR_PATH_VAR = "STUNT_REEL_RMDIR_PATH"


def _shell_rmdir(path: Path) -> None:
    """Remove the empty-or-linked directory *path* with ``cmd /c rmdir``, never recursively.

    On a junction ``rmdir`` removes the reparse point and leaves its target alone; there
    is deliberately no ``/s``, so a real directory that still holds files is refused
    instead of emptied.

    ``cmd`` parses its own command line, so the path never appears on it: it rides in an
    environment variable that ``/v:on`` expands after parsing, so ``&``, ``%``, ``(``, ``^``
    or any other character of a valid name is plain text and cannot start a command.
    ``/d`` skips any AutoRun command, and undecodable shell output is replaced rather than
    raised, so a localised error message still reaches the caller.
    """
    comspec = os.environ.get("COMSPEC", "cmd.exe")
    command = f'"{comspec}" /d /v:on /c rmdir "!{_RMDIR_PATH_VAR}!"'
    result = subprocess.run(  # noqa: S603
        command,
        env={**os.environ, _RMDIR_PATH_VAR: str(path)},
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OSError(f"rmdir exited {result.returncode}: {detail}")


def remove_link(path: Path) -> None:
    """Remove a symbolic link or junction, never the directory it points at.

    Some Windows machines refuse Python's directory removal on a junction with
    ``[WinError 5] Access is denied`` yet let the shell's ``rmdir`` remove the same one
    (docs/harness-setup.md).  A permission error on Windows therefore retries once with
    the shell's non-recursive ``rmdir``; if that fails too, the error names both.
    """
    if path.is_symlink():
        path.unlink()
        return
    try:
        path.rmdir()
    except PermissionError as first:
        if os.name != "nt":
            raise
        try:
            _shell_rmdir(path)
        except OSError as second:
            raise OSError(
                f"rmdir refused ({first}); the shell's rmdir fallback failed too ({second})"
            ) from second


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


def _holds_files(path: Path) -> bool:
    """True when *path* is a file or a directory tree containing one."""
    return path.is_file() or (path.is_dir() and any(item.is_file() for item in path.rglob("*")))


def _legacy_destination(film: str) -> Path:
    """Where an old ``reference/<film>`` goes, relative to the data root."""
    return parity_layout.frames_path(f"vault-{film}")


def convert_layout(root: Path) -> list[str]:
    """Convert an old-layout data root to the corpus/captures layout (ADR 0022); say what moved.

    ``stisldem`` and ``si_archive`` move under ``corpus/`` (the second as ``siarchive``),
    ``target_bin/StuntIsl`` becomes ``corpus/stuntisl`` and ``target_bin/patch`` becomes
    ``corpus/patches``.  The top-level ``target_bin/PLAYONE.EXE`` is dropped when it is
    byte-identical to ``StuntIsl``'s, and ``oracle`` is deleted: it was generated, not
    evidence.  ``reference/<film>`` becomes ``captures/vault-<film>/frames`` (ADR 0028).
    A root already in the new layout is left alone; one holding both an old name and a new
    name with files in it is refused before anything moves, because merging them would guess which side is right.
    """
    old = [name for name in _OLD_NAMES if (root / name).exists()]
    if not old:
        return []
    # An earlier layout's links created the new directories empty before a migration; those
    # are not data, so only a new name holding files is a conflict.
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
        (film, root / _legacy_destination(film.name))
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
