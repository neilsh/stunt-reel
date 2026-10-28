"""Candidate sweep: render and score every combination of ``DBG_*`` values (probes.md section 4).

Assumes the ``DBG_*`` switches are already in the working tree (never committed). Builds
``stunt-cli`` once, then for each combination of ``--var`` values renders every film with those
variables in the environment, scores it against the film's capture with ``stuntreel parity``,
and prints one table sorted best first, then the winner. Render directories live under the
sweep root that ``stunt_reel.parity_layout`` names and are deleted after scoring.

Usage::

    mise run sweep -- --var DBG_PITCH=0,-0.5 --var DBG_DY=-0.2,-0.3 [--films ctry,intro]
        [--probe film|iou] [--keep-best] [--data-root DIR] [--no-build] [--retime N]
    mise run sweep -- --reuse <retime root> [--films ctry,intro] [--retime N]

stdout carries only the table and the winner line; progress goes to stderr. Variants are ranked
by mean SSIM over the films (then mean mask IoU), so a CTRY-only gain that costs INTRO shows up.
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
from dataclasses import dataclass, field
from pathlib import Path

import parity_probe
from cli import add_parity_options, parity_options

from stunt_reel import parity_layout
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.parity_artifacts import (
    Geometry,
    open_render,
    read_capture,
    read_report,
    render_plane_paths,
)
from stunt_reel.parity_pipeline import (
    FILMS,
    REPO_ROOT,
    FilmFailure,
    FilmScore,
    Score,
    build_release,
    format_summary,
    preflight,
    run_films,
)

VAR_NAME = re.compile(r"DBG_[A-Z0-9_]+")
#: Padding around the actor's silhouette in the winner's crop, in pixels.
CROP_PAD = 25


@dataclass
class Variant:
    """One combination of values; ``scores`` holds ``None`` for a film that failed."""

    index: int
    values: tuple[str, ...]
    scores: dict[str, Score | None]
    renders: dict[str, Path] = field(default_factory=dict)

    def mean_ssim(self) -> float | None:
        return self._mean([s.ssim if s else None for s in self.scores.values()])

    def mean_iou(self) -> float | None:
        return self._mean([s.iou if s else None for s in self.scores.values()])

    @staticmethod
    def _mean(values: list[float | None]) -> float | None:
        if not values or any(v is None for v in values):
            return None
        return sum(v for v in values if v is not None) / len(values)


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


def rank(variants: list[Variant]) -> list[Variant]:
    """Best first by mean SSIM, then mean IoU; variants with a failed film go last."""

    def key(v: Variant) -> tuple[int, float, float, int]:
        ssim, iou = v.mean_ssim(), v.mean_iou()
        if ssim is None or iou is None:
            return (1, 0.0, 0.0, v.index)
        return (0, -ssim, -iou, v.index)

    return sorted(variants, key=key)


def label(names: list[str], values: tuple[str, ...]) -> str:
    return " ".join(f"{n}={v}" for n, v in zip(names, values, strict=True))


def _cell(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def format_table(names: list[str], films: list[str], variants: list[Variant], probe: str) -> str:
    """Aligned table, one line per variant in the order given."""
    header = list(names)
    for film in films:
        header += [f"{film} SSIM", f"{film} IoU"]
        if probe == "iou":
            header.append(f"{film} actor")
    if len(films) > 1:
        header.append("mean SSIM")
    rows = [header]
    for v in variants:
        row = list(v.values)
        for film in films:
            s = v.scores.get(film)
            row += [_cell(s.ssim if s else None), _cell(s.iou if s else None)]
            if probe == "iou":
                row.append(_cell(s.actor_iou if s else None))
        if len(films) > 1:
            row.append(_cell(v.mean_ssim()))
        rows.append(row)
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    return "\n".join(
        "  ".join(c.rjust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in rows
    )


def winner_line(names: list[str], variants: list[Variant]) -> str:
    best = variants[0] if variants else None
    if best is None or best.mean_ssim() is None:
        return "winner: none (every variant failed)"
    return f"winner: {label(names, best.values)} (mean SSIM {_cell(best.mean_ssim())})"


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
        report_json = workdir / f"{name}_report" / "report.json"
        reference, render = root / FILMS[name].reference, renders[name]
        capture = read_capture(reference)
        geometry = open_render(render).geometry or capture.geometry
        best: tuple[int, int, int, list[int]] | None = None
        for frame in read_report(report_json).per_frame:
            if frame.scored is not True:
                continue
            layer = render_plane_paths(render, frame.film_tick)[1].read_bytes()
            pixels = parity_probe.actor_pixels(layer, geometry)
            if best is None or len(pixels) > best[0]:
                best = (len(pixels), frame.ordinal, frame.film_tick, pixels)
        if best is None:
            continue
        _, ordinal, film_tick, pixels = best
        out = workdir / f"crop_{name}.png"
        box = padded_box(pixels, CROP_PAD, geometry)
        parity_probe.make_crop(reference, render, ordinal, film_tick, box, 3, out)
        written.append(out)
    return written


#: Adoption floor: a margin under this is not attributable to a change (probes.md section 6).
NOISE_FLOOR = 0.002


def _same_scores(left: Score | None, right: Score | None) -> bool:
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


def noise_note(margin: float) -> str:
    """Appended to a winner line when the lead over the runner-up is inside the noise floor."""
    if margin < NOISE_FLOOR:
        return " (noise floor +/-0.002; winner is ~within noise)"
    return ""


def validate_selector(reuse: Path | None, specs: list[str]) -> None:
    """``--var`` is required for a sweep and forbidden with ``--reuse``."""
    if reuse is not None and specs:
        raise ValueError("--var cannot be combined with --reuse")
    if reuse is None and not specs:
        raise ValueError("--var is required unless --reuse is given")


def _first_line(error: Exception, limit: int) -> str:
    """The first line of a failure, trimmed to the caller's budget."""
    return str(error).splitlines()[0][:limit]


def with_actor_iou(attempt: FilmScore, root: Path) -> Score:
    """Adds ``parity_probe``'s actor-window IoU to one pipeline score."""
    actor, _ = parity_probe.actor_iou(
        attempt.report / "report.json",
        root / FILMS[attempt.film].reference,
        attempt.render,
    )
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
        for warning in attempt.warnings:
            print(f"warning: {attempt.render} {warning}", file=sys.stderr)
        print(format_summary(attempt.film, attempt.report))
    return 0 if failures == 0 else 1


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--var", action="append", default=None, metavar="DBG_NAME=v1,v2", help="repeatable"
    )
    add_parity_options(parser, films=FILMS, data_root=REPO_ROOT)
    parser.add_argument("--probe", choices=("film", "iou"), default="film")
    parser.add_argument("--keep-best", action="store_true", help="keep the winner's render dirs")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_selector(args.reuse, args.var or [])
        parsed = [parse_var(spec) for spec in args.var or []]
        names = [n for n, _ in parsed]
        combos = expand_variants(names, [v for _, v in parsed])
        options = parity_options(args, films=FILMS)
    except ValueError as err:
        print(f"parity_sweep: {err}", file=sys.stderr)
        return 2
    films = list(options.films)
    root = options.data_root
    if root == REPO_ROOT and not ensure_links_or_report("parity_sweep"):
        return 2
    problems = preflight(root, films, build_required=not options.no_build)
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
    variants: list[Variant] = []
    best: Variant | None = None
    try:
        for index, values in enumerate(combos, start=1):
            started = time.monotonic()
            workdir = scratch / f"v{index:03d}"
            shutil.rmtree(workdir, ignore_errors=True)
            env = {**os.environ, **dict(zip(names, values, strict=True))}
            variant = Variant(index, values, {})
            notes = []
            for attempt in run_films(films, root, workdir, env=env, retime=options.retime):
                if isinstance(attempt, FilmFailure):
                    variant.scores[attempt.film] = None
                    notes.append(f"{attempt.film} FAILED ({_first_line(attempt.error, 80)})")
                    continue
                try:
                    measured = (
                        with_actor_iou(attempt, root) if args.probe == "iou" else attempt.score
                    )
                except (RuntimeError, ValueError, OSError, KeyError) as err:
                    variant.scores[attempt.film] = None
                    notes.append(f"{attempt.film} FAILED ({_first_line(err, 80)})")
                    continue
                variant.renders[attempt.film] = attempt.render
                variant.scores[attempt.film] = measured
                notes.append(f"{attempt.film} {measured.ssim:.4f}")
            variants.append(variant)
            mean = variant.mean_ssim()
            if (
                args.keep_best
                and mean is not None
                and (best is None or rank([best, variant])[0] is variant)
            ):
                if best is not None:
                    shutil.rmtree(scratch / f"v{best.index:03d}", ignore_errors=True)
                best = variant
            else:
                shutil.rmtree(workdir, ignore_errors=True)
            print(
                f"[{index}/{len(combos)}] {label(names, values)}: {', '.join(notes)}"
                f" ({time.monotonic() - started:.0f}s)",
                file=sys.stderr,
            )
    finally:
        for v in variants:
            if best is None or v is not best:
                shutil.rmtree(scratch / f"v{v.index:03d}", ignore_errors=True)

    ordered = rank(variants)
    print(format_table(names, films, ordered, args.probe))
    for left, right in identical_variant_pairs(ordered)[:3]:
        print(
            f"warning: variants {label(names, left.values)} and {label(names, right.values)}"
            " scored identically; the switch may not be wired",
            file=sys.stderr,
        )
    line = winner_line(names, ordered)
    if len(ordered) > 1:
        first, second = ordered[0].mean_ssim(), ordered[1].mean_ssim()
        if first is not None and second is not None:
            line += noise_note(first - second)
    if best is not None:
        workdir = scratch / f"v{best.index:03d}"
        crops = write_crops(films, root, workdir, best.renders)
        line += f"; kept {parity_layout.sweep_root() / workdir.name}" + (
            f", crops {len(crops)}" if crops else ""
        )
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
