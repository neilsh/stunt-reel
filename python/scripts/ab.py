"""Time variants of a headless render in interleaved rounds, into a CSV and a summary.

Usage::

    mise run ab -- --out work/2026-11/<issue>_<slug> --name span-b \\
        --variant base --variant "skip STUNT_PROBE_SKIP_WORLD=1" \\
        [--span 3680..=3979] [--adapter lavapipe|gpu ...] [--rounds 4] [--order alternate|rotate]
    mise run ab -- --out DIR --variant "old binary=build/old.exe" --variant "new binary=build/new.exe"
    mise run ab -- --summarize work/2026-11/<issue>_<slug>/span-b.csv

A ``--variant`` is ``NAME [binary=PATH] [VAR=VALUE ...]``: a name, optionally its own binary
(default the release ``stuntreel``), and the environment variables it sets. The first variant is
the baseline every change and "faster" count is against. Each round runs every variant once;
``alternate`` reverses the order every other round and ``rotate`` starts each round one variant
later. Every ``--span`` is run on every ``--adapter``: ``lavapipe`` sets ``VK_DRIVER_FILES`` to
``--icd`` (default Mesa 25.2.8 in the data root's ``tools/``) and passes ``--software-only``;
``gpu`` leaves both off. A run whose ``render.json`` names another adapter class than the cell's
fails the whole run.

Writes ``<out>/<name>.csv`` (one row per run, the loop and wall ms, the four store hashes, the
adapter) and ``<out>/<name>-summary.md``, and prints the summary; it refuses to overwrite either.
It refuses to start, and stops between runs, while a ``stuntreel``, ``cargo`` or ``rustc``
process runs, unless ``--force``. Build the binaries first: this runs them as they are. Exit 0
on success, 1 on a failed run, 2 on a refusal or bad arguments.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from typing import TYPE_CHECKING

from stunt_reel import ab_timing, dataroot, process_tree
from stunt_reel.link import binary_path
from stunt_reel.parity_pipeline import SIDATA

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

DEFAULT_SPAN = "3680..=3979"
DEFAULT_ICD = "tools/mesa-25.2.8/x64/lvp_icd.x86_64.json"
SCRATCH = dataroot.REPO_ROOT / "build" / "scratch" / "ab"


def _span(text: str) -> str:
    first, sep, last = text.partition("..=")
    if not (sep and first.isdigit() and last.isdigit() and int(first) <= int(last)):
        raise argparse.ArgumentTypeError(f"{text!r} is not FIRST..=LAST")
    return f"{int(first)}..={int(last)}"


def _variant(text: str) -> ab_timing.Variant:
    try:
        return ab_timing.parse_variant(text)
    except ValueError as err:
        raise argparse.ArgumentTypeError(str(err)) from err


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=dataroot.data_path_arg, help="the work folder to write into")
    parser.add_argument("--name", default="timing", help="file stem of the CSV and summary")
    parser.add_argument(
        "--variant",
        action="append",
        type=_variant,
        default=[],
        metavar="'NAME [binary=PATH] [VAR=VALUE ...]'",
    )
    parser.add_argument("--span", action="append", type=_span, default=[], metavar="FIRST..=LAST")
    parser.add_argument("--adapter", action="append", choices=("lavapipe", "gpu"), default=[])
    parser.add_argument(
        "--rounds", "--pairs", type=int, default=4, help="runs of each variant per cell"
    )
    parser.add_argument("--order", choices=ab_timing.MODES, default="alternate")
    parser.add_argument(
        "--film", type=dataroot.data_path_arg, help="default: Patch #3 LOCATION.FLM"
    )
    parser.add_argument(
        "--all", type=dataroot.data_path_arg, help="default: LOCATION's capture .ALL"
    )
    parser.add_argument(
        "--icd", type=dataroot.data_path_arg, help=f"default: <data root>/{DEFAULT_ICD}"
    )
    parser.add_argument("--data-root", type=dataroot.data_path_arg)
    parser.add_argument(
        "--force", action="store_true", help="time while another stuntreel, cargo or rustc runs"
    )
    parser.add_argument(
        "--summarize", type=dataroot.data_path_arg, metavar="CSV", help="print a CSV's summary"
    )
    return parser


def _refusals(
    args: argparse.Namespace, cells: list[ab_timing.Cell], inputs: dict[str, Path], root: Path
) -> list[str]:
    """What stops a run before it starts, one line each."""
    problems: list[str] = []
    if args.out is None:
        problems.append("name the work folder to write into with --out")
    if len(args.variant) < 2:
        problems.append("name at least two --variant")
    names = [v.name for v in args.variant]
    if len(set(names)) != len(names):
        problems.append("--variant names must differ")
    if args.rounds < 1:
        problems.append("--rounds must be at least 1")
    problems += [
        f"missing {what}: {path}"
        for what, path in inputs.items()
        if what != "icd" and not path.is_file()
    ]
    if not (dataroot.corpus_of(root) / SIDATA).is_dir():
        problems.append("missing the SIDATA directory under the data root's corpus")
    for variant in args.variant:
        binary = variant.binary or binary_path()
        if not binary.is_file():
            problems.append(f"missing binary of {variant.name}: {binary} (build it first)")
    if any(c.adapter == "lavapipe" for c in cells) and not inputs["icd"].is_file():
        problems.append(
            f"missing icd: {inputs['icd']} (a lavapipe cell needs it: "
            "see docs/howto/render-on-lavapipe.md)"
        )
    if args.out is not None:
        for suffix in (".csv", "-summary.md"):
            if (args.out / f"{args.name}{suffix}").exists():
                problems.append(
                    f"{args.out / (args.name + suffix)} exists; raw timings are never overwritten"
                )
    return problems


def _busy_message(found: list[str]) -> str:
    return f"{', '.join(found)} running: a timing needs a quiet machine (wait, or --force)"


def run(args: argparse.Namespace, root: Path) -> int:
    """The timing run *args* name; returns the exit code."""
    adapters = args.adapter or ["lavapipe"]
    cells = [
        ab_timing.Cell(span, adapter)
        for adapter in adapters
        for span in args.span or [DEFAULT_SPAN]
    ]
    inputs = {
        "film": args.film or root / "builds" / "patch3" / "VAULT" / "LOCATION.FLM",
        "archive": args.all or root / "captures" / "vault-location" / "archives" / "LOCATION.ALL",
        "icd": args.icd or root / DEFAULT_ICD,
    }
    problems = _refusals(args, cells, inputs, root)
    if not args.force and (found := ab_timing.busy_processes(process_tree.process_names())):
        problems.append(_busy_message(found))
    if problems:
        print("\n".join(f"ab: {p}" for p in problems), file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / f"{args.name}.csv"
    rows: list[ab_timing.Row] = []
    scratch = SCRATCH / args.name
    for cell in cells:
        expect = "cpu" if cell.adapter == "lavapipe" else "hardware"
        for index in range(args.rounds):
            for position, which in enumerate(
                ab_timing.round_order(len(args.variant), index, args.order)
            ):
                if not args.force and (
                    found := ab_timing.busy_processes(process_tree.process_names())
                ):
                    print(f"ab: stopped: {_busy_message(found)}", file=sys.stderr)
                    return 2
                variant = args.variant[which]
                out_dir = scratch / f"{cell.name}-{index}-{variant.name}"
                shutil.rmtree(out_dir, ignore_errors=True)
                argv = ab_timing.render_argv(
                    variant.binary or binary_path(),
                    inputs["film"],
                    inputs["archive"],
                    root,
                    cell,
                    out_dir,
                )
                env = ab_timing.environment_for(variant, cell.adapter, inputs["icd"])
                try:
                    loop, wall, sha, adapter, klass = ab_timing.run_once(
                        argv, env, out_dir, expect_class=expect
                    )
                except ab_timing.RunError as err:
                    print(f"ab: {cell.name} round {index} {variant.name}: {err}", file=sys.stderr)
                    return 1
                shutil.rmtree(out_dir, ignore_errors=True)
                rows.append(
                    ab_timing.Row(
                        cell.name, index, position, variant.name, loop, wall, sha, adapter, klass
                    )
                )
                csv_path.write_text(ab_timing.write_csv(rows), encoding="utf-8", newline="")
                print(
                    f"ab: {cell.name} round {index} {variant.name}: loop {loop:.0f} ms, wall {wall:.0f} ms"
                )
    summary = ab_timing.summarize(rows)
    (args.out / f"{args.name}-summary.md").write_text(summary, encoding="utf-8", newline="")
    print(summary)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.summarize is not None:
        try:
            print(
                ab_timing.summarize(ab_timing.read_csv(args.summarize.read_text(encoding="utf-8")))
            )
        except (OSError, ValueError) as err:
            print(f"ab: {err}", file=sys.stderr)
            return 2
        return 0
    return run(args, dataroot.data_root_flag(args.data_root))


if __name__ == "__main__":
    sys.exit(main())
