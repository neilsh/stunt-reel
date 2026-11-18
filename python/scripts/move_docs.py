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

A ``[[split]]`` table relinks one section of a note split into topic files: ``from`` and ``to``
are repo-relative POSIX paths, and each may end in ``#<anchor>``, a GitHub heading anchor
(duplicate headings take the ``-1``, ``-2`` suffixes GitHub gives them). A ``to`` without a
fragment keeps the section's anchor; a ``from`` without one names the whole-file destination
for links to the note that carry no fragment, once per note. ``from`` names the note by its
pre-move path; the note must be tracked and each anchor must be one of its headings. On either
phase a link to a split note is written to the mapped file with its query kept; a link whose
fragment is a heading the note keeps, when the plan does not move the note, is left alone, and
an inbound link whose fragment names no mapped section and no kept heading is reported and makes the run exit non-zero without
writing; the move phase checks the files that stay and the files about to move before any
git mv runs. A self-link (a bare ``#<anchor>`` in the note) whose section a rule moved is
printed as a warning under its own heading and does not change the exit status, since the note's
text is not cut; a link in a destination file to its own section is written as
``#<anchor>``.

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
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
lazy from collections.abc import Collection, Iterable

from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.git_env import isolated_env
from stunt_reel.markdown_links import (
    HEADING_REGEX,
    LINK_DEFINITION_REGEX,
    MARKDOWN_LINK_REGEX,
    URL_SCHEME_REGEX,
    prose,
    slug,
)
from stunt_reel.work_items import WorkFolderError, is_dated, parse_folder, readme_text

type Edit = tuple[int, int, str]
type Splits = dict[str, "Split"]


@dataclass
class Split:
    """How links to one split note are relinked: its whole-file destination and its sections."""

    #: Where a link to the note with no fragment goes; None leaves such links alone.
    default: str | None = None
    #: Each section's GitHub anchor to (its new file, the anchor to write there or None).
    sections: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    #: Anchors of headings the note keeps at its own path, so a link to one needs no rule.
    staying: set[str] = field(default_factory=set)


_MOVE_KEYS = frozenset(("from", "to"))
_SPLIT_KEYS = frozenset(("from", "to"))
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
    text: str,
    source_old: str,
    source_new: str,
    mapping: dict[str, str],
    *,
    markdown: bool,
    splits: Splits | None = None,
    unmapped: list[str] | None = None,
    warnings: list[str] | None = None,
) -> str:
    """*text*, the file at repo path *source_old* that now sits at *source_new*, after *mapping*.

    When *markdown*, each link outside code whose target is in *mapping* (a file, a directory or
    a path under one), or whose file moved, is written relative to *source_new*, with its query
    and fragment kept. A link to a note in *splits* goes to the file mapped for its fragment, or
    to the note's whole-file destination when it has none; a fragment with no mapping is added to
    *unmapped* and the link is left as it is, while a self-link to a section a rule moved is
    added to *warnings* and left alone. Unless *source_new* is a dated record, every
    repo-root-relative path in *mapping* is replaced where it appears outside those links, on
    path boundaries, a directory as a prefix. Every other character is kept.
    """
    edits: list[Edit] = []
    links = _link_spans(text) if markdown else []
    for start, end in links:
        new = _relink(text[start:end], source_old, source_new, mapping, splits, unmapped, warnings)
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
        splits = _splits(data)
        _check_splits(splits, root, tracked, mapping, moving=moving)
        files = [(old, new) for old, new in moves if not old.endswith("/")]
        _check_phase(root, tracked, moves, moving=moving)
        unmapped: list[str] = []
        warnings: list[str] = []
        if moving:
            readmes = _readmes(data, root, tracked, moves)
            skipped = {old for old, _ in files} | {_relative(args.moves, root)}
            stay = [(path, path) for path in sorted(tracked - skipped)]
            rewrites, untouched = _rewrites(root, stay, mapping, splits, unmapped, warnings)
            unmapped += _unmapped_in_moved(root, files, mapping, splits, warnings)
        else:
            _check_not_relinked(root, tracked, files, mapping)
            readmes = []
            rewrites, untouched = _rewrites(root, files, mapping, splits, unmapped, warnings)
        _check_unmapped(unmapped)
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
    if warnings:
        _print_list(
            "Self-links in the split note that point at moved sections; "
            "fix them by hand after cutting the note",
            sorted(dict.fromkeys(warnings)),
        )
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
    if unknown := sorted(data.keys() - {"move", "folder", "split"}):
        raise MovesError(
            f"{path}: unknown key(s) {', '.join(unknown)}; "
            "expected [[move]], [[folder]] or [[split]]"
        )
    for key in ("move", "folder", "split"):
        tables = data.get(key, [])
        if not isinstance(tables, list) or not all(isinstance(table, dict) for table in tables):
            raise MovesError(f"{path}: {key} must be [[{key}]] tables")
    if not data.get("move") and not data.get("split"):
        raise MovesError(f"{path}: lists no [[move]] or [[split]]")
    return data


def _moves(data: dict[str, Any], tracked: Collection[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for number, table in enumerate(data.get("move", []), start=1):
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


def _splits(data: dict[str, Any]) -> Splits:
    """*data*'s ``[[split]]`` rules: each split note's whole-file destination and its sections."""
    splits: Splits = {}
    for number, table in enumerate(data.get("split", []), start=1):
        if table.keys() != _SPLIT_KEYS:
            raise MovesError(f"[[split]] {number} needs from and to, and nothing else")
        source, anchor = _split_side(table["from"], f"[[split]] {number} from")
        destination, destination_anchor = _split_side(table["to"], f"[[split]] {number} to")
        for side, path in (("from", source), ("to", destination)):
            if not path.endswith(".md"):
                raise MovesError(f"[[split]] {number} {side} {path} is not a Markdown file")
        split = splits.setdefault(source, Split())
        if anchor is None:
            if split.default is not None:
                raise MovesError(f"{source} names its whole-file destination twice")
            split.default = destination
            continue
        key = slug(anchor)
        if key in split.sections:
            raise MovesError(f"{source}#{anchor} appears twice in the splits")
        split.sections[key] = (
            destination,
            None if destination_anchor is None else slug(destination_anchor),
        )
    return splits


def _check_splits(
    splits: Splits,
    root: Path,
    tracked: Collection[str],
    mapping: dict[str, str],
    *,
    moving: bool,
) -> None:
    """Raise MovesError unless each split source is a tracked note whose headings map its anchors.

    *source* is the note's pre-move path: keyed by a move destination, that is, a path a move
    brings, the rules would silently never apply, so it is refused. The note is read at *source*
    in the move phase and at its new path in the inside phase.
    """
    reverse = {new: old for old, new in mapping.items()}
    for source, split in splits.items():
        if (pre_move := _moved(source, reverse)) is not None:
            raise MovesError(
                f"[[split]] {source} is a move destination; key it by its pre-move path {pre_move}"
            )
        current = source if moving else (_moved(source, mapping) or source)
        if current not in tracked:
            raise MovesError(f"[[split]] {source} is not a tracked note")
        note = root / current
        if not note.is_file():
            raise MovesError(f"[[split]] {source} does not exist")
        anchors = _heading_anchors(note.read_text(encoding="utf-8"))
        for key in split.sections:
            if key not in anchors:
                raise MovesError(f"[[split]] {source}#{key} names no heading of {source}")
        if _moved(source, mapping) is None:
            split.staying = anchors - split.sections.keys()


def _heading_anchors(text: str) -> set[str]:
    """GitHub's anchors for *text*'s headings, outside fenced code, duplicates numbered -1 onward."""
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    for blanked, line in zip(prose(text).splitlines(), text.splitlines(), strict=True):
        heading = HEADING_REGEX.match(line) if HEADING_REGEX.match(blanked) else None
        if heading is None:
            continue
        base = slug(heading[2])
        count = seen.get(base, 0)
        anchors.add(base if count == 0 else f"{base}-{count}")
        seen[base] = count + 1
    return anchors


def _split_side(value: object, what: str) -> tuple[str, str | None]:
    """A ``path[#anchor]`` split value as its repo path and its GitHub anchor, if it has one."""
    raw = value if isinstance(value, str) else ""
    path, hashmark, anchor = raw.partition("#")
    if hashmark and (not slug(anchor) or anchor != anchor.strip() or "#" in anchor):
        raise MovesError(f"{what} {value!r} does not end in a non-empty heading anchor")
    return _clean(path, what), (anchor if hashmark else None)


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


def _unmapped_in_moved(
    root: Path,
    files: list[tuple[str, str]],
    mapping: dict[str, str],
    splits: Splits,
    warnings: list[str],
) -> list[str]:
    """Section links in the files that will move, resolved from their old paths, that no rule maps.

    The move phase does not rewrite a moved file, so this only collects the report: an unmapped
    section link is refused before any git mv runs, while a self-link to a moved section only
    warns (issue #523).
    """
    unmapped: list[str] = []
    for old, _new in files:
        contents = _contents(root, old) if old.endswith(".md") else None
        if not isinstance(contents, str):
            continue
        for start, end in _link_spans(contents):
            _relink(contents[start:end], old, old, mapping, splits, unmapped, warnings)
    return unmapped


def _check_unmapped(unmapped: list[str]) -> None:
    """Raise MovesError naming every section link no ``[[split]]`` rule maps."""
    if unmapped:
        raise MovesError(
            "these links point at a section with no [[split]] mapping:\n  "
            + "\n  ".join(dict.fromkeys(unmapped))
        )


def _check_not_relinked(
    root: Path,
    tracked: set[str],
    files: list[tuple[str, str]],
    mapping: dict[str, str],
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
            # Only the move matters here: a split rewrite is not evidence the inside phase ran.
            if _relink(target, old, new, mapping) is None:
                continue
            here = _resolve(split[0], new)
            if here is not None and (here in tracked or here in directories):
                raise MovesError(
                    f"{new}: link {target} already resolves from its new place; "
                    "has --phase inside already run?"
                )


def _rewrites(
    root: Path,
    files: list[tuple[str, str]],
    mapping: dict[str, str],
    splits: Splits,
    unmapped: list[str],
    warnings: list[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    """(path, new text) for each (old, current) path pair whose text the move changes, and the
    paths of the files that are not text but whose bytes name a moved path, for a person.

    A section link with no split mapping is appended to *unmapped*; a self-link to a moved
    section is appended to *warnings*.
    """
    rewrites: list[tuple[str, str]] = []
    untouched: list[str] = []
    for old, path in files:
        contents = _contents(root, path)
        if isinstance(contents, bytes):
            if not is_dated(path) and any(key.encode() in contents for key in mapping):
                untouched.append(path)
        elif contents is not None:
            text = rewrite_text(
                contents,
                old,
                path,
                mapping,
                markdown=path.endswith(".md"),
                splits=splits,
                unmapped=unmapped,
                warnings=warnings,
            )
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


def _relink(
    target: str,
    source_old: str,
    source_new: str,
    mapping: dict[str, str],
    splits: Splits | None = None,
    unmapped: list[str] | None = None,
    warnings: list[str] | None = None,
) -> str | None:
    """The link *target* rewritten for the move or split, or None when it stays."""
    if target.startswith("#"):
        _split_self_link(target, source_old, source_new, splits, warnings)
        return None
    split = _split_target(target)
    if split is None:
        return None
    path, rest = split
    rooted = path.startswith("/")
    resolved = _resolve(path, source_old)
    if resolved is None:
        return None
    section = _split_section(resolved, rest, splits, source_new, target, unmapped)
    if section is not None:
        destination, section_rest = section
        destination = _moved(destination, mapping) or destination
        if destination == source_new and section_rest.startswith("#"):
            # The file already is the destination: its own section is a bare fragment.
            return None if section_rest == target else section_rest
        if rooted:
            new = f"/{destination}"
        else:
            new = _relative_path(destination, posixpath.dirname(source_new))
        new += section_rest
        return None if new == target else new
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


def _split_self_link(
    target: str,
    source_old: str,
    source_new: str,
    splits: Splits | None,
    warnings: list[str] | None,
) -> None:
    """Warn about a bare fragment in the split note whose section a rule moved to another file.

    The tool does not cut the note, so the note's own links cannot be relinked; the person making
    the split fixes them by hand, and the run still succeeds.
    """
    if not splits or warnings is None or (split := splits.get(source_old)) is None:
        return
    fragment = target[1:]
    if not fragment or (section := split.sections.get(slug(fragment))) is None:
        return
    destination, anchor = section
    if destination != source_old:
        warnings.append(
            f"{source_new}: {target} is a self-link whose section moved to "
            f"{destination}#{anchor or slug(fragment)}"
        )


def _split_section(
    resolved: str,
    rest: str,
    splits: Splits | None,
    source_new: str,
    target: str,
    unmapped: list[str] | None,
) -> tuple[str, str] | None:
    """The new file and query/fragment for a link to a split note, or None when it stays."""
    if not splits or (split := splits.get(resolved)) is None:
        return None
    query, hashmark, fragment = rest.partition("#")
    if not hashmark or not fragment:
        return (split.default, rest) if split.default is not None else None
    key = slug(fragment)
    section = split.sections.get(key)
    if section is None:
        if key in split.staying:
            return None
        if unmapped is not None:
            unmapped.append(
                f"{source_new}: {target} points at a section of {resolved} "
                "with no [[split]] mapping"
            )
        return None
    destination, anchor = section
    return destination, f"{query}#{anchor or slug(fragment)}"


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
    env = isolated_env(keep_index=False)
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        [git, *args], cwd=root, env=env, capture_output=True, encoding="utf-8", check=True
    )
    return done.stdout


if __name__ == "__main__":
    sys.exit(main())
