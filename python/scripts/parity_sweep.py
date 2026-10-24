"""Candidate sweep: render and score every combination of ``DBG_*`` values (probes.md section 4).

Assumes the ``DBG_*`` switches are already in the working tree (never committed). Builds
``stunt-cli`` once, then for each combination of ``--var`` values renders every film with those
variables in the environment, scores it against the film's capture with ``stuntreel parity``,
and prints one table sorted best first, then the winner. Render directories live under
``build/scratch/sweep/`` and are deleted after scoring.

Usage::

    mise run sweep -- --var DBG_PITCH=0,-0.5 --var DBG_DY=-0.2,-0.3 [--films ctry,intro]
        [--probe film|iou] [--keep-best] [--data-root DIR] [--no-build] [--retime N]
    mise run sweep -- --reuse build/scratch/retime [--films ctry,intro] [--retime N]

stdout carries only the table and the winner line; progress goes to stderr. Variants are ranked
by mean SSIM over the films (then mean mask IoU), so a CTRY-only gain that costs INTRO shows up.
``--probe iou`` adds the actor-window IoU of ``parity_probe.py`` (its CTRY background ranges are
used for every film). ``--data-root`` points at a checkout holding ``corpus/`` and
``build/parity/reference/`` when this one (a worktree) has none. ``--no-build`` reuses the
existing release binary, ``--reuse DIR`` scores an existing ``DIR/<film>`` tree without
rendering, and ``--retime N`` relabels each film directory by N ticks before scoring (see
``parity_probe.py retime``). Two variants that score identically to four decimals produce a
warning, and a winner within the 0.002 adoption floor says so.
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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import parity_probe
from parity_probe import capture_ticks

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
#: Per-film inputs (research/parity/method.md section 1, research/parity/attribution.md and 11).
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
        cmd,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if done.returncode != 0:
        tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-8:])
        raise RuntimeError(f"{Path(cmd[0]).name} exited {done.returncode}: {tail}")


#: Sidecar ``stunt-cli --headless`` writes beside its frames (``PALETTE_SIDECAR_NAME``).
RENDER_SIDECAR = "palette_controls.json"


def check_render(reference: Path, render: Path, ticks: list[int]) -> None:
    """Refuses a render that cannot be scored against ``reference``.

    Raises ``ValueError`` when the render's sidecar names a different film or ``.FLM`` size than
    the capture's ``meta.json`` (either side may lack the tags), or when a captured tick has no
    ``.idx``/``.layer`` planes beside its frame.
    """
    meta = json.loads((reference / "meta.json").read_text(encoding="utf-8"))
    sidecar_path = render / RENDER_SIDECAR
    if sidecar_path.is_file():
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        ours, theirs = sidecar.get("film"), meta.get("film")
        if ours and theirs and str(ours).upper() != str(theirs).upper():
            raise ValueError(f"the capture is of {theirs} but the render is of {ours}")
        ours, theirs = sidecar.get("flm_bytes"), meta.get("flm_bytes")
        if ours is not None and theirs is not None and ours != theirs:
            raise ValueError(f"the capture's .FLM is {theirs} bytes but the render's is {ours}")
    missing = [
        tick
        for tick in ticks
        if not all((render / f"tick_{tick:05d}.{ext}").is_file() for ext in ("idx", "layer"))
    ]
    if missing:
        raise ValueError(
            f"{render} has no render planes for {len(missing)} captured tick(s), first {missing[0]}"
        )


def render_film(film: Film, root: Path, render: Path, env: dict[str, str] | None) -> None:
    """Renders ``film`` into ``render`` with ``env`` in the environment."""
    exe = str(binary_path())
    run(
        [
            *(exe, "--headless", str(root / film.flm), "--all", str(root / film.all)),
            *(
                "--frames",
                render_range(capture_ticks(root / film.reference)),
                "--sidata",
                str(root / film.sidata),
                "--out-dir",
                str(render),
            ),
            *RENDER_FLAGS,
        ],
        env,
    )


def check_film(film: Film, root: Path, render: Path) -> None:
    """Refuses a render of ``film`` that cannot be scored against its capture."""
    reference = root / film.reference
    check_render(reference, render, capture_ticks(reference))


def score_dir(film: Film, root: Path, render: Path, report: Path, probe: str) -> Score:
    """Scores the render directory ``render`` of ``film`` against its capture."""
    reference = root / film.reference
    exe = str(binary_path())
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


def score_film(
    name: str, film: Film, root: Path, workdir: Path, env: dict[str, str], probe: str
) -> Score:
    """Renders ``film`` into ``workdir`` with ``env`` and scores it against its capture."""
    render, report = workdir / name, workdir / f"{name}_report"
    render_film(film, root, render, env)
    check_film(film, root, render)
    return score_dir(film, root, render, report, probe)


def write_crops(
    films: list[str], root: Path, workdir: Path, renders: dict[str, Path]
) -> list[Path]:
    """Writes ``parity_probe.py crop`` PNGs of the frame with the largest actor, per film."""
    written: list[Path] = []
    for name in films:
        report_json = workdir / f"{name}_report" / "report.json"
        reference, render = root / FILMS[name].reference, renders[name]
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


#: Adoption floor: a margin under this is not attributable to a change (probes.md section 6).
NOISE_FLOOR = 0.002


def build_release() -> None:
    """Builds the release binary once, since every render and score runs it."""
    run(["cargo", "build", "--release", "-p", "stunt-cli"])


def binary_locked(path: Path) -> bool:
    """Whether a process holds ``path`` open for writing (Windows refuses that on a running exe)."""
    if os.name != "nt" or not path.is_file():
        return False
    try:
        with path.open("r+b"):
            return False
    except PermissionError:
        return True


def preflight(
    root: Path,
    films: list[str],
    *,
    build_required: bool,
    locked: Callable[[Path], bool] = binary_locked,
) -> list[str]:
    """Problems that stop a sweep or baseline before any build or render starts."""
    problems: list[str] = []
    for name in films:
        film = FILMS[name]
        for path in (film.flm, film.all, film.sidata):
            if not (root / path).exists():
                problems.append(f"missing input {root / path} (try --data-root)")
        reference = root / film.reference
        if not (reference / "meta.json").is_file():
            problems.append(f"missing capture {reference} (run `mise run capture-ref`)")
    if build_required and locked(binary_path()):
        problems.append("release binary is in use; rerun with --no-build or wait")
    return problems


def format_summary(name: str, report: Path) -> str:
    """One line naming a scored film: ``ctry  ssim ... iou ... idx ... scored n/m``."""
    data = json.loads((report / "report.json").read_text(encoding="utf-8"))
    ssim, iou = parse_report(data)
    index = data.get("mean_index_agreement_scored")
    scored = data.get("scored_frames", 0)
    frames = data.get("frames", len(data.get("per_frame", [])))
    index_text = "-" if index is None else f"{float(index):.3f}"
    return f"{name:<5} ssim {ssim:.4f}  iou {iou:.4f}  idx {index_text}  scored {scored}/{frames}"


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


def prepare_render(
    name: str, film: Film, root: Path, workdir: Path, env: dict[str, str], by: int | None
) -> Path:
    """Renders ``film`` into ``workdir/<name>``, checks it, and returns its retimed copy."""
    render = workdir / name
    render_film(film, root, render, env)
    check_film(film, root, render)
    if by is None:
        return render
    retimed = workdir / f"{name}_retime"
    shutil.rmtree(retimed, ignore_errors=True)
    parity_probe.retime_render(
        render, root / film.reference, retimed, by, force=True, allow_missing=True
    )
    return retimed


def run_reuse(args: argparse.Namespace, films: list[str], root: Path) -> int:
    """Scores ``--reuse DIR``'s per-film render trees without rendering."""
    reuse: Path = args.reuse
    if not reuse.is_dir():
        print(f"parity_sweep: --reuse directory not found: {reuse}", file=sys.stderr)
        return 2
    failures = 0
    for name in films:
        film = FILMS[name]
        try:
            render = reuse / name
            if not render.is_dir():
                raise ValueError(f"{render} is not a render directory")
            check_film(film, root, render)
            if args.retime is not None:
                retimed = reuse / f"{name}_retime"
                shutil.rmtree(retimed, ignore_errors=True)
                parity_probe.retime_render(
                    render,
                    root / film.reference,
                    retimed,
                    args.retime,
                    force=True,
                    allow_missing=True,
                )
                render = retimed
            if not (render / RENDER_SIDECAR).is_file():
                print(
                    f"warning: {render} has no {RENDER_SIDECAR}; the measured fade decides",
                    file=sys.stderr,
                )
            report = reuse / f"{name}_report"
            score_dir(film, root, render, report, args.probe)
            print(format_summary(name, report))
        except (RuntimeError, ValueError, OSError, KeyError) as err:
            failures += 1
            print(
                f"parity_sweep: {name} FAILED ({str(err).splitlines()[0][:120]})",
                file=sys.stderr,
            )
    return 0 if failures == 0 else 1


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--var", action="append", default=None, metavar="DBG_NAME=v1,v2", help="repeatable"
    )
    parser.add_argument("--films", default=",".join(FILMS), help="comma list; default: all")
    parser.add_argument("--probe", choices=("film", "iou"), default="film")
    parser.add_argument("--keep-best", action="store_true", help="keep the winner's render dirs")
    parser.add_argument("--data-root", type=Path, default=REPO_ROOT, help="holds corpus/, captures")
    parser.add_argument("--no-build", action="store_true", help="reuse the release binary")
    parser.add_argument(
        "--reuse", type=Path, default=None, help="score DIR/<film> without rendering"
    )
    parser.add_argument(
        "--retime", type=int, default=None, metavar="N", help="relabel each film by N ticks"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_selector(args.reuse, args.var or [])
        parsed = [parse_var(spec) for spec in args.var or []]
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
    problems = preflight(root, films, build_required=not args.no_build)
    if problems:
        print("parity_sweep: " + "\n  ".join(problems), file=sys.stderr)
        return 2

    if not args.no_build:
        print("[sweep] cargo build --release -p stunt-cli", file=sys.stderr)
        try:
            build_release()
        except RuntimeError as err:
            print(f"parity_sweep: build failed: {err}", file=sys.stderr)
            return 1

    if args.reuse is not None:
        return run_reuse(args, films, root)

    print(f"[sweep] {len(combos)} variant(s)", file=sys.stderr)
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
                    variant.renders[film] = prepare_render(
                        film, FILMS[film], root, workdir, env, args.retime
                    )
                    score = score_dir(
                        FILMS[film],
                        root,
                        variant.renders[film],
                        workdir / f"{film}_report",
                        args.probe,
                    )
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
        line += f"; kept {SCRATCH / workdir.name}" + (f", crops {len(crops)}" if crops else "")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
