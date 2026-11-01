"""Score the parity metrics against planted faults and recapture noise.

Subcommands::

    mise run parity-bench -- run --film ctry [--render DIR] [--report FILE] [--recapture ID]
        [--seed N] [--floor-render DIR] [--out DIR]
    mise run parity-bench -- plant --render DIR --out DIR --fault shift_x:4@500-599 ...
    mise run parity-bench -- judge-make --film ctry --seed N [--out DIR]
    mise run parity-bench -- judge-score --film ctry --seed N --answers FILE [--out DIR]

``run`` writes ``bench.json`` into ``--out`` and prints one row per metric: whether it passes,
its sigma, and the drop each fault causes in sigma. ``plant`` copies a render tree and writes the
faults over the ticks named, so a render with known errors can be scored by the real scorer.
``judge-make`` writes blind capture|A|B composites and ``ids.txt`` for a Haiku judge;
``judge-score`` scores its answer file and writes ``judge.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from stunt_reel import parity_layout, references
from stunt_reel.bench.faults import ALL_FAULTS, Fault
from stunt_reel.bench.judge import answer_key, make_composites, score_answers
from stunt_reel.bench.planes import BenchError
from stunt_reel.bench.run import plant_tree, run_bench
from stunt_reel.dataroot import REPO_ROOT, ensure_links_or_report

DEFAULT_RECAPTURE = "005"
DEFAULT_SEED = 1


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


def _judge_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    film = args.film
    root = Path(args.data_root).resolve()
    reference = references.reference_dir(root, film)
    render = args.render or REPO_ROOT / parity_layout.render_dir(film)
    report = args.report or REPO_ROOT / parity_layout.report_dir(film) / "report.json"
    out = args.out or REPO_ROOT / "build" / "parity" / "bench" / film / "judge"
    return reference, render, report, out


def judge_make(args: argparse.Namespace) -> int:
    reference, render, report, out = _judge_paths(args)
    count = make_composites(reference, render, report, out, args.seed, args.frames_per_fault)
    print(f"[bench] wrote {count} composites and ids.txt into {out}", file=sys.stderr)
    return 0


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def judge_score(args: argparse.Namespace) -> int:
    reference, render, report, out = _judge_paths(args)
    key = answer_key(reference, render, report, args.seed, args.frames_per_fault)
    document = score_answers(args.answers, key)
    out.mkdir(parents=True, exist_ok=True)
    (out / "judge.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    for name, entry in document.items():
        if isinstance(entry, dict):
            verdict = "PASS" if entry["passes"] else "FAIL"
            print(
                f"{name:<16} {verdict}  accuracy {_fmt(entry['accuracy'])}  "
                f"answered {entry['answered']}  a_share {_fmt(entry['a_share'])}"
            )
    print(f"unanswered {document['unanswered']}  control_a_share {document['control_a_share']}")
    print(f"[bench] wrote {out / 'judge.json'}", file=sys.stderr)
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
    for name, handler in (("judge-make", judge_make), ("judge-score", judge_score)):
        judge_p = sub.add_parser(
            name,
            help="blind composites for a Haiku judge"
            if name == "judge-make"
            else "score a judge's answers",
        )
        judge_p.add_argument("--film", required=True)
        judge_p.add_argument("--render", type=Path, default=None)
        judge_p.add_argument("--report", type=Path, default=None)
        judge_p.add_argument("--seed", type=int, default=DEFAULT_SEED)
        judge_p.add_argument("--frames-per-fault", type=int, default=10)
        judge_p.add_argument("--out", type=Path, default=None)
        judge_p.add_argument("--data-root", type=Path, default=REPO_ROOT)
        if name == "judge-score":
            judge_p.add_argument("--answers", type=Path, required=True)
        judge_p.set_defaults(handler=handler)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if (
        args.command in ("run", "judge-make", "judge-score")
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
