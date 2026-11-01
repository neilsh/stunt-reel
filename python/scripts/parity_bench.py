"""Score the parity metrics against planted faults and recapture noise.

Subcommands::

    mise run parity-bench -- run --film ctry [--render DIR] [--report FILE] [--recapture ID]
        [--seed N] [--floor-render DIR] [--out DIR]
    mise run parity-bench -- plant --render DIR --out DIR --fault shift_x:4@500-599 ...
    mise run parity-bench -- errors-make --film ctry [--calibrate] [--recapture ID] [--seed N]
    mise run parity-bench -- errors-score --film ctry [--against READOUT]
    mise run parity-bench -- errors-make|errors-score --film vault-tod --batch
    mise run parity-bench -- errors-example --film ctry --tick T --category ID

``run`` writes ``bench.json`` into ``--out`` and prints one row per metric: whether it passes,
its sigma, and the drop each fault causes in sigma. ``plant`` copies a render tree and writes the
faults over the ticks named, so a render with known errors can be scored by the real scorer.
``errors-make`` writes the error readout's sheets, ``ids.txt``, ``brief.md`` and ``run.json``
into ``build/parity/bench/<film>/errors``; a Haiku subagent reads the brief and writes
``grades.txt``; ``errors-score`` writes ``readout.json`` and prints it, the changes since
``--against`` and, for a calibrating run, the calibration. ``errors-example`` commits one tick's
sheet as an example of a category. ``--batch`` reads a film the batch survey captured, rendered
and scored (``mise run batch-parity``) instead of a pinned reference; a film with no
``[films.<film>]`` window is graded over its whole length.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from stunt_reel import parity_layout, references
from stunt_reel.bench.errors import make_run, score_run, write_example
from stunt_reel.bench.faults import ALL_FAULTS, Fault
from stunt_reel.bench.planes import BenchError
from stunt_reel.bench.run import plant_tree, run_bench
from stunt_reel.dataroot import REPO_ROOT, ensure_links_or_report

DEFAULT_RECAPTURE = "005"
DEFAULT_SEED = 1
CATEGORIES = REPO_ROOT / "research" / "parity" / "error-categories.toml"


def parse_plant(text: str) -> tuple[Fault, range]:
    """``name[:magnitude]@FIRST-LAST`` (inclusive) as a fault and its tick range."""
    key, at, span = text.partition("@")
    faults = {fault.key: fault for fault in ALL_FAULTS}
    first, dash, last = span.partition("-")
    if (
        key not in faults
        or not at
        or not dash
        or not first.isdigit()
        or not last.isdigit()
        or int(last) < int(first)
    ):
        raise argparse.ArgumentTypeError(
            f"{text!r} is not KEY@FIRST-LAST with KEY one of {', '.join(faults)}"
        )
    return faults[key], range(int(first), int(last) + 1)


def _print_rows(document: dict[str, Any]) -> None:
    keys = [fault.key for fault in ALL_FAULTS if fault.name != "none"]
    for name, results in document["results"].items():
        verdict = "PASS" if document["passes"][name] else "FAIL"
        cells = []
        for key in keys:
            sigmas = results[key]["sigmas"]
            cells.append(f"{key}={'n/a' if sigmas is None else format(sigmas, '.1f')}")
        sigma = document["sigma"][name]
        shown = "n/a" if sigma is None else f"{sigma:.5f}"
        print(f"{name:<16} {verdict}  sigma {shown}  " + " ".join(cells))


def run(args: argparse.Namespace) -> int:
    film = args.film
    root = Path(args.data_root).resolve()
    pointer = references.read_reference(root, film)
    reference = references.reference_dir(root, film)
    recapture = root / parity_layout.frames_path(pointer.slug, args.recapture)
    render = args.render or REPO_ROOT / parity_layout.render_dir(film)
    report = args.report or REPO_ROOT / parity_layout.report_dir(film) / "report.json"
    out = args.out or REPO_ROOT / "build" / "parity" / "bench" / film
    document = run_bench(reference, recapture, render, report, args.seed, args.floor_render)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    _print_rows(document)
    print(f"[bench] wrote {out / 'bench.json'}", file=sys.stderr)
    return 0


def plant(args: argparse.Namespace) -> int:
    plant_tree(args.render, args.out, args.fault)
    print(f"[bench] planted {len(args.fault)} fault ranges into {args.out}", file=sys.stderr)
    return 0


def _errors_out(args: argparse.Namespace) -> Path:
    return Path(args.out or REPO_ROOT / "build" / "parity" / "bench" / args.film / "errors")


def _render(args: argparse.Namespace) -> Path:
    if args.render:
        return Path(args.render)
    if args.batch:
        return REPO_ROOT / parity_layout.batch_film_dir(args.film) / "render"
    return REPO_ROOT / parity_layout.render_dir(args.film)


def _batch_capture(root: Path, slug: str) -> Path:
    """The batch survey's latest capture of *slug*: its highest-numbered run."""
    parent = root / parity_layout.frames_root(slug)
    runs = (
        [p for p in parent.iterdir() if p.is_dir() and p.name.isdigit()] if parent.is_dir() else []
    )
    if not runs:
        raise BenchError(f"{parent} holds no capture; run mise run batch-parity -- --only {slug}")
    return max(runs, key=lambda p: int(p.name))


def _revision() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - git from PATH, as every task
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except OSError, subprocess.CalledProcessError:
        return "unknown"
    return done.stdout.strip()


def errors_make(args: argparse.Namespace) -> int:
    film = args.film
    root = Path(args.data_root).resolve()
    recapture = None
    if args.batch:
        if args.calibrate:
            raise BenchError("--calibrate needs a pinned reference and recapture, not --batch")
        reference = _batch_capture(root, film)
        report_dir = REPO_ROOT / parity_layout.batch_film_dir(film) / "report"
    else:
        reference = references.reference_dir(root, film)
        if args.calibrate:
            pointer = references.read_reference(root, film)
            recapture = root / parity_layout.frames_path(pointer.slug, args.recapture)
        report_dir = REPO_ROOT / parity_layout.report_dir(film)
    report = args.report or report_dir / "report.json"
    out = _errors_out(args)
    count = make_run(
        film, reference, recapture, _render(args), report, out, CATEGORIES, args.seed, _revision()
    )
    print(f"[bench] wrote {count} sheets and brief.md into {out}", file=sys.stderr)
    return 0


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def errors_score(args: argparse.Namespace) -> int:
    out = _errors_out(args)
    result, changes, calibration = score_run(out, _render(args), CATEGORIES, args.against)
    frames = len(result.ticks) - result.missing
    for category in result.categories:
        ungraded = f"  ungraded {category.ungraded}" if category.ungraded else ""
        print(
            f"{category.category:<28} 2+ on {len(category.ticks_2plus)}/{frames}  "
            f"mean {_fmt(category.mean)}{ungraded}"
        )
    for tick, note in sorted(result.other.items()):
        print(f"other @{tick}: {note}")
    if result.missing:
        print(f"missing {result.missing} of {len(result.ticks)} sheets")
    if result.unknown:
        print(f"unknown categories: {', '.join(result.unknown)}")
    if changes is not None:
        print(f"changes since {args.against}: {len(changes) or 'none'}")
        for change in changes:
            print(
                f"  {change.category:<28} {change.before} -> {change.after}  "
                f"added {list(change.added)}  removed {list(change.removed)}"
            )
    if calibration is not None:
        verdict = "PASS" if calibration.passes else "FAIL"
        clean = f"{calibration.controls_clean}/{calibration.controls}"
        print(f"calibration {verdict}: controls clean {clean}")
        for key, (detected, sheets) in calibration.faults.items():
            print(f"  {key:<16} detected {detected}/{sheets}")
    print(f"[bench] wrote {out / 'readout.json'}", file=sys.stderr)
    return 0


def errors_example(args: argparse.Namespace) -> int:
    root = Path(args.data_root).resolve()
    if args.batch:
        reference = _batch_capture(root, args.film)
    else:
        reference = references.reference_dir(root, args.film)
    path = write_example(args.film, args.tick, args.category, reference, _render(args), CATEGORIES)
    print(f"[bench] {path.name} is an example of {args.category}", file=sys.stderr)
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="bench the metrics on one film")
    run_p.add_argument("--film", required=True)
    run_p.add_argument("--render", type=Path, default=None)
    run_p.add_argument("--report", type=Path, default=None)
    run_p.add_argument("--recapture", default=DEFAULT_RECAPTURE, help="recapture id")
    run_p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    run_p.add_argument("--floor-render", type=Path, default=None)
    run_p.add_argument("--out", type=Path, default=None)
    run_p.add_argument("--data-root", type=Path, default=REPO_ROOT)
    run_p.set_defaults(handler=run)
    plant_p = sub.add_parser("plant", help="write known faults into a copy of a render")
    plant_p.add_argument("--render", type=Path, required=True)
    plant_p.add_argument("--out", type=Path, required=True)
    plant_p.add_argument(
        "--fault",
        type=parse_plant,
        nargs="+",
        action="extend",
        required=True,
        metavar="KEY@A-B",
    )
    plant_p.set_defaults(handler=plant)
    make_p = sub.add_parser("errors-make", help="sheets and a brief for the error readout")
    make_p.add_argument("--film", required=True)
    make_p.add_argument("--calibrate", action="store_true", help="add controls and planted faults")
    make_p.add_argument("--recapture", default=DEFAULT_RECAPTURE, help="recapture id for controls")
    make_p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    make_p.add_argument("--render", type=Path, default=None)
    make_p.add_argument("--report", type=Path, default=None)
    make_p.add_argument("--out", type=Path, default=None)
    make_p.add_argument("--data-root", type=Path, default=REPO_ROOT)
    make_p.add_argument(
        "--batch", action="store_true", help="the batch survey's capture, render and report"
    )
    make_p.set_defaults(handler=errors_make)
    score_p = sub.add_parser("errors-score", help="score grades.txt into readout.json")
    score_p.add_argument("--film", required=True)
    score_p.add_argument("--against", type=Path, default=None, help="an earlier readout.json")
    score_p.add_argument("--render", type=Path, default=None)
    score_p.add_argument("--out", type=Path, default=None)
    score_p.add_argument(
        "--batch", action="store_true", help="the batch survey's capture, render and report"
    )
    score_p.set_defaults(handler=errors_score)
    example_p = sub.add_parser("errors-example", help="commit a tick's sheet as a category example")
    example_p.add_argument("--film", required=True)
    example_p.add_argument("--tick", type=int, required=True)
    example_p.add_argument("--category", required=True)
    example_p.add_argument("--render", type=Path, default=None)
    example_p.add_argument("--data-root", type=Path, default=REPO_ROOT)
    example_p.add_argument(
        "--batch", action="store_true", help="the batch survey's capture, render and report"
    )
    example_p.set_defaults(handler=errors_example)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if (
        args.command in ("run", "errors-make", "errors-example")
        and Path(args.data_root).resolve() == REPO_ROOT
        and not ensure_links_or_report("parity_bench")
    ):
        return 2
    try:
        return int(args.handler(args))
    except (BenchError, references.ReferenceCaptureError, OSError) as err:
        print(f"parity_bench: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
