"""Print a capture's content hash and the ``references.toml`` entry that would promote it.

Every promotion of a reference capture needs the ``sha256`` that
:func:`stunt_reel.references.capture_digest` computes, and there was no command for it. This
prints that hash for one capture, read through this checkout's link to the data root, and,
when ``references.toml`` has an entry for the capture's film, the replacement entry to paste
in a reviewed commit, with the capture the entry names now. It writes nothing; promoting
stays an edit of ``research/parity/references.toml`` (ADR 0022).

Usage: ``mise run capture-digest -- vault-ctry 005`` (film slug, run id), or
``mise run capture-digest -- --dir <capture directory>``.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import dataroot, parity_layout, references

if TYPE_CHECKING:
    from collections.abc import Sequence


def _entries() -> dict[str, dict[str, object]]:
    """``references.toml`` as committed in this checkout, keyed by film name."""
    path = dataroot.REPO_ROOT / parity_layout.REFERENCES_FILE
    if not path.is_file():
        return {}
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return {name: entry for name, entry in document.items() if isinstance(entry, dict)}


def report(slug: str, run: str, digest: str, *, promotable: bool = True) -> list[str]:
    """The lines printed for capture *run* of *slug* hashing to *digest*.

    *promotable* is false for a directory that is not where parity reads that capture: an
    entry naming it would point parity at a different directory, so none is printed.
    """
    lines = [f"{parity_layout.frames_path(slug, run).as_posix()}", f'sha256 = "{digest}"']
    if not promotable:
        return [
            *lines,
            "# not this checkout's capture directory for that id, so no references.toml entry",
        ]
    for name, entry in _entries().items():
        if entry.get("film") != slug:
            continue
        if entry.get("capture") == run and entry.get("sha256") == digest:
            lines.append(f"[{name}] already names this capture with this hash")
            continue
        lines += [
            "",
            f"# references.toml names {entry.get('capture')} for [{name}]; to promote {run}:",
            f"[{name}]",
            f'film = "{slug}"',
            f'capture = "{run}"',
            f'sha256 = "{digest}"',
        ]
    return lines


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("film", nargs="?", help="film slug, e.g. vault-ctry")
    parser.add_argument("run", nargs="?", help="run id under captures/<film>/frames/, e.g. 005")
    parser.add_argument("--dir", type=Path, help="a capture directory instead of film and run")
    args = parser.parse_args(argv)

    promotable = True
    if args.dir is not None:
        directory = args.dir.resolve()
        slug, run = directory.parent.parent.name, directory.name
        # Parity reads captures through the checkout's data-root link; a copy elsewhere with
        # the same name is not the directory a references.toml entry would name.
        canonical = (dataroot.REPO_ROOT / parity_layout.frames_path(slug, run)).resolve()
        promotable = directory == canonical
    elif args.film and args.run:
        slug = parity_layout.require_slug(args.film)
        run = str(args.run)
        if root is None:
            if not dataroot.ensure_links_or_report("capture_digest"):
                return 1
            root = dataroot.REPO_ROOT
        directory = root / parity_layout.frames_path(slug, run)
    else:
        parser.error("name a film slug and a run id, or --dir")

    if not (directory / "meta.json").is_file():
        print(f"{directory} is not a capture (no meta.json)", file=sys.stderr)
        return 1
    for line in report(slug, run, references.capture_digest(directory), promotable=promotable):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
