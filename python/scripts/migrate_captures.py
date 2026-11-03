"""Move the captures to one of each kind per film (ADR 0028), keeping only the pinned references.

Under the numbered layout a film's captures were ``captures/<film>/<kind>/<run>/``. Now a film
has one of each kind, ``captures/<film>/<kind>/``. Each pinned reference in
``research/parity/references.toml`` is the run of its film's frames whose content hashes to the
pin; it moves up to become the film's frame capture, unchanged, so its digest still matches and
no baseline moves. Every other run, of every kind and film, is deleted; a batch survey under the
new rules recaptures and re-archives them.

A pin that matches no run stops the migration before anything is deleted. A kind directory
that already holds ``meta.json`` is in the new layout and is left alone, so a second run changes
nothing. Dry run unless ``--yes``.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import capture_store, dataroot, parity_layout, references

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The kinds a film's directory holds, one each (ADR 0028).
KINDS = ("frames", "video", "archives")
#: The suffix a kind directory carries while its pinned run moves up out of it.
_HELD = ".migrating"
#: A run directory of the numbered layout, and its ``.lock`` / ``.partial`` siblings.
_RUN = re.compile(r"\d+(?:\..*)?")


class MigrationError(RuntimeError):
    """A pinned reference that is not on this machine, or a directory the migration cannot read."""


def read_pins(path: Path) -> dict[str, str]:
    """Film slug -> pinned digest of its reference, from a ``references.toml``."""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        entry["film"]: entry["sha256"]
        for entry in document.values()
        if isinstance(entry, dict) and "film" in entry and "sha256" in entry
    }


def _pinned_run(directory: Path, pin: str) -> Path:
    """The complete run in *directory* whose content hashes to *pin*."""
    for run in sorted(item for item in directory.iterdir() if _RUN.fullmatch(item.name)):
        if capture_store.current(run) is not None and references.capture_digest(run) == pin:
            return run
    raise MigrationError(f"no run in {directory} hashes to its pin; nothing was changed")


def migrate(root: Path, pins: Mapping[str, str], *, apply: bool) -> list[str]:
    """Plan the migration of *root*'s captures, make it when *apply*, and return one line per step.

    *pins* maps a film slug to the digest of its reference capture. Every pin is matched before
    anything moves or is deleted.
    """
    captures = root / parity_layout.capture_root().name
    keep: list[tuple[Path, Path]] = []
    drop: list[Path] = []
    notes: list[str] = []
    films = (
        sorted(item for item in captures.iterdir() if item.is_dir()) if captures.is_dir() else []
    )
    for film in films:
        for name in sorted(item.name for item in film.iterdir()):
            kind = film / name
            if name.endswith(_HELD):
                target = film / name.removesuffix(_HELD)
                raise MigrationError(
                    f"{kind} is left from an interrupted migration. The pinned run is either "
                    f"still inside it or already at {target}: check which one hashes to the pin "
                    f"(mise run capture-digest), move it to {target} if needed, delete {kind}, "
                    "then rerun"
                )
            if name not in KINDS or not kind.is_dir():
                notes.append(f"skip {kind.relative_to(root).as_posix()}: not a capture kind")
            elif capture_store.current(kind) is None:
                strays = [item.name for item in kind.iterdir() if not _RUN.fullmatch(item.name)]
                if strays:
                    raise MigrationError(
                        f"{kind} holds {', '.join(sorted(strays))}, which is not a numbered run; "
                        "move it out by hand; nothing was changed"
                    )
                pin = pins.get(film.name) if name == "frames" else None
                if pin is not None:
                    keep.append((_pinned_run(kind, pin), kind))
                else:
                    drop.append(kind)
    for film in films:
        if film.name in pins and not (film / "frames").is_dir():
            raise MigrationError(
                f"{film} has no frames directory, so its pinned reference is not on this machine; "
                "nothing was changed"
            )
    for film_name in sorted(set(pins) - {film.name for film in films}):
        notes.append(f"pinned film {film_name} has no captures on this machine")

    verb = "" if apply else "would "
    lines = [
        f"{verb}keep {run.relative_to(root).as_posix()} as {kind.relative_to(root).as_posix()}"
        for run, kind in keep
    ]
    lines += [f"{verb}delete {kind.relative_to(root).as_posix()}" for kind in drop]
    if apply:
        for run, kind in keep:
            held = kind.with_name(f"{kind.name}{_HELD}")
            kind.rename(held)
            (held / run.name).rename(kind)
            shutil.rmtree(held)
        for kind in drop:
            shutil.rmtree(kind)
        for film in films:
            if film.is_dir() and not any(film.iterdir()):
                film.rmdir()
    return [*lines, *notes]


def main() -> int:
    """Run the migration against the shared data root."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root", type=Path, default=None, help="data root (default: the shared one)"
    )
    parser.add_argument("--yes", action="store_true", help="move and delete (default: dry run)")
    args = parser.parse_args()
    root = dataroot.data_root() if args.root is None else args.root
    pins = read_pins(dataroot.REPO_ROOT / parity_layout.REFERENCES_FILE)
    try:
        for line in migrate(root, pins, apply=args.yes):
            print(f"[migrate] {line}")
    except MigrationError as exc:
        print(f"[migrate] {exc}", file=sys.stderr)
        return 1
    if not args.yes:
        print("[migrate] dry run; add --yes to keep the pinned references and delete the rest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
