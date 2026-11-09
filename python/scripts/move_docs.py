"""Move docs with ``git mv`` as a moves file lists them, and rewrite every link and path to them.

A moves file is TOML. Each ``[[move]]`` table has ``from`` and ``to``, repo-relative POSIX
paths; a directory moves as a whole, its files keeping their layout under ``to``. Each optional
``[[folder]]`` table describes a new work folder (``path``, ``title``, ``started``,
``outcome``, and ``issue`` or, for dropped work, ``status = "abandoned"``; a folder with neither
is landed) whose README ``apply`` writes; its ``state_source``, how a plan's state was
inferred, stays in the moves file as a record.

``apply --phase move`` runs ``git mv`` for every moved file, writes the folder READMEs (left
unstaged) and rewrites every tracked text file that did not move, so each moved file keeps its
bytes and git records a 100% rename; it refuses a directory move onto an existing path and a
``[[folder]]`` inside a moved directory. ``apply --phase inside`` then rewrites the moved files'
own links: each resolves from the file's old place and is written from its new one. It refuses
a second run, seen as a link it would change that already resolves from the new place.
Both print the old-to-new table in Markdown for the PR body, then the files written;
``--dry-run`` prints the same and changes nothing.

Rewriting a file (``rewrite_text``): a Markdown file's links outside code (inline, image and
reference definitions) follow their target, fragment kept; and a file that is not a dated record
(under ``work/<YYYY-MM>/``) has each repo-root-relative path in the map replaced wherever it
appears, code included, since a dated record changes only for link fixes. A text file is a
tracked file outside ``corpus/`` that decodes as UTF-8 and holds no NUL byte; any other file
whose bytes name a moved path is listed for a person to edit. The moves file itself is never
rewritten.

Usage: ``mise run move-docs -- apply <moves.toml> --phase move|inside [--dry-run] [--root DIR]``.
Exit status: ``0`` on success, ``1`` for a moves file that does not fit the tree or a failed git
command, ``2`` for bad arguments.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import date, datetime
from pathlib import Path
from typing import Any
lazy from collections.abc import Collection, Iterable

from stunt_reel import git_env
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.markdown_links import (
    LINK_DEFINITION_REGEX,
    MARKDOWN_LINK_REGEX,
    URL_SCHEME_REGEX,
    prose,
)
from stunt_reel.work_items import WorkFolderError, is_dated, parse_folder, readme_text

type Edit = tuple[int, int, str]

_MOVE_KEYS = frozenset(("from", "to"))
_FOLDER_KEYS = frozenset(("path", "title", "started", "issue", "status", "outcome", "state_source"))
#: Where a link target's path ends and its query or fragment begins.
_QUERY_OR_FRAGMENT = re.compile(r"[?#]")


class MovesError(Exception):
    """The moves file is malformed or does not fit the tree; the message says where."""


def load_moves(path: Path, tracked: Collection[str]) -> list[tuple[str, str]]:
    """*path*'s ``[[move]]`` entries as (old, new) pairs at file level, in the file's order.

    A directory entry gives a pair of its own, both paths ending in ``/``, then one pair per
    *tracked* file under it, found under ``from`` before the move or under ``to`` after it.
    Raises MovesError for a malformed file, an entry with neither side in *tracked*, or a path
    that two pairs share.
    """
    return _moves(_read(path), tracked)


def path_map(moves: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Each moved file's old path to its new one, and each moved directory's and subdirectory's."""
    mapping: dict[str, str] = {}
    pairs = list(moves)
    directories = [(old, new) for old, new in pairs if old.endswith("/")]
    for old, new in pairs:
        if old.endswith("/"):
            mapping[old.rstrip("/")] = new.rstrip("/")
            continue
        mapping[old] = new
        for old_dir, new_dir in directories:
            if old.startswith(old_dir):
                parts = old.removeprefix(old_dir).split("/")[:-1]
                for depth in range(1, len(parts) + 1):
                    sub = "/".join(parts[:depth])
                    mapping[old_dir + sub] = new_dir + sub
    return mapping


def rewrite_text(
    text: str, source_old: str, source_new: str, mapping: dict[str, str], *, markdown: bool
) -> str:
    """*text*, the file at repo path *source_old* that now sits at *source_new*, after *mapping*.

    When *markdown*, each link outside code whose target is in *mapping* (a file, a directory or
    a path under one), or whose file moved, is written relative to *source_new*, with its query
    and fragment kept. Unless *source_new* is a dated record, every repo-root-relative path in
    *mapping* is replaced where it appears outside those links, on path boundaries, a directory
    as a prefix. Every other character is kept.
    """
    edits: list[Edit] = []
    links = _link_spans(text) if markdown else []
    for start, end in links:
        new = _relink(text[start:end], source_old, source_new, mapping)
        if new is not None:
            edits.append((start, end, new))
    if mapping and not is_dated(source_new):
        for match in _path_regex(tuple(mapping)).finditer(text):
            if not any(start < match.end() and match.start() < end for start, end in links):
                edits.append((match.start(), match.end(), mapping[match[0]]))
    return _apply_edits(text, edits)


def main(argv: list[str] | None = None) -> int:
    """Run ``apply`` from *argv*; see the module docstring."""
    args = _parser().parse_args(argv)
    root: Path = args.root.resolve()
    moving = args.phase == "move"
    try:
        tracked = set(_tracked(root))
        data = _read(args.moves)
        moves = _moves(data, tracked)
        mapping = path_map(moves)
        files = [(old, new) for old, new in moves if not old.endswith("/")]
        _check_phase(root, tracked, moves, moving=moving)
        if moving:
            readmes = _readmes(data, root, tracked, moves)
            skipped = {old for old, _ in files} | {_relative(args.moves, root)}
            stay = [(path, path) for path in sorted(tracked - skipped)]
            rewrites, untouched = _rewrites(root, stay, mapping)
        else:
            _check_not_relinked(root, tracked, files, mapping)
            readmes = []
            rewrites, untouched = _rewrites(root, files, mapping)
        _print_tables(files, data.get("folder", []) if moving else [])
        if not args.dry_run:
            _write(root, files if moving else [], [*readmes, *rewrites])
    except (MovesError, OSError) as error:
        print(f"move-docs: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        detail = str(error.stderr or "").strip() or f"exit status {error.returncode}"
        print(f"move-docs: `git {error.cmd[1]}` failed: {detail}", file=sys.stderr)
        return 1
    verb = ("Would write", "Would rewrite") if args.dry_run else ("Wrote", "Rewrote")
    _print_list(f"{verb[0]} {len(readmes)} README file(s)", [path for path, _ in readmes])
    _print_list(f"{verb[1]} {len(rewrites)} file(s)", [path for path, _ in rewrites])
    if untouched:
        heading = (
            "Left alone as binary (a NUL byte, or not UTF-8), yet naming a moved path; edit by hand"
        )
        _print_list(heading, untouched)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mise run move-docs --",
        description="Move docs with git mv as a moves file lists them, and rewrite their links.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    apply = commands.add_parser("apply", help="apply one phase of a moves file")
    apply.add_argument("moves", type=Path, help="the moves file, TOML")
    apply.add_argument(
        "--phase",
        required=True,
        choices=("move", "inside"),
        help="move: git mv and rewrite the files that stay; inside: rewrite the moved files",
    )
    apply.add_argument("--dry-run", action="store_true", help="print what it would do, only")
    apply.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="the repository (default: this checkout)"
    )
    return parser


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise MovesError(f"{path}: not valid TOML: {error}") from error
    if unknown := sorted(data.keys() - {"move", "folder"}):
        raise MovesError(
            f"{path}: unknown key(s) {', '.join(unknown)}; expected [[move]], [[folder]]"
        )
    for key in ("move", "folder"):
        tables = data.get(key, [])
        if not isinstance(tables, list) or not all(isinstance(table, dict) for table in tables):
            raise MovesError(f"{path}: {key} must be [[{key}]] tables")
    if not data.get("move"):
        raise MovesError(f"{path}: lists no [[move]]")
    return data


def _moves(data: dict[str, Any], tracked: Collection[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for number, table in enumerate(data["move"], start=1):
        if table.keys() != _MOVE_KEYS:
            raise MovesError(f"[[move]] {number} needs from and to, and nothing else")
        old = _clean(table["from"], f"[[move]] {number} from")
        new = _clean(table["to"], f"[[move]] {number} to")
        pairs.extend(_expand(old, new, tracked))
    for side in (0, 1):
        seen: set[str] = set()
        for pair in pairs:
            if pair[side] in seen:
                raise MovesError(f"{pair[side]} appears twice in the moves")
            seen.add(pair[side])
    return pairs


def _expand(old: str, new: str, tracked: Collection[str]) -> list[tuple[str, str]]:
    """(old, new) for a file, or the directory's own pair then its files' pairs."""
    if old in tracked or new in tracked:
        return [(old, new)]
    if inside := sorted(path for path in tracked if path.startswith(f"{old}/")):
        return [(f"{old}/", f"{new}/"), *((path, new + path[len(old) :]) for path in inside)]
    if inside := sorted(path for path in tracked if path.startswith(f"{new}/")):
        return [(f"{old}/", f"{new}/"), *((old + path[len(new) :], path) for path in inside)]
    raise MovesError(f"neither {old} nor {new} is tracked")


def _clean(value: object, what: str) -> str:
    """*value* as a repo-relative POSIX path without a trailing ``/``."""
    path = value.rstrip("/") if isinstance(value, str) else ""
    parts = path.split("/")
    if not path or "\\" in path or any(part in ("", ".", "..") for part in parts):
        raise MovesError(f"{what} {value!r} is not a repo-relative POSIX path")
    return path


def _readmes(
    data: dict[str, Any], root: Path, tracked: Collection[str], moves: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """(path, text) of each ``[[folder]]`` README, checked to parse as a work folder and to sit
    neither on a file the moves bring nor inside a moved directory."""
    targets = {new for _, new in moves}
    directories = [new.rstrip("/") for old, new in moves if old.endswith("/")]
    readmes: list[tuple[str, str]] = []
    for number, table in enumerate(data.get("folder", []), start=1):
        if unknown := sorted(table.keys() - _FOLDER_KEYS):
            raise MovesError(f"[[folder]] {number} has unknown keys: {', '.join(unknown)}")
        path = _clean(table.get("path"), f"[[folder]] {number} path")
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "work":
            raise MovesError(f"[[folder]] {path} is not work/<YYYY-MM>/<name>")
        for directory in directories:
            if path == directory or path.startswith(f"{directory}/"):
                raise MovesError(f"[[folder]] {path} is inside the moved directory {directory}")
        try:
            text = readme_text(
                _text_field(table, "title", path),
                _started(table.get("started"), path),
                _text_field(table, "outcome", path, default=""),
                issue=_int_field(table, path),
                status=table.get("status"),
            )
        except WorkFolderError as error:
            raise MovesError(f"[[folder]] {path}: {error}") from error
        _check_folder(parts, text)
        readme = f"{path}/README.md"
        if readme in targets or readme in tracked or (root / readme).exists():
            raise MovesError(f"{readme} already exists or is a move's target")
        if readme in (seen[0] for seen in readmes):
            raise MovesError(f"[[folder]] {path} appears twice")
        readmes.append((readme, text))
    return readmes


def _text_field(table: dict[str, Any], key: str, path: str, default: str | None = None) -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise MovesError(f"[[folder]] {path}: {key} must be a string")
    return value


def _int_field(table: dict[str, Any], path: str) -> int | None:
    value = table.get("issue")
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise MovesError(f"[[folder]] {path}: issue must be a number")
    return value


def _started(value: object, path: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise MovesError(f"[[folder]] {path}: started {value!r} is not a date")


def _check_folder(parts: list[str], text: str) -> None:
    """Raise MovesError unless a folder at ``<month>/<name>`` with README *text* parses."""
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch, *parts[1:])
        folder.mkdir(parents=True)
        (folder / "README.md").write_text(text, encoding="utf-8", newline="\n")
        try:
            parse_folder(folder)
        except WorkFolderError as error:
            raise MovesError(f"[[folder]] work/{error}") from error


def _check_phase(
    root: Path, tracked: set[str], moves: list[tuple[str, str]], *, moving: bool
) -> None:
    """Raise MovesError unless every file is where the phase expects it.

    Before the move a directory's ``to`` must not exist: the inside phase reads every file under
    it as one the move brought.
    """
    for old, new in moves:
        if old.endswith("/"):
            if moving and ((root / new).exists() or any(p.startswith(new) for p in tracked)):
                raise MovesError(
                    f"{new.rstrip('/')} already exists; a directory moves to a new path"
                )
        elif moving and old not in tracked:
            raise MovesError(f"{old} is not tracked; has --phase move already run?")
        elif moving and (new in tracked or (root / new).exists()):
            raise MovesError(f"{new} already exists")
        elif not moving and (old in tracked or new not in tracked):
            raise MovesError(f"{old} has not moved to {new}; run --phase move first")


def _check_not_relinked(
    root: Path, tracked: set[str], files: list[tuple[str, str]], mapping: dict[str, str]
) -> None:
    """Raise MovesError when a moved file's relative link that the inside phase would change
    already resolves from the file's new place to a tracked file or directory: the phase ran."""
    directories: set[str] = set()
    for path in tracked:
        parts = path.split("/")
        directories.update("/".join(parts[:depth]) for depth in range(1, len(parts)))
    for old, new in files:
        text = _contents(root, new) if new.endswith(".md") else None
        if not isinstance(text, str):
            continue
        for start, end in _link_spans(text):
            target = text[start:end]
            split = _split_target(target)
            if split is None or split[0].startswith("/"):
                continue
            if _relink(target, old, new, mapping) is None:
                continue
            here = _resolve(split[0], new)
            if here is not None and (here in tracked or here in directories):
                raise MovesError(
                    f"{new}: link {target} already resolves from its new place; "
                    "has --phase inside already run?"
                )


def _rewrites(
    root: Path, files: list[tuple[str, str]], mapping: dict[str, str]
) -> tuple[list[tuple[str, str]], list[str]]:
    """(path, new text) for each (old, current) path pair whose text the move changes, and the
    paths of the files that are not text but whose bytes name a moved path, for a person."""
    rewrites: list[tuple[str, str]] = []
    untouched: list[str] = []
    for old, path in files:
        contents = _contents(root, path)
        if isinstance(contents, bytes):
            if not is_dated(path) and any(key.encode() in contents for key in mapping):
                untouched.append(path)
        elif contents is not None:
            text = rewrite_text(contents, old, path, mapping, markdown=path.endswith(".md"))
            if text != contents:
                rewrites.append((path, text))
    return rewrites, untouched


def _write(root: Path, files: list[tuple[str, str]], texts: list[tuple[str, str]]) -> None:
    """``git mv`` each of *files*, then write each of *texts*' bytes as UTF-8."""
    for old, new in files:
        (root / new).parent.mkdir(parents=True, exist_ok=True)
        _git(root, "mv", "--", old, new)
    for path, text in texts:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(text.encode("utf-8"))


def _print_tables(files: list[tuple[str, str]], folders: list[dict[str, Any]]) -> None:
    print("| Old path | New path |\n| --- | --- |")
    for old, new in files:
        print(f"| `{old}` | `{new}` |")
    if folders:
        print("\n| Folder | Issue or status | State source |\n| --- | --- | --- |")
        for table in folders:
            record = f"#{table['issue']}" if "issue" in table else table.get("status", "landed")
            print(f"| `{table['path']}` | {record} | {table.get('state_source', '')} |")
    print()


def _print_list(heading: str, paths: list[str]) -> None:
    print(f"{heading}:" if paths else f"{heading}.")
    for path in paths:
        print(f"  {path}")


def _relink(target: str, source_old: str, source_new: str, mapping: dict[str, str]) -> str | None:
    """The link *target* rewritten for the move, or None when it stays."""
    split = _split_target(target)
    if split is None:
        return None
    path, rest = split
    rooted = path.startswith("/")
    resolved = _resolve(path, source_old)
    if resolved is None:
        return None
    moved = _moved(resolved, mapping)
    # A rooted link, `/docs/x.md`, reads the same from anywhere.
    if moved is None and (rooted or source_old == source_new):
        return None
    destination = resolved if moved is None else moved
    if rooted:
        new = f"/{destination}"
    else:
        new = _relative_path(destination, posixpath.dirname(source_new))
    if path.endswith("/") and not new.endswith("/"):
        new += "/"
    new += rest
    return None if new == target else new


def _link_spans(text: str) -> list[tuple[int, int]]:
    """Where each Markdown link target outside code sits in *text*: inline, image, definition."""
    blanked = prose(text)
    return [
        match.span(1)
        for regex in (MARKDOWN_LINK_REGEX, LINK_DEFINITION_REGEX)
        for match in regex.finditer(blanked)
    ]


def _split_target(target: str) -> tuple[str, str] | None:
    """(path, query and fragment) of a link *target*; None for a URL or a bare fragment."""
    if URL_SCHEME_REGEX.match(target):
        return None
    path = _QUERY_OR_FRAGMENT.split(target, maxsplit=1)[0]
    return (path, target[len(path) :]) if path else None


def _resolve(path: str, source: str) -> str | None:
    """Link *path* in repo file *source* as a repo path (``/`` is the root); None outside it."""
    base = "" if path.startswith("/") else posixpath.dirname(source)
    resolved = posixpath.normpath(posixpath.join(base, path.lstrip("/")))
    return None if resolved == ".." or resolved.startswith("../") else resolved


def _moved(path: str, mapping: dict[str, str]) -> str | None:
    """Where *path* went: its own entry, or its nearest moved ancestor's; None if it stayed."""
    if path in mapping:
        return mapping[path]
    parts = path.split("/")
    for depth in range(len(parts) - 1, 0, -1):
        prefix = "/".join(parts[:depth])
        if prefix in mapping:
            return mapping[prefix] + path[len(prefix) :]
    return None


def _relative_path(target: str, start: str) -> str:
    """Repo path *target* written relative to repo directory *start* (``""`` or ``.`` is the root)."""
    to = [] if target in ("", ".") else target.split("/")
    base = [] if start in ("", ".") else start.split("/")
    common = 0
    while common < min(len(to), len(base)) and to[common] == base[common]:
        common += 1
    return "/".join([".."] * (len(base) - common) + to[common:]) or "."


def _path_regex(keys: tuple[str, ...]) -> re.Pattern[str]:
    """A repo path in *keys*, longest first, not inside a longer path; ``/`` may follow it."""
    alternatives = "|".join(re.escape(key) for key in sorted(keys, key=len, reverse=True))
    return re.compile(rf"(?<![\w./-])(?:{alternatives})(?![\w-])(?!\.[\w-])")


def _apply_edits(text: str, edits: list[Edit]) -> str:
    out: list[str] = []
    position = 0
    for start, end, new in sorted(edits):
        if start < position:
            continue
        out.extend((text[position:start], new))
        position = end
    out.append(text[position:])
    return "".join(out)


def _contents(root: Path, path: str) -> str | bytes | None:
    """The file's text; its bytes when they hold a NUL or are not UTF-8; None under corpus/ or
    when it is not a regular file."""
    if path.split("/", maxsplit=1)[0] == "corpus":
        return None
    full = root / path
    if full.is_symlink() or not full.is_file():
        return None
    data = full.read_bytes()
    if b"\x00" in data:
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data


def _relative(path: Path, root: Path) -> str | None:
    resolved = path.resolve()
    return resolved.relative_to(root).as_posix() if resolved.is_relative_to(root) else None


def _tracked(root: Path) -> list[str]:
    return [name for name in _git(root, "ls-files", "-z").split("\0") if name]


def _git(root: Path, *args: str) -> str:
    """``git args`` on *root*'s own repository and index."""
    git = shutil.which("git")
    if git is None:
        raise MovesError("git is not on PATH")
    env = git_env.clean_environ()
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        [git, *args], cwd=root, env=env, capture_output=True, encoding="utf-8", check=True
    )
    return done.stdout


if __name__ == "__main__":
    sys.exit(main())
