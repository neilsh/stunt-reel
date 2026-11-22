"""One-command parity baseline: render every reference film and print the headline scores.

Runs the release binary over every captured tick of each film, scores the render against its
capture with ``stuntreel parity``, and prints each film's line, the film's expected score under
it, and the adoption noise note.
The latest render and report are the ``_current`` trees that ``stunt_reel.parity_layout``
names. Before a render replaces the tree, it is renamed to that film's previous render (one
per film, by rename, so no bytes are copied), and the re-score command is printed: any render
can be compared later with ``--reuse`` on the previous root.

Usage::

    mise run parity -- [--films ctry,intro] [--no-build] [--no-render]
        [--reuse DIR] [--retime N] [--software-only] [--data-root DIR]

``--no-build`` reuses the existing release binary; ``--no-render`` scores the existing
``_current`` render tree; ``--reuse DIR`` scores ``DIR/<film>`` instead; ``--retime N``
relabels that tree by N ticks (see ``parity_probe.py retime``) and scores the copy, writing a
``_retime<N>`` report so the baseline report is not overwritten. Progress goes to stderr;
stdout carries only each film's summary line, under it the comparison with the film's expected
score for the renderer class it rendered on (``stunt_reel.expected_scores``: the delta, and
drift only when the scores compare), and the noise note. A run that builds and renders on a
clean ``crates/`` records that tree in each report (``crates``), which ``mise run parity-repin``
requires. So does a ``--no-render`` run on a clean ``crates/`` whose render records, beside its
frames (``crates-tree.txt``), a build tree that differs from this one only under the scorer
(``stunt_reel.expected_scores.SCORER_DIR``), since no pixel of the render it scores has moved;
any other run records null, and a render made without a clean build records none. Every report also records the reference pins it was scored
against (``sha256``, ``all_sha256``), which ``parity-repin`` checks against the film's row.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
lazy from collections.abc import Callable

from cli import (
    DEFAULT_JOBS,
    ParityOptions,
    UsageError,
    add_parity_options,
    parity_options,
    positive_int,
    resolve_jobs,
)

from stunt_reel import parity_layout
from stunt_reel.expected_scores import (
    clean_crates_tree,
    comparison_line,
    read_render_tree,
    renderer_changes,
    scorer_only_change,
    write_render_tree,
)
from stunt_reel.parity_artifacts import read_report
from stunt_reel.parity_pipeline import (
    REPO_ROOT,
    FilmFailure,
    FilmJob,
    FilmScore,
    RenderBudget,
    Retime,
    build_release,
    captured_ticks,
    check_film,
    format_summary,
    physical_memory,
    preflight,
    render_budget,
    render_film,
    run_matrix,
    score_film,
)
from stunt_reel.references import read_reference

#: Adoption floor; a margin under it is not attributable to a change (probes.md section 6).
NOISE_NOTE = "noise floor +/-0.002 SSIM; margin below 0.002 is not an adoption"


def prepare_source(
    job: FilmJob,
    options: ParityOptions,
    *,
    no_render: bool,
    software_only: bool,
    built_from: str | None = None,
    workers: int = 1,
) -> Path:
    """The render directory to score: reused, existing, or freshly rendered ``_current``.

    A fresh render records *built_from*, the ``crates/`` tree its binary was built from (``None``
    when unknown), inside the directory, replacing any record of the render it displaces.
    *workers* above 1 renders it in that many ``stuntreel --workers`` processes.
    """
    film = job.name
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
    render_film(job, scratch, software_only=software_only, workers=workers)
    check_film(job, scratch)
    write_render_tree(scratch, built_from)
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


def rescored_with(options: ParityOptions) -> str | None:
    """The flag that made the run score a tree other than this checkout's render, else ``None``."""
    if options.retime is not None:
        return "--retime"
    if options.reuse is not None:
        return "--reuse"
    return None


def recorded_crates(
    *,
    no_build: bool,
    rescored: bool,
    tree: Callable[[], str | None] = clean_crates_tree,
) -> str | None:
    """The ``crates/`` tree a run may record: *tree*'s, only when the binary was built now.

    For a fresh render it is the tree the reports record.  For ``--no-render`` it is only a
    candidate, which :func:`scored_render_tree` confirms film by film.  ``None`` when the binary
    was not built now (``--no-build``), another tree is scored (``--reuse``, ``--retime``), or
    ``crates/`` is dirty.
    """
    if no_build or rescored:
        return None
    return tree()


def scored_render_tree(
    candidate: str | None,
    render: Path,
    *,
    no_render: bool,
    scorer_only: Callable[[str, str], bool] = scorer_only_change,
) -> str | None:
    """The ``crates/`` tree one film's report records, given :func:`recorded_crates`'s *candidate*.

    A fresh render records *candidate*.  A ``--no-render`` run records it only when the tree
    recorded inside *render* (:func:`stunt_reel.expected_scores.read_render_tree`), the one that
    made its frames, is known and differs from *candidate* only under the scorer, so a renderer
    change still needs a re-render.
    """
    if not no_render or candidate is None:
        return candidate
    built = read_render_tree(render)
    if built is None or not scorer_only(built, candidate):
        return None
    return candidate


def unrecorded_reason(
    candidate: str,
    render: Path,
    *,
    changes: Callable[[str, str], list[str] | None] = renderer_changes,
) -> str:
    """Why a ``--no-render`` run records no tree for *render* although *candidate* is clean.

    Call it only when :func:`scored_render_tree` returned ``None`` for *candidate*.
    """
    built = read_render_tree(render)
    if built is None:
        return "the render records no build tree"
    paths = changes(built, candidate)
    if not paths:
        return f"git cannot compare the render's tree {built[:7]} with crates/"
    more = f" and {len(paths) - 1} more" if len(paths) > 1 else ""
    return f"crates/{paths[0]}{more} changed outside the scorer since the render"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_parity_options(parser)
    parser.add_argument("--no-render", action="store_true", help="score the existing _current dirs")
    parser.add_argument(
        "--software-only",
        action="store_true",
        help="render on the software adapter (lavapipe), even when a GPU is available",
    )
    parser.add_argument(
        "--workers",
        type=positive_int,
        default=1,
        metavar="N",
        help=(
            "render each film in up to N stuntreel processes (LP_NUM_THREADS=1 each), cut so "
            "jobs x workers fits the cores and about 0.93 GiB of RAM per process; default 1"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Renders and scores the chosen films, *jobs* at a time; 0 when every film scored, else 1.

    A refused invocation or a failed preflight exits 2 before any render.
    """
    args = parse_args(argv)
    try:
        options = parity_options(args)
    except UsageError as err:
        print(f"parity_run: {err}", file=sys.stderr)
        return 2
    root = options.data_root
    problems = preflight(root, list(options.films), build_required=not options.no_build)
    if problems:
        print("parity_run: " + "\n  ".join(problems), file=sys.stderr)
        return 2
    # Sampled before the build, and kept only if the build left it unchanged.
    built_from = recorded_crates(
        no_build=options.no_build,
        rescored=rescored_with(options) is not None,
    )
    if not options.no_build:
        print("[parity] cargo build --release -p stunt-cli", file=sys.stderr)
        try:
            build_release()
        except RuntimeError as err:
            print(f"parity_run: build failed: {err}", file=sys.stderr)
            return 1

    crates = built_from if built_from == clean_crates_tree() else None
    films = options.films
    if args.workers > 1:
        budget = render_budget(
            options.jobs,
            args.workers,
            len(films),
            default_jobs=DEFAULT_JOBS,
            cpus=os.cpu_count() or 1,
            memory=physical_memory(),
        )
        if budget.workers < args.workers:
            print(
                f"[parity] --workers {args.workers} cut to {budget.workers} so {budget.jobs} "
                "jobs fit the cores and memory",
                file=sys.stderr,
            )
    else:
        budget = RenderBudget(resolve_jobs(options.jobs, len(films)), 1)

    def work(job: FilmJob, _variant: None) -> FilmScore:
        """Renders (or reuses) *job*'s film and scores it, printing nothing."""
        source = prepare_source(
            job,
            options,
            no_render=args.no_render,
            software_only=args.software_only,
            built_from=crates,
            workers=budget.workers,
        )
        suffix = ""
        request = None
        if options.retime is not None:
            suffix = f"_retime{options.retime:+d}"
            request = Retime(options.retime, REPO_ROOT / parity_layout.retime_dir(job.name, suffix))
        report = REPO_ROOT / parity_layout.report_dir(job.name, suffix)
        film_crates = scored_render_tree(crates, source, no_render=args.no_render)
        if crates is not None and film_crates is None:
            print(
                f"[parity] {job.name}: report records no crates/ tree, so parity-repin refuses it: "
                f"{unrecorded_reason(crates, source)}; run without --no-render to repin",
                file=sys.stderr,
            )
        result = score_film(job, source, report, retime=request, crates=film_crates)
        if result.retime is not None:
            print(
                f"[parity] {job.name}: copied {result.retime.copied} frames; "
                f"missing {len(result.retime.missing)} ticks",
                file=sys.stderr,
            )
        return result

    # Each film has its own scratch, _current and _previous trees, so films never share one.
    # The longest capture renders first, so it does not run alone at the end.
    attempts = run_matrix(films, root, (None,), work, jobs=budget.jobs, weight=captured_ticks)[0]
    failures = 0
    for attempt in attempts:
        if isinstance(attempt, FilmFailure):
            failures += 1
            print(
                f"parity_run: {attempt.film} FAILED ({str(attempt.error).splitlines()[0][:120]})",
                file=sys.stderr,
            )
        else:
            print(format_summary(attempt.film, attempt.report), flush=True)
            reference = read_reference(root, attempt.film)
            document = read_report(attempt.report / "report.json")
            print(comparison_line(reference, document, rescored=rescored_with(options)), flush=True)
    print(NOISE_NOTE)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
