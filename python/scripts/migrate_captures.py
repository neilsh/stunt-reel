"""Move the existing captures into the film-first layout (ADR 0024).

``captures/<film>/<id>`` becomes ``captures/vault-<film>/frames/001`` and
``captures/all/<film>/<id>`` becomes ``captures/vault-<film>/archives/001``.  A frame capture's
numbered files move under ``frames/`` and its ``meta.json`` names follow, with ``captured_on``
and ``checkout`` read from the old id.  Each capture is copied to a ``.partial`` sibling, checked
file by file against the original and renamed into place before the original is deleted, so an
interrupted run loses nothing and a second run changes nothing.  Dry run unless ``--yes``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import dataroot, parity_layout, references
from stunt_reel.parity_artifacts import CAPTURE_FRAMES_DIR

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The films that were captured before the layout named them by source: all are in ``VAULT/``.
VAULT_FILMS = ("ctry", "intro", "balloon", "traintnl")
_FIRST_RUN = parity_layout.run_id(1)
_NUMBERED = re.compile(r"(tick_\d+\.idx|palettes_\d+\.json)")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class MigrationError(RuntimeError):
    """A capture that is not what the pins say it is, or did not copy intact."""


def _relative(path: Path) -> Path:
    """*path* from :mod:`parity_layout` (checkout-relative) as a data-root-relative path."""
    return path.relative_to(parity_layout.capture_root().parent)


def _manifest(directory: Path) -> dict[str, str]:
    """Relative POSIX path -> SHA-256 of every file under *directory*."""
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _provenance(old_id: str) -> dict[str, str]:
    """``captured_on`` and ``checkout`` as far as the old id ``<date>-<checkout>-<hash>`` says."""
    found = _DATE.search(old_id)
    if found is None:
        return {}
    result = {"captured_on": found.group()}
    if old_id.startswith(found.group() + "-"):
        middle = old_id[len(found.group()) + 1 :].rsplit("-", 1)
        if len(middle) == 2 and middle[0]:
            result["checkout"] = middle[0]
    return result


def _rewrite_meta(text: str, old_id: str) -> str:
    """The ``meta.json`` text with frame names under ``frames/`` and provenance added."""
    meta = json.loads(text)
    for frame in meta.get("frames", []):
        for key in ("frame_file", "palette_file"):
            name = frame.get(key)
            if name and "/" not in name:
                frame[key] = f"{CAPTURE_FRAMES_DIR}/{name}"
    for key, value in _provenance(old_id).items():
        meta.setdefault(key, value)
    return json.dumps(meta, indent=2) + "\n"


def _copy_frames(source: Path, partial: Path) -> None:
    """Copy a frame capture to *partial*: numbered files under ``frames/``, meta rewritten."""
    (partial / CAPTURE_FRAMES_DIR).mkdir(parents=True)
    for path in sorted(source.iterdir()):
        if path.name == "meta.json":
            continue
        if not (path.is_file() and _NUMBERED.fullmatch(path.name)):
            raise MigrationError(f"{path} is not part of a frame capture; move it by hand")
        shutil.copy2(path, partial / CAPTURE_FRAMES_DIR / path.name)
    meta = _rewrite_meta((source / "meta.json").read_text(encoding="utf-8"), source.name)
    (partial / "meta.json").write_text(meta, encoding="utf-8")


def _move(source: Path, target: Path, *, frames: bool) -> None:
    """Copy *source* to *target* through ``<target>.partial``, verify every file, delete *source*.

    For a frame capture every file but the rewritten ``meta.json`` must come out byte for byte,
    renamed into ``frames/``; an archive must come out identical.
    """
    partial = target.with_name(target.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    before = _manifest(source)
    if frames:
        _copy_frames(source, partial)
        expected = {
            f"{CAPTURE_FRAMES_DIR}/{name}": digest
            for name, digest in before.items()
            if name != "meta.json"
        }
        after = _manifest(partial)
        after.pop("meta.json")
    else:
        shutil.copytree(source, partial)
        expected, after = before, _manifest(partial)
    if after != expected:
        shutil.rmtree(partial)
        raise MigrationError(f"{source} did not copy byte for byte; the original is untouched")
    partial.rename(target)
    shutil.rmtree(source)


def _only_run(directory: Path) -> Path | None:
    """The single run directory inside *directory*, or ``None`` when there is not exactly one."""
    runs = [item for item in directory.iterdir() if item.is_dir()]
    return runs[0] if len(runs) == 1 else None


def migrate(root: Path, pins: Mapping[str, str], *, apply: bool) -> list[str]:
    """Plan the moves under *root*, make them when *apply*, and return one line per item.

    *pins* maps a film to the digest its old frame capture must have; a mismatch raises
    :class:`MigrationError` before anything moves.
    """
    captures = root / _relative(parity_layout.capture_root())
    plan: list[tuple[str, Path, Path, bool]] = []
    notes: list[str] = []
    for film in VAULT_FILMS:
        slug = f"vault-{film}"
        for base, destination, frames in (
            (captures / film, parity_layout.frames_path(slug, _FIRST_RUN), True),
            (captures / "all" / film, parity_layout.archive_path(slug, _FIRST_RUN), False),
        ):
            if not base.is_dir():
                continue
            source = _only_run(base)
            target = root / _relative(destination)
            if source is None:
                notes.append(f"skip {base}: not exactly one run; move it by hand")
            elif target.exists():
                notes.append(f"skip {source}: {target} already exists")
            else:
                plan.append((film, source, target, frames))
    for film, source, _target, frames in plan:
        if frames and film in pins and references.capture_digest(source) != pins[film]:
            raise MigrationError(
                f"{source} no longer hashes to its pin in references.toml; nothing was moved"
            )
    lines = [
        f"{'move' if apply else 'would move'} {source.relative_to(root).as_posix()} -> "
        f"{target.relative_to(root).as_posix()}"
        for _film, source, target, _frames in plan
    ]
    if apply:
        for _film, source, target, frames in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            parents = (source.parent, source.parent.parent)
            _move(source, target, frames=frames)
            for leftover in parents:
                if leftover != captures and leftover.is_dir() and not any(leftover.iterdir()):
                    leftover.rmdir()
    return [*lines, *notes]


def read_pins(path: Path) -> dict[str, str]:
    """Film -> pinned digest from a ``references.toml``."""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return {film: entry["sha256"] for film, entry in document.items() if "sha256" in entry}


def write_pins(path: Path, root: Path) -> list[str]:
    """Point each ``references.toml`` entry at run ``001`` of its slug, with that digest."""
    text = path.read_text(encoding="utf-8")
    lines: list[str] = []
    for film, entry in tomllib.loads(text).items():
        digest = references.capture_digest(
            root / _relative(parity_layout.frames_path(entry["film"], _FIRST_RUN))
        )
        section = re.compile(
            rf'(\[{re.escape(film)}\]\n[^\[]*?capture = )"[^"]*"(\nsha256 = )"[^"]*"'
        )
        text, count = section.subn(rf'\g<1>"{_FIRST_RUN}"\g<2>"{digest}"', text)
        if count != 1:
            raise MigrationError(f"{path}: cannot rewrite the [{film}] entry")
        lines.append(f'pin {film}: capture = "{_FIRST_RUN}" sha256 = "{digest}"')
    path.write_text(text, encoding="utf-8")
    return lines


def main() -> int:
    """Run the migration against the shared data root."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root", type=Path, default=None, help="data root (default: the shared one)"
    )
    parser.add_argument("--yes", action="store_true", help="make the moves (default: dry run)")
    parser.add_argument(
        "--write-pins", action="store_true", help="re-pin research/parity/references.toml"
    )
    args = parser.parse_args()
    root = dataroot.data_root() if args.root is None else args.root
    pointers = dataroot.REPO_ROOT / parity_layout.REFERENCES_FILE
    try:
        for line in migrate(root, read_pins(pointers), apply=args.yes):
            print(f"[migrate] {line}")
        if args.write_pins and args.yes:
            for line in write_pins(pointers, root):
                print(f"[migrate] {line}")
    except MigrationError as exc:
        print(f"[migrate] {exc}", file=sys.stderr)
        return 1
    if not args.yes:
        print("[migrate] dry run; add --yes to move and --write-pins to re-pin references.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
