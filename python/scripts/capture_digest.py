"""Print a capture's content hash and the ``references.toml`` entry that would promote it.

Every promotion of a reference capture needs the ``sha256`` that
:func:`stunt_reel.references.capture_digest` computes, and there was no command for it. This
prints that hash for a film's capture, read through this checkout's link to the data root, and,
when ``references.toml`` has an entry for the capture's film, the replacement entry to paste
in a reviewed commit, with the capture the entry names now. It writes nothing; promoting
stays an edit of ``research/parity/references.toml`` (ADR 0029).

Usage: ``mise run capture-digest -- vault-ctry`` (film slug), or
``mise run capture-digest -- --dir <capture directory>``.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import capture_store, dataroot, parity_layout, references

if TYPE_CHECKING:
    from collections.abc import Sequence


def _entries() -> dict[str, dict[str, object]]:
    """``references.toml`` as committed in this checkout, keyed by film name."""
    path = dataroot.REPO_ROOT / parity_layout.REFERENCES_FILE
    if not path.is_file():
        return {}
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return {name: entry for name, entry in document.items() if isinstance(entry, dict)}


def recorded_builds(root: Path, slug: str, directory: Path) -> dict[str, str]:
    """The builds the film's capture and stored archive record, as ``references.toml`` names them.

    ``playone`` comes from the capture's ``meta.json`` (``playone_build``) and ``makeone`` from
    the archive's ``makeone_sha256``; a field whose record is absent or unknown is left out.
    """
    found: dict[str, str] = {}
    try:
        meta = json.loads((directory / capture_store.META_FILE).read_text(encoding="utf-8"))
        build = meta.get("playone_build")
        if build in references.BUILD_NAMES:
            found["playone"] = build
    except OSError, ValueError, AttributeError:
        pass
    stored = capture_store.current(root / parity_layout.archive_path(slug))
    if stored is not None:
        try:
            archive = json.loads((stored / capture_store.META_FILE).read_text(encoding="utf-8"))
            build = references.MAKEONE_BUILDS.get(str(archive.get("makeone_sha256", "")))
        except OSError, ValueError, AttributeError:
            build = None
        if build is not None:
            found["makeone"] = build
    return found


def report(
    slug: str, digest: str, *, promotable: bool = True, builds: dict[str, str] | None = None
) -> list[str]:
    """The lines printed for the capture of *slug* hashing to *digest*.

    *promotable* is false for a directory that is not where parity reads the film's capture: an
    entry pinning it would point parity at a different directory, so none is printed. *builds*
    are the builds the capture records; for a field it lacks, the row's own value is kept, and
    when neither names one the line says so, because a row must name both (ADR 0029).
    """
    builds = builds or {}
    lines = [f"{parity_layout.frames_path(slug).as_posix()}", f'sha256 = "{digest}"']
    if not promotable:
        return [
            *lines,
            "# not this checkout's capture directory for that film, so no references.toml entry",
        ]
    for name, entry in _entries().items():
        if entry.get("film") != slug:
            continue
        if entry.get("sha256") == digest:
            lines.append(f"[{name}] already pins this capture")
            continue
        lines += [
            "",
            f"# references.toml pins another capture for [{name}]; to promote this one:",
            f"[{name}]",
            f'film = "{slug}"',
            f'sha256 = "{digest}"',
        ]
        chosen = {f: builds.get(f) or entry.get(f) for f in ("makeone", "playone")}
        for field, build in chosen.items():
            lines.append(
                f'{field} = "{build}"'
                if build in references.BUILD_NAMES
                else f"# {field} = ?  (the capture does not record it; name unpatched or patch3)"
            )
        if "unpatched" in chosen.values():
            reason = str(entry.get("reason", "why this film needs the unpatched build"))
            # A JSON string is a valid TOML basic string, so quotes and backslashes survive.
            lines.append(f"reason = {json.dumps(reason, ensure_ascii=False)}")
    return lines


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("film", nargs="?", help="film slug, e.g. vault-ctry")
    parser.add_argument("--dir", type=Path, help="a capture directory instead of a film slug")
    args = parser.parse_args(argv)

    promotable = True
    # Parity repairs a missing or stale data-root link before it reads a capture, so do the same
    # first: the --dir comparison and the film path both go through that link.
    if root is None:
        if not dataroot.ensure_links_or_report("capture_digest"):
            return 1
        root = dataroot.REPO_ROOT
    if args.dir is not None:
        directory = args.dir.resolve()
        slug = directory.parent.name
        # Parity reads captures through the checkout's data-root link; a copy elsewhere is not
        # the directory a references.toml entry would pin.
        promotable = directory == (root / parity_layout.frames_path(slug)).resolve()
    elif args.film:
        slug = parity_layout.require_slug(args.film)
        directory = root / parity_layout.frames_path(slug)
    else:
        parser.error("name a film slug, or --dir")

    if capture_store.current(directory) is None:
        print(f"{directory} is not a capture (no meta.json)", file=sys.stderr)
        return 1
    builds = recorded_builds(root, slug, directory)
    for line in report(
        slug, references.capture_digest(directory), promotable=promotable, builds=builds
    ):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
