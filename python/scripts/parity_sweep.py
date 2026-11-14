"""Candidate sweep: render and score every combination of ``DBG_*`` values (probes.md section 4).

Assumes the ``DBG_*`` switches are already in the working tree (never committed). Builds
``stunt-cli`` once, then for each combination of ``--var`` values renders every film with those
variables in the environment, scores it against the film's capture with ``stuntreel parity``,
and prints one table sorted best first, then the winner. Render directories live under the
sweep root that ``stunt_reel.parity_layout`` names and are deleted after scoring.

Usage::

    mise run sweep -- --var DBG_PITCH=0,-0.5 --var DBG_DY=-0.2,-0.3 [--films ctry,intro]
        [--probe film|iou] [--keep-best] [--data-root DIR] [--no-build] [--retime N]
        [--track evidence|heuristic [--target <film>:<lo>-<hi> ...
            [--images DIR --topic WORDS [--crop x0,y0,x1,y1]]]]
    mise run sweep -- --reuse <retime root> [--films ctry,intro] [--retime N]

stdout carries only the ``--target`` echo, the table and the winner line; progress, the
listed frames and the picture paths go to stderr. The baseline is the variant of each
``--var``'s first value, and every other variant is judged against it once all have finished (``stunt_reel.parity_judge``).
With ``--track`` the winner line gives the adoption rule's verdict (loop-rules.md) and the
baseline never wins; ``--track`` and ``--target`` refuse a ``--films`` subset, ``--reuse`` and
a single variant, and a ``--target`` range holding no captured tick stops the sweep before it
renders. Without ``--track`` variants are ranked by mean SSIM over the films (then mean mask
IoU), so a CTRY-only gain that costs INTRO shows up, and there is no verdict.
``--images DIR --topic WORDS`` (both, and only with ``--target``) then draws, for the winner (else
the best variant that is not the baseline), one PNG per chosen tick into ``DIR`` as
``<film>-<tick>-<topic>.png``: the capture, the baseline and the winner, left to right
(``stunt_reel.parity_pictures`` chooses the ticks). It re-renders only those ticks, refuses before
rendering when a path it could write exists, and never replaces a picture. ``--crop x0,y0,x1,y1``
crops every picture to that box, enlarged 3 times; without it a picture is the whole frame.
``--probe iou`` adds the actor-window IoU of ``parity_probe.py`` (its CTRY background ranges are
used for every film). ``--data-root`` points at a checkout holding ``corpus/`` and the capture
directories when this one (a worktree) has none. ``--no-build`` reuses the existing release
binary, ``--reuse DIR`` scores an existing ``DIR/<film>`` tree without rendering, and ``--retime
N`` relabels each film directory by N ticks before scoring (see ``parity_probe.py retime``). Two
variants that score identically to four decimals produce a warning, and a winner within the
0.002 adoption floor says so.
"""

from __future__ import annotations

import argparse
import itertools
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import parity_probe
from cli import add_parity_options, parity_options, resolve_jobs

from stunt_reel import parity_layout, references
from stunt_reel.matched_frames import Reference
from stunt_reel.parity_artifacts import (
    Geometry,
    RenderStore,
    read_capture,
    read_report,
)
from stunt_reel.parity_judge import (
    BASELINE,
    TRACKS,
    Decision,
    FilmRun,
    Headline,
    Judgement,
    Target,
    Track,
    Variant,
    decide,
    judge,
    label,
    outcome_lines,
    sort_key,
)
from stunt_reel.parity_pictures import (
    CROP_SCALE,
    Picture,
    existing_paths,
    films_with,
    parse_crop,
    plan_pictures,
    topic_clashes,
    topic_slug,
)
from stunt_reel.parity_pipeline import (
    REPO_ROOT,
    FilmFailure,
    FilmJob,
    FilmScore,
    Score,
    build_release,
    format_summary,
    preflight,
    reference_job,
    render_film,
    retime_render,
    run_film,
    run_films,
    run_matrix,
)

VAR_NAME = re.compile(r"DBG_[A-Z0-9_]+")
#: Padding around the actor's silhouette in the winner's crop, in pixels.
CROP_PAD = 25


@dataclass(frozen=True)
class SweepPlan:
    """One variant to run: its score record, work directory and rendering environment."""

    variant: Variant
    workdir: Path
    env: dict[str, str]


def parse_var(spec: str) -> tuple[str, list[str]]:
    """Splits ``DBG_NAME=a,b,c`` into the name and its values (kept as given)."""
    name, sep, raw = spec.partition("=")
    if not sep or not VAR_NAME.fullmatch(name):
        raise ValueError(f"--var must look like DBG_NAME=v1,v2, got {spec!r}")
    values = raw.split(",")
    if any(not v.strip() for v in values):
        raise ValueError(f"--var {name} has an empty value in {raw!r}")
    return name, [v.strip() for v in values]


def expand_variants(names: list[str], value_lists: list[list[str]]) -> list[tuple[str, ...]]:
    """Cartesian product of the value lists; the last variable varies fastest."""
    if len(set(names)) != len(names):
        raise ValueError("a --var name is given twice")
    return list(itertools.product(*value_lists))


def padded_box(pixels: list[int], pad: int, geometry: Geometry) -> tuple[int, int, int, int]:
    """Viewport box around pixel offsets, padded and clamped; the whole viewport when empty."""
    width, rows = geometry.width, geometry.plane_rows()
    if not pixels:
        return 0, 0, width, rows
    xs = [p % width for p in pixels]
    ys = [p // width for p in pixels]
    return (
        max(0, min(xs) - pad),
        max(0, min(ys) - pad),
        min(width, max(xs) + pad),
        min(rows, max(ys) + pad),
    )


def write_crops(
    films: list[str], root: Path, workdir: Path, renders: dict[str, Path]
) -> list[Path]:
    """Writes ``parity_probe.py crop`` PNGs of the frame with the largest actor, per film."""
    written: list[Path] = []
    for name in films:
        report_json = parity_layout.run_report_json(workdir, name)
        render = renders[name]
        store = RenderStore(render)
        geometry = store.record.geometry
        with references.open_reference(root, name) as reference:
            best: tuple[int, int, int, list[int]] | None = None
            for matched in Reference(reference, store).from_report(read_report(report_json)):
                pixels = matched.page.actor_pixels()
                if best is None or len(pixels) > best[0]:
                    best = (len(pixels), matched.ordinal, matched.film_tick, pixels)
            if best is None:
                continue
            _, ordinal, film_tick, pixels = best
            out = workdir / f"crop_{name}.png"
            box = padded_box(pixels, CROP_PAD, geometry)
            parity_probe.make_crop(reference, render, ordinal, film_tick, box, 3, out)
        written.append(out)
    return written


def _same_scores(left: Headline | None, right: Headline | None) -> bool:
    if left is None or right is None:
        return False
    return round(left.ssim, 4) == round(right.ssim, 4) and round(left.iou, 4) == round(right.iou, 4)


def identical_variant_pairs(variants: list[Variant]) -> list[tuple[Variant, Variant]]:
    """Pairs whose per-film SSIM and IoU both agree to four decimals."""
    pairs: list[tuple[Variant, Variant]] = []
    for left, right in itertools.combinations(variants, 2):
        films = left.scores.keys() & right.scores.keys()
        if films and all(_same_scores(left.scores[f], right.scores[f]) for f in films):
            pairs.append((left, right))
    return pairs


def validate_selector(reuse: Path | None, specs: list[str]) -> None:
    """``--var`` is required for a sweep and forbidden with ``--reuse``."""
    if reuse is not None and specs:
        raise ValueError("--var cannot be combined with --reuse")
    if reuse is None and not specs:
        raise ValueError("--var is required unless --reuse is given")


def validate_judging(
    targets: list[Target],
    track: Track | None,
    *,
    films: list[str],
    pinned: tuple[str, ...],
    reuse: Path | None,
    variants: int,
) -> None:
    """Raises ``ValueError`` unless the judging flags are usable.

    ``--target`` needs ``--track``; either refuses a ``--films`` subset, ``--reuse``, a single
    variant, and a target on a film that is not a reference film.
    """
    if targets and track is None:
        raise ValueError("--target needs --track")
    if track is None:
        return
    flag = "--target" if targets else "--track"
    if set(films) != set(pinned):
        raise ValueError(f"{flag} judges every reference film, so it refuses a --films subset")
    if reuse is not None:
        raise ValueError(f"{flag} cannot be combined with --reuse, which has no baseline")
    if variants < 2:
        raise ValueError(f"{flag} needs two variants or more; the first is the baseline")
    unknown = [t.spec() for t in targets if t.film not in pinned]
    if unknown:
        raise ValueError(f"--target {unknown[0]} names no reference film ({', '.join(pinned)})")


@dataclass(frozen=True)
class PictureOptions:
    """``--images``, ``--topic`` and ``--crop`` as resolved: where, under what topic, which box."""

    directory: Path
    topic: str
    #: ``None`` draws the whole frame.
    box: tuple[int, int, int, int] | None


def validate_pictures(
    images: Path | None, topic: str | None, crop: str | None, targets: list[Target]
) -> PictureOptions | None:
    """The picture options, or ``None`` when none is given; raises ``ValueError`` when unusable.

    ``--images`` and ``--topic`` go together, ``--images`` needs ``--target``, ``--crop`` needs
    ``--images``, and a picture of that topic already in the directory refuses the sweep.
    """
    if images is None and topic is None and crop is None:
        return None
    if images is None:
        raise ValueError("--topic needs --images" if topic is not None else "--crop needs --images")
    if topic is None:
        raise ValueError("--images needs --topic")
    if not targets:
        raise ValueError("--images needs --target")
    if images.exists() and not images.is_dir():
        raise ValueError(f"--images {images} is not a directory")
    slug = topic_slug(topic)
    box = parse_crop(crop) if crop is not None else None
    clashes = topic_clashes(images, slug)
    if clashes:
        raise ValueError(
            f"{clashes[0].name} already exists in {images}; a picture is never replaced, "
            "so name another --topic"
        )
    return PictureOptions(images, slug, box)


def uncaptured_ranges(root: Path, targets: list[Target]) -> list[str]:
    """A problem per ``--target`` range whose film's reference capture holds no tick in it."""
    problems = []
    for film in dict.fromkeys(t.film for t in targets):
        try:
            with references.open_reference(root, film) as capture:
                ticks = [frame.film_tick for frame in read_capture(capture).frames]
        except (references.ReferenceCaptureError, OSError, ValueError) as err:
            problems.append(str(err))
            continue
        problems += [
            f"--target {t.spec()} holds no captured tick"
            for t in targets
            if t.film == film and not any(t.lo <= tick <= t.hi for tick in ticks)
        ]
    return problems


def _first_line(error: Exception, limit: int) -> str:
    """The first line of a failure, trimmed to the caller's budget."""
    return str(error).splitlines()[0][:limit]


def with_actor_iou(attempt: FilmScore, root: Path) -> Score:
    """Adds ``parity_probe``'s actor-window IoU to one pipeline score."""
    with references.open_reference(root, attempt.film) as reference:
        actor, _ = parity_probe.actor_iou(attempt.report / "report.json", reference, attempt.render)
    return Score(attempt.score.ssim, attempt.score.iou, actor)


def run_reuse(reuse: Path, retime: int | None, films: list[str], root: Path) -> int:
    """Scores ``--reuse DIR``'s per-film render trees without rendering."""
    if not reuse.is_dir():
        print(f"parity_sweep: --reuse directory not found: {reuse}", file=sys.stderr)
        return 2
    failures = 0
    for attempt in run_films(films, root, reuse, render=False, retime=retime):
        if isinstance(attempt, FilmFailure):
            failures += 1
            print(
                f"parity_sweep: {attempt.film} FAILED ({_first_line(attempt.error, 120)})",
                file=sys.stderr,
            )
            continue
        print(format_summary(attempt.film, attempt.report))
    return 0 if failures == 0 else 1


def render_ticks(
    job: FilmJob, out: Path, env: dict[str, str], ticks: list[int], retime: int | None
) -> None:
    """Renders only *ticks* of the job's film into *out*, as the sweep's variant was scored.

    With a retime, film tick ``t`` shows source tick ``t + retime``: those ticks are rendered
    and relabelled into *out*.
    """
    if retime is None:
        render_film(job, out, env, ticks=ticks)
        return
    raw = out.with_name(out.name + "_raw")
    render_film(job, raw, env, ticks=[tick + retime for tick in ticks])
    retime_render(raw, job.capture, out, retime, force=True, allow_missing=True)


def draw_film(
    capture: Path,
    stores: tuple[Path, Path],
    pictures: list[Picture],
    directory: Path,
    *,
    box: tuple[int, int, int, int] | None,
    scale: int,
) -> list[Path]:
    """Writes one PNG per picture: *capture*'s frame, then each of *stores* at that tick.

    *box* is cut from the whole frame, enlarged *scale* times; ``None`` is the whole frame.
    Raises ``ValueError`` for a tick the capture or a store lacks, a box outside the frame, or
    a picture that exists.
    """
    ordinals: dict[int, int] = {}
    for frame in read_capture(capture).frames:
        ordinals.setdefault(frame.film_tick, frame.ordinal)
    geometry = RenderStore(stores[0]).record.geometry
    box = box or (0, 0, geometry.width, geometry.height)
    if not (0 <= box[0] < box[2] <= geometry.width and 0 <= box[1] < box[3] <= geometry.height):
        raise ValueError(f"--crop {box} is outside the {geometry.width}x{geometry.height} frame")
    held = [RenderStore(store) for store in stores]
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for picture in pictures:
        if picture.tick not in ordinals or not all(store.holds(picture.tick) for store in held):
            raise ValueError(
                f"{picture.film} tick {picture.tick} is not in the capture and renders"
            )
        out = directory / picture.name
        if out.exists():
            raise ValueError(f"{out} already exists; a picture is never replaced")
        ordinal = ordinals[picture.tick]
        parity_probe.make_strip(capture, list(stores), ordinal, picture.tick, box, scale, out)
        written.append(out)
    return written


def write_pictures(
    decision: Decision,
    plans: list[SweepPlan],
    options: PictureOptions,
    *,
    root: Path,
    retime: int | None,
    scratch: Path,
) -> int:
    """Draws the winner's pictures against the baseline's; the exit code.

    With no winner the best variant that is not the baseline is drawn, as the stderr lines
    describe it. A decision with no verdict, or no variant to draw, draws nothing and says so.
    Only the chosen ticks are re-rendered, into a scratch directory removed afterwards.
    """
    shown = decision.winner or decision.best
    if decision.no_verdict is not None or shown is None:
        print("[sweep] no pictures: the sweep gave no verdict to draw", file=sys.stderr)
        return 0
    pictures = plan_pictures(decision.judgements[shown.index], options.topic)
    taken = existing_paths(options.directory, [p.name for p in pictures])
    if taken:
        print(f"parity_sweep: {taken[0]} already exists; no pictures drawn", file=sys.stderr)
        return 1
    if not pictures:
        print("[sweep] no pictures: no target frame was scored in both variants", file=sys.stderr)
        return 0
    work = scratch / "pictures"
    shutil.rmtree(work, ignore_errors=True)
    scale = CROP_SCALE if options.box is not None else 1
    drawn = (plans[BASELINE - 1], plans[shown.index - 1])
    written: list[Path] = []
    try:
        for film, ticks in films_with(pictures).items():
            stores = (work / film / "baseline", work / film / "shown")
            with reference_job(root, film) as job:
                for store, plan in zip(stores, drawn, strict=True):
                    render_ticks(job, store, plan.env, ticks, retime)
                written += draw_film(
                    job.capture,
                    stores,
                    [p for p in pictures if p.film == film],
                    options.directory,
                    box=options.box,
                    scale=scale,
                )
    except (RuntimeError, ValueError, OSError, references.ReferenceCaptureError) as err:
        print(f"parity_sweep: pictures failed: {_first_line(err, 200)}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    which = "the winner" if decision.winner is not None else "the best variant, not adopted"
    print(f"[sweep] {len(written)} picture(s) of {which}: capture | baseline | it", file=sys.stderr)
    for path in written:
        print(f"[sweep] picture {path}", file=sys.stderr)
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--var", action="append", default=None, metavar="DBG_NAME=v1,v2", help="repeatable"
    )
    add_parity_options(parser)
    parser.add_argument("--probe", choices=("film", "iou"), default="film")
    parser.add_argument("--keep-best", action="store_true", help="keep the winner's render dirs")
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="FILM:LO-HI",
        help="repeatable: an inclusive range of film ticks the round targets; needs --track",
    )
    parser.add_argument(
        "--track", choices=TRACKS, default=None, help="judge by this track's adoption rule"
    )
    parser.add_argument(
        "--images",
        type=Path,
        default=None,
        metavar="DIR",
        help="draw the winner's capture | baseline | winner pictures here; needs --target, --topic",
    )
    parser.add_argument("--topic", default=None, help="a few words naming what the pictures show")
    parser.add_argument(
        "--crop", default=None, metavar="x0,y0,x1,y1", help="crop every picture, enlarged 3 times"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Renders and scores every variant on every chosen film, then judges and ranks them.

    Exits 2 on a refused invocation, a failed preflight or a ``--target`` range holding no
    captured tick, and 1 when the pictures of ``--images`` fail after the verdict printed.
    Every variant's work directory is removed on the way out, interrupted or not, except the
    best one's under ``--keep-best``; with ``--track`` that is never the baseline.
    """
    args = parse_args(argv)
    try:
        validate_selector(args.reuse, args.var or [])
        parsed = [parse_var(spec) for spec in args.var or []]
        names = [n for n, _ in parsed]
        combos = expand_variants(names, [v for _, v in parsed])
        options = parity_options(args)
        targets = [Target.parse(spec) for spec in args.target]
        track: Track | None = args.track
        validate_judging(
            targets,
            track,
            films=list(options.films),
            pinned=references.reference_films(options.data_root),
            reuse=options.reuse,
            variants=len(combos),
        )
        pictures = validate_pictures(args.images, args.topic, args.crop, targets)
    except ValueError as err:
        print(f"parity_sweep: {err}", file=sys.stderr)
        return 2
    films = list(options.films)
    root = options.data_root
    problems = preflight(root, films, build_required=not options.no_build)
    if not problems:
        problems = uncaptured_ranges(root, targets)
    if problems:
        print("parity_sweep: " + "\n  ".join(problems), file=sys.stderr)
        return 2

    if not options.no_build:
        print("[sweep] cargo build --release -p stunt-cli", file=sys.stderr)
        try:
            build_release()
        except RuntimeError as err:
            print(f"parity_sweep: build failed: {err}", file=sys.stderr)
            return 1

    if options.reuse is not None:
        return run_reuse(options.reuse, options.retime, films, root)

    print(f"[sweep] {len(combos)} variant(s)", file=sys.stderr)
    scratch = REPO_ROOT / parity_layout.sweep_root()
    plans = [
        SweepPlan(
            Variant(index, values, {}),
            scratch / f"v{index:03d}",
            {**os.environ, **dict(zip(names, values, strict=True))},
        )
        for index, values in enumerate(combos, start=1)
    ]
    for plan in plans:
        shutil.rmtree(plan.workdir, ignore_errors=True)
    variants: list[Variant] = []
    best: Variant | None = None
    baseline: Variant | None = None
    #: Variants finished before the baseline, kept until they can be judged against it.
    waiting: list[Variant] = []
    started = time.monotonic()

    def work(job: FilmJob, plan: SweepPlan) -> FilmScore:
        """Renders and scores *job*'s film in *plan*'s work directory and environment."""
        return run_film(job, plan.workdir, env=plan.env, retime=options.retime)

    def key(variant: Variant) -> tuple[float, ...]:
        """The variant's rank; with a track, judged against the finished baseline."""
        judged: Judgement | None = None
        if track is not None and baseline is not None:
            judged = judge(baseline.frames, variant.frames, targets, track)
        return sort_key(variant, judged, track)

    def keep(variant: Variant) -> None:
        """Keeps *variant*'s work directory when it ranks above the best so far, else removes it."""
        nonlocal best
        if (
            args.keep_best
            and variant.mean_ssim() is not None
            and (best is None or key(variant) < key(best))
        ):
            if best is not None:
                shutil.rmtree(scratch / f"v{best.index:03d}", ignore_errors=True)
            best = variant
        else:
            shutil.rmtree(scratch / f"v{variant.index:03d}", ignore_errors=True)

    def on_variant(position: int, row: list[FilmScore | FilmFailure]) -> None:
        """Records a finished variant's scores and per-frame reports; keeps the best so far.

        Called on this thread as each variant's last film finishes, in completion order. With a
        track the baseline is never kept, and a variant finishing before it waits for it; ranks
        break ties by index, so the best kept does not depend on that order.
        """
        nonlocal baseline
        plan = plans[position]
        variant = plan.variant
        notes = []
        for attempt in row:
            if isinstance(attempt, FilmFailure):
                variant.scores[attempt.film] = variant.frames[attempt.film] = None
                notes.append(f"{attempt.film} FAILED ({_first_line(attempt.error, 80)})")
                continue
            try:
                measured = with_actor_iou(attempt, root) if args.probe == "iou" else attempt.score
                frames = FilmRun.of(read_report(attempt.report / "report.json"))
            except (RuntimeError, ValueError, OSError, KeyError) as err:
                variant.scores[attempt.film] = variant.frames[attempt.film] = None
                notes.append(f"{attempt.film} FAILED ({_first_line(err, 80)})")
                continue
            variant.renders[attempt.film] = attempt.render
            variant.scores[attempt.film] = measured
            variant.frames[attempt.film] = frames
            notes.append(f"{attempt.film} {measured.ssim:.4f}")
        variants.append(variant)
        if track is None:
            keep(variant)
        elif variant.index == BASELINE:
            baseline = variant
            shutil.rmtree(plan.workdir, ignore_errors=True)
            for held in waiting:
                keep(held)
            waiting.clear()
        elif baseline is None and args.keep_best:
            waiting.append(variant)
        else:
            keep(variant)
        print(
            f"[{variant.index}/{len(combos)}] {label(names, variant.values)}: {', '.join(notes)}"
            f" ({time.monotonic() - started:.0f}s)",
            file=sys.stderr,
        )

    jobs = resolve_jobs(options.jobs, len(plans) * len(films))
    try:
        run_matrix(films, root, plans, work, jobs=jobs, on_variant=on_variant)
    finally:
        # Every variant's directory, finished or not, except the best kept so far.
        for plan in plans:
            if best is None or plan.variant is not best:
                shutil.rmtree(plan.workdir, ignore_errors=True)

    decision = decide(variants, targets, track)
    out, notes = outcome_lines(names, films, decision, args.probe)
    print("\n".join(out[:-1]))
    for left, right in identical_variant_pairs(decision.ordered)[:3]:
        print(
            f"warning: variants {label(names, left.values)} and {label(names, right.values)}"
            " scored identically; the switch may not be wired",
            file=sys.stderr,
        )
    for note in notes:
        print(f"[sweep] {note}", file=sys.stderr)
    line = out[-1]
    if best is not None:
        workdir = scratch / f"v{best.index:03d}"
        crops = write_crops(films, root, workdir, best.renders)
        line += f"; kept {parity_layout.sweep_root() / workdir.name}" + (
            f", crops {len(crops)}" if crops else ""
        )
    print(line)
    if pictures is not None:
        return write_pictures(
            decision, plans, pictures, root=root, retime=options.retime, scratch=scratch
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
