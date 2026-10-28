"""One-command parity baseline: render both films and print the headline scores.

Runs the release binary over every captured tick of each film, scores the render against its
capture with ``stuntreel parity``, and prints one line per film plus the adoption noise note.
The latest render and report are the ``_current`` trees that ``stunt_reel.parity_layout``
names. Before a render replaces the tree, it is renamed to that film's previous render (one
per film, by rename, so no bytes are copied), and the re-score command is printed: any render
can be compared later with ``--reuse`` on the previous root.

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

from cli import ParityOptions, UsageError, add_parity_options, parity_options

from stunt_reel import parity_layout
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.parity_pipeline import (
    FILMS,
    REPO_ROOT,
    Retime,
    build_release,
    check_film,
    format_summary,
    preflight,
    render_film,
    score_film,
)

#: Adoption floor; a margin under it is not attributable to a change (probes.md section 6).
NOISE_NOTE = "noise floor +/-0.002 SSIM; margin below 0.002 is not an adoption"


def prepare_source(film: str, root: Path, options: ParityOptions, *, no_render: bool) -> Path:
    """The render directory to score: reused, existing, or freshly rendered ``_current``."""
    current = REPO_ROOT / parity_layout.render_dir(film)
    if options.reuse is not None:
        return Path(options.reuse) / film
    if no_render:
        if not current.is_dir():
            raise ValueError(
                f"{current} is missing; run `mise run parity` without --no-render first"
            )
        return current
    print(f"[parity] rendering {film} into {current}", file=sys.stderr)
    scratch = REPO_ROOT / parity_layout.render_scratch_dir(film)
    shutil.rmtree(scratch, ignore_errors=True)
    render_film(film, root, scratch, None)
    check_film(film, root, scratch)
    current.parent.mkdir(parents=True, exist_ok=True)
    # Rename rather than copy: the previous tree stays scoreable with --reuse and the
    # render directories are hundreds of megabytes, so a copy per run is not affordable.
    previous = REPO_ROOT / parity_layout.previous_dir(film)
    if current.is_dir():
        previous.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(previous, ignore_errors=True)
        shutil.move(str(current), str(previous))
        print(
            f"[parity] previous {film} render kept at {previous}; re-score it with "
            f"mise run parity -- --films {film} --no-build --reuse {previous.parent}",
            file=sys.stderr,
        )
    shutil.move(str(scratch), str(current))
    return current


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_parity_options(parser, films=FILMS, data_root=REPO_ROOT)
    parser.add_argument("--no-render", action="store_true", help="score the existing _current dirs")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        options = parity_options(args, films=FILMS)
    except UsageError as err:
        print(f"parity_run: {err}", file=sys.stderr)
        return 2
    root = options.data_root
    if root == REPO_ROOT and not ensure_links_or_report("parity_run"):
        return 2
    problems = preflight(root, list(options.films), build_required=not options.no_build)
    if problems:
        print("parity_run: " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if not options.no_build:
        print("[parity] cargo build --release -p stunt-cli", file=sys.stderr)
        try:
            build_release()
        except RuntimeError as err:
            print(f"parity_run: build failed: {err}", file=sys.stderr)
            return 1

    failures = 0
    for film in options.films:
        try:
            source = prepare_source(film, root, options, no_render=args.no_render)
            suffix = ""
            request = None
            if options.retime is not None:
                suffix = f"_retime{options.retime:+d}"
                request = Retime(options.retime, REPO_ROOT / parity_layout.retime_dir(film, suffix))
            report = REPO_ROOT / parity_layout.report_dir(film, suffix)
            result = score_film(film, root, source, report, retime=request)
            if result.retime is not None:
                print(
                    f"[parity] {film}: copied {result.retime.copied} frames; "
                    f"missing {len(result.retime.missing)} ticks",
                    file=sys.stderr,
                )
            print(format_summary(film, result.report), flush=True)
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
