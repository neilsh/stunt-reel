"""One-command parity baseline: render both films and print the headline scores.

Runs the release binary over every captured tick of each film, scores the render against its
capture with ``stuntreel parity``, and prints one line per film plus the adoption noise note.
``build/parity/ours/<film>_current`` and ``build/parity/report/<film>_current`` are the
canonical baseline directories.

Usage::

    mise run parity -- [--films ctry,intro] [--no-build] [--no-render]
        [--reuse DIR] [--retime N] [--data-root DIR]

``--no-build`` reuses the existing release binary; ``--no-render`` scores the existing
``_current`` render tree; ``--reuse DIR`` scores ``DIR/<film>`` instead; ``--retime N``
relabels that tree by N ticks (see ``parity_probe.py retime``) and scores the copy, writing a
``_retime<N>`` report so the baseline report is not overwritten. Progress goes to stderr;
stdout carries only the summary lines and the noise note.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from parity_probe import retime_render
from parity_sweep import (
    FILMS,
    REPO_ROOT,
    build_release,
    check_film,
    format_summary,
    preflight,
    render_film,
    score_dir,
)

from stunt_reel.dataroot import SharedDataError, ensure_links

OURS = REPO_ROOT / "build" / "parity" / "ours"
REPORT = REPO_ROOT / "build" / "parity" / "report"
SCRATCH = REPO_ROOT / "build" / "scratch" / "parity"
RETIME_SCRATCH = REPO_ROOT / "build" / "scratch" / "retime"
#: Adoption floor; a margin under it is not attributable to a change (probes.md section 6).
NOISE_NOTE = "noise floor +/-0.002 SSIM; margin below 0.002 is not an adoption"


def prepare_source(film: str, root: Path, args: argparse.Namespace) -> Path:
    """The render directory to score: reused, existing, or freshly rendered ``_current``."""
    current = OURS / f"{film}_current"
    if args.reuse is not None:
        source = Path(args.reuse) / film
        if not source.is_dir():
            raise ValueError(f"{source} is not a render directory")
        return source
    if args.no_render:
        if not current.is_dir():
            raise ValueError(
                f"{current} is missing; run `mise run parity` without --no-render first"
            )
        return current
    print(f"[parity] rendering {film} into {current}", file=sys.stderr)
    scratch = SCRATCH / film
    shutil.rmtree(scratch, ignore_errors=True)
    render_film(FILMS[film], root, scratch, None)
    check_film(FILMS[film], root, scratch)
    current.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(current, ignore_errors=True)
    shutil.move(str(scratch), str(current))
    return current


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--films", default=",".join(FILMS), help="comma list; default: all")
    parser.add_argument("--no-build", action="store_true", help="reuse the release binary")
    parser.add_argument("--no-render", action="store_true", help="score the existing _current dirs")
    parser.add_argument(
        "--reuse", type=Path, default=None, help="score DIR/<film> instead of _current"
    )
    parser.add_argument(
        "--retime", type=int, default=None, metavar="N", help="score each film relabelled by N"
    )
    parser.add_argument("--data-root", type=Path, default=REPO_ROOT, help="holds corpus/, captures")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    films = [f.strip() for f in args.films.split(",") if f.strip()]
    unknown = [f for f in films if f not in FILMS]
    if unknown or not films:
        print(
            f"parity_run: --films must be from {', '.join(FILMS)}, got {args.films!r}",
            file=sys.stderr,
        )
        return 2
    root: Path = args.data_root.resolve()
    if root == REPO_ROOT:
        try:
            for relative in ensure_links():
                print(f"[parity] linked {relative}", file=sys.stderr)
        except SharedDataError as err:
            print(f"parity_run: {err}", file=sys.stderr)
            return 2
    problems = preflight(root, films, build_required=not args.no_build)
    if problems:
        print("parity_run: " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if not args.no_build:
        print("[parity] cargo build --release -p stunt-cli", file=sys.stderr)
        try:
            build_release()
        except RuntimeError as err:
            print(f"parity_run: build failed: {err}", file=sys.stderr)
            return 1

    failures = 0
    for film in films:
        try:
            source = prepare_source(film, root, args)
            check_film(FILMS[film], root, source)
            scored = source
            suffix = ""
            if args.retime is not None:
                suffix = f"_retime{args.retime:+d}"
                retimed = RETIME_SCRATCH / f"{film}_current{suffix}"
                shutil.rmtree(retimed, ignore_errors=True)
                result = retime_render(
                    source,
                    root / FILMS[film].reference,
                    retimed,
                    args.retime,
                    force=True,
                    allow_missing=True,
                )
                print(
                    f"[parity] {film}: copied {result.copied} frames; "
                    f"missing {len(result.missing)} ticks",
                    file=sys.stderr,
                )
                scored = retimed
            report = REPORT / f"{film}_current{suffix}"
            score_dir(FILMS[film], root, scored, report, "film")
            print(format_summary(film, report), flush=True)
        except (RuntimeError, ValueError, OSError, KeyError) as err:
            failures += 1
            print(
                f"parity_run: {film} FAILED ({str(err).splitlines()[0][:120]})",
                file=sys.stderr,
            )
    print(NOISE_NOTE)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
