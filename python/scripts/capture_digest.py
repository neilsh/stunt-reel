"""Print a capture's content hash and the ``references.toml`` entry that would promote it.

Every promotion of a reference capture needs the ``sha256`` that
:func:`stunt_reel.references.capture_digest` computes, and there was no command for it. This
prints that hash for a film's capture, read from the data root (ADR 0036), and,
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
from typing import TYPE_CHECKING
lazy from pathlib import Path

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


#: Stands for a build that a record names but that is not a known one, or that the record cannot
#: vouch for; ``references.toml`` refuses it, so a pasted row fails until a person names one.
UNKNOWN = "?"


def _read_meta(path: Path) -> dict[str, object]:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return meta if isinstance(meta, dict) else {}


def recorded_builds(root: Path, slug: str, directory: Path) -> dict[str, str]:
    """The builds the film's capture and stored archive record, as ``references.toml`` names them.

    ``playone`` comes from the capture's ``meta.json`` (``playone_build``) and ``makeone`` from
    the stored archive's ``makeone_sha256``. A field with no record is left out. A record that
    names no known build is ``UNKNOWN``, and so is ``makeone`` when the capture played another
    archive than the stored one (their ``all_sha256`` differ).
    """
    found: dict[str, str] = {}
    meta = _read_meta(directory / capture_store.META_FILE)
    if "playone_build" in meta:
        build = meta["playone_build"]
        found["playone"] = (
            build if isinstance(build, str) and build in references.BUILD_NAMES else UNKNOWN
        )
    stored = capture_store.current(root / parity_layout.archive_path(slug))
    if stored is not None:
        archive = _read_meta(stored / capture_store.META_FILE)
        if "makeone_sha256" in archive:
            played, kept = meta.get("all_sha256"), archive.get("all_sha256")
            if played and kept and played != kept:
                found["makeone"] = UNKNOWN
            else:
                build = references.MAKEONE_BUILDS.get(str(archive["makeone_sha256"]))
                found["makeone"] = build or UNKNOWN
    return found


def report(
    slug: str, digest: str, *, promotable: bool = True, builds: dict[str, str] | None = None
) -> list[str]:
    """The lines printed for the capture of *slug* hashing to *digest*.

    *promotable* is false for a directory that is not where parity reads the film's capture: an
    entry pinning it would point parity at a different directory, so none is printed. *builds*
    are the builds the capture records; for a field it lacks, the row's own value is kept, and
    when neither names a known one the line holds ``"?"``, which ``references.toml`` refuses until
    a person names the build, because an omitted one would be read as patch3 (ADR 0029).
    """
    builds = builds or {}
    lines = [f"{parity_layout.frames_path(slug).as_posix()}", f'sha256 = "{digest}"']
    if not promotable:
        return [
            *lines,
            "# not the data root's capture directory for that film, so no references.toml entry",
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
        chosen = {f: builds[f] if f in builds else entry.get(f) for f in ("makeone", "playone")}
        for field, build in chosen.items():
            if build in references.BUILD_NAMES:
                lines.append(f'{field} = "{build}"')
            else:
                # An active "?", not a comment: an omitted build would be read as patch3.
                why = "its record names no known build" if field in builds else "nothing records it"
                lines.append(f'{field} = "{UNKNOWN}"  # {why}; name unpatched or patch3')
        if "unpatched" in chosen.values():
            reason = str(entry.get("reason", "why this film needs the unpatched build"))
            # A JSON string is a valid TOML basic string, so quotes and backslashes survive.
            lines.append(f"reason = {json.dumps(reason, ensure_ascii=False)}")
    return lines


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("film", nargs="?", help="film slug, e.g. vault-ctry")
    parser.add_argument(
        "--dir", type=dataroot.data_path_arg, help="a capture directory instead of a film slug"
    )
    args = parser.parse_args(argv)

    promotable = True
    if root is None:
        root = dataroot.data_root()
    if args.dir is not None:
        directory = args.dir.resolve()
        slug = directory.parent.name
        # Parity reads captures from the data root; a copy elsewhere is not the directory a
        # references.toml entry would pin.
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
