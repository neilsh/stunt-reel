"""Candidate sweep: render and score every combination of ``DBG_*`` values (probes.md section 4).

Assumes the ``DBG_*`` switches are already in the working tree (never committed). Builds
``stunt-cli`` once, then for each combination of ``--var`` values renders every film with those
variables in the environment, scores it against the film's capture with ``stuntreel parity``,
and prints one table sorted best first, then the winner. Render directories live under
``build/scratch/sweep/`` and are deleted after scoring.

Usage::

    mise run sweep -- --var DBG_PITCH=0,-0.5 --var DBG_DY=-0.2,-0.3 [--films ctry,intro]
        [--probe film|iou] [--keep-best] [--data-root DIR]

stdout carries only the table and the winner line; progress goes to stderr. Variants are ranked
by mean SSIM over the films (then mean mask IoU), so a CTRY-only gain that costs INTRO shows up.
``--probe iou`` adds the actor-window IoU of ``parity_probe.py`` (its CTRY background ranges are
used for every film). ``--data-root`` points at a checkout holding ``corpus/`` and
``build/parity/reference/`` when this one (a worktree) has none.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import parity_probe

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRATCH = Path("build/scratch/sweep")
VAR_NAME = re.compile(r"DBG_[A-Z0-9_]+")
#: Padding around the actor's silhouette in the winner's crop, in pixels.
CROP_PAD = 25


@dataclass(frozen=True)
class Film:
    """Inputs of one film's render and score; paths are relative to the data root."""

    flm: str
    all: str
    sidata: str
    reference: str


_VAULT = "corpus/stisldem/VAULT"
_SIDATA = "corpus/si_archive/Developer/FreeFlight/SIDATA"
#: Per-film inputs (research/parity/method.md section 1, parity-findings.md sections 9 and 11).
FILMS: dict[str, Film] = {
    "ctry": Film(
        f"{_VAULT}/CTRY.FLM", f"{_VAULT}/CTRY.ALL", _SIDATA, "build/parity/reference/ctry"
    ),
    "intro": Film(
        f"{_VAULT}/INTRO.FLM", f"{_VAULT}/INTRO.ALL", _SIDATA, "build/parity/reference/intro"
    ),
}
RENDER_FLAGS = ("--width", "320", "--height", "200", "--viewport-rows", "185")


@dataclass(frozen=True)
class Score:
    ssim: float
    iou: float
    actor_iou: float | None = None


@dataclass
class Variant:
    """One combination of values; ``scores`` holds ``None`` for a film that failed."""

    index: int
    values: tuple[str, ...]
    scores: dict[str, Score | None]

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


def render_range(ticks: list[int]) -> str:
    """``--frames`` range covering the captured film ticks (frame n renders tick n - 1)."""
    return f"{min(ticks) + 1}..{max(ticks) + 2}"


def parse_report(data: dict[str, Any]) -> tuple[float, float]:
    """Headline SSIM and mask IoU of a ``parity`` report: scored frames, else all matched."""
    ssim = data.get("mean_ssim_scored")
    iou = data.get("mean_iou_scored")
    if ssim is None:
        ssim = data.get("mean_ssim")
    if iou is None:
        iou = data.get("mean_iou")
    if ssim is None or iou is None:
        raise ValueError("report has no mean SSIM or mean IoU")
    return float(ssim), float(iou)


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


def padded_box(pixels: list[int], pad: int) -> tuple[int, int, int, int]:
    """Viewport box around pixel offsets, padded and clamped; the whole viewport when empty."""
    if not pixels:
        return 0, 0, parity_probe.WIDTH, parity_probe.ROWS
    xs = [p % parity_probe.WIDTH for p in pixels]
    ys = [p // parity_probe.WIDTH for p in pixels]
    return (
        max(0, min(xs) - pad),
        max(0, min(ys) - pad),
        min(parity_probe.WIDTH, max(xs) + pad),
        min(parity_probe.ROWS, max(ys) + pad),
    )


def binary_path() -> Path:
    return REPO_ROOT / "target" / "release" / ("stuntreel.exe" if os.name == "nt" else "stuntreel")


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    """Runs a command with its output captured; raises with the output's tail on failure."""
    done = subprocess.run(  # noqa: S603 - fixed argument vectors, no shell
        cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, errors="replace", check=False
    )
    if done.returncode != 0:
        tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-8:])
        raise RuntimeError(f"{Path(cmd[0]).name} exited {done.returncode}: {tail}")


def capture_ticks(reference: Path) -> list[int]:
    meta = json.loads((reference / "meta.json").read_text(encoding="utf-8"))
    return [int(f["film_tick"]) for f in meta["frames"]]


def score_film(
    name: str, film: Film, root: Path, workdir: Path, env: dict[str, str], probe: str
) -> Score:
    """Renders ``film`` into ``workdir`` with ``env`` and scores it against its capture."""
    reference = root / film.reference
    render, report = workdir / name, workdir / f"{name}_report"
    frames = render_range(capture_ticks(reference))
    exe = str(binary_path())
    run(
        [
            *(exe, "--headless", str(root / film.flm), "--all", str(root / film.all)),
            *("--frames", frames, "--sidata", str(root / film.sidata), "--out-dir", str(render)),
            *RENDER_FLAGS,
        ],
        env,
    )
    run(
        [
            *(exe, "parity", "--reference", str(reference), "--test", str(render)),
            *("--output", str(report)),
        ]
    )
    report_json = report / "report.json"
    ssim, iou = parse_report(json.loads(report_json.read_text(encoding="utf-8")))
    actor = None
    if probe == "iou":
        actor, _ = parity_probe.actor_iou(report_json, reference, render)
    return Score(ssim, iou, actor)


def write_crops(films: list[str], root: Path, workdir: Path) -> list[Path]:
    """Writes ``parity_probe.py crop`` PNGs of the frame with the largest actor, per film."""
    written: list[Path] = []
    for name in films:
        report_json = workdir / f"{name}_report" / "report.json"
        reference, render = root / FILMS[name].reference, workdir / name
        best: tuple[int, dict[str, int], list[int]] | None = None
        for frame in parity_probe.scored_frames(report_json):
            layer = (render / f"tick_{frame['film_tick']:05d}.layer").read_bytes()
            pixels = parity_probe.actor_pixels(layer)
            if best is None or len(pixels) > best[0]:
                best = (len(pixels), frame, pixels)
        if best is None:
            continue
        _, frame, pixels = best
        out = workdir / f"crop_{name}.png"
        box = padded_box(pixels, CROP_PAD)
        parity_probe.make_crop(reference, render, frame["ordinal"], frame["film_tick"], box, 3, out)
        written.append(out)
    return written


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--var", action="append", required=True, metavar="DBG_NAME=v1,v2", help="repeatable"
    )
    parser.add_argument("--films", default=",".join(FILMS), help="comma list; default: all")
    parser.add_argument("--probe", choices=("film", "iou"), default="film")
    parser.add_argument("--keep-best", action="store_true", help="keep the winner's render dirs")
    parser.add_argument("--data-root", type=Path, default=REPO_ROOT, help="holds corpus/, captures")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        parsed = [parse_var(spec) for spec in args.var]
        names = [n for n, _ in parsed]
        combos = expand_variants(names, [v for _, v in parsed])
        films = [f.strip() for f in args.films.split(",") if f.strip()]
        unknown = [f for f in films if f not in FILMS]
        if unknown or not films:
            raise ValueError(f"--films must be from {', '.join(FILMS)}, got {args.films!r}")
    except ValueError as err:
        print(f"parity_sweep: {err}", file=sys.stderr)
        return 2
    root: Path = args.data_root.resolve()
    missing = [
        str(root / p)
        for f in films
        for p in (FILMS[f].flm, FILMS[f].all, FILMS[f].sidata, FILMS[f].reference)
        if not (root / p).exists()
    ]
    if missing:
        print(
            "parity_sweep: missing inputs (try --data-root):\n  " + "\n  ".join(missing),
            file=sys.stderr,
        )
        return 2

    print(f"[sweep] cargo build --release -p stunt-cli; {len(combos)} variant(s)", file=sys.stderr)
    try:
        run(["cargo", "build", "--release", "-p", "stunt-cli"])
    except RuntimeError as err:
        print(f"parity_sweep: build failed: {err}", file=sys.stderr)
        return 1

    scratch = REPO_ROOT / SCRATCH
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
            for film in films:
                try:
                    score = score_film(film, FILMS[film], root, workdir, env, args.probe)
                    variant.scores[film] = score
                    notes.append(f"{film} {score.ssim:.4f}")
                except (RuntimeError, ValueError, OSError, KeyError) as err:
                    variant.scores[film] = None
                    notes.append(f"{film} FAILED ({str(err).splitlines()[0][:80]})")
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
    line = winner_line(names, ordered)
    if best is not None:
        workdir = scratch / f"v{best.index:03d}"
        crops = write_crops(films, root, workdir)
        line += f"; kept {SCRATCH / workdir.name}" + (f", crops {len(crops)}" if crops else "")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
