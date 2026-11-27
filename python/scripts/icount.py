"""Count a headless lavapipe render's instructions on two or more builds, into a CSV and a summary.

Usage::

    mise run icount -- --out work/2026-11/<issue>_<slug> --name span-b \\
        --variant "old binary=build/old.exe" --variant "new binary=build/new.exe" \\
        [--span 3680..=3709] [--repeats 3] [--top 10]

A ``--variant`` is ``NAME [binary=PATH] [VAR=VALUE ...]`` as in ``mise run ab``; the first is the
baseline. Each repeat runs every variant once, under ``setarch -R valgrind --tool=cachegrind``
with Mesa's shader cache off and one lavapipe thread (``docs/howto/count-a-renders-instructions.md``).
Writes ``<out>/<name>.csv`` and ``<out>/<name>-summary.md`` and prints the summary; it refuses to
overwrite either. Exit 0 on success, 1 on a failed run or a store that differs from the baseline's,
2 on a refusal or bad arguments.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import sys
from typing import TYPE_CHECKING

from stunt_reel import ab_timing, dataroot, icount
from stunt_reel.link import binary_path
from stunt_reel.parity_pipeline import SIDATA

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

DEFAULT_SPAN = "3680..=3709"
DEFAULT_ICD = "/usr/share/vulkan/icd.d/lvp_icd.json"
SCRATCH = dataroot.REPO_ROOT / "build" / "scratch" / "icount"


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
    parser.add_argument("--name", default="icount", help="file stem of the CSV and summary")
    parser.add_argument(
        "--variant",
        action="append",
        type=_variant,
        default=[],
        metavar="'NAME [binary=PATH] [VAR=VALUE ...]'",
    )
    parser.add_argument("--span", action="append", type=_span, default=[], metavar="FIRST..=LAST")
    parser.add_argument("--repeats", type=int, default=3, help="counted runs of each variant")
    parser.add_argument("--top", type=int, default=10, help="functions listed per variant")
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
    return parser


def _refusals(args: argparse.Namespace, inputs: dict[str, Path], root: Path) -> list[str]:
    """What stops a run before it starts, one line each."""
    problems: list[str] = []
    if args.out is None:
        problems.append("name the work folder to write into with --out")
    if len(args.variant) < 2:
        problems.append("name at least two --variant")
    names = [v.name for v in args.variant]
    if len(set(names)) != len(names):
        problems.append("--variant names must differ")
    if args.repeats < 2:
        problems.append("--repeats must be at least 2, so the baseline has a repeat range")
    problems += [f"missing {what}: {path}" for what, path in inputs.items() if not path.is_file()]
    if not (dataroot.corpus_of(root) / SIDATA).is_dir():
        problems.append("missing the SIDATA directory under the data root's corpus")
    problems += [
        f"{tool} is not on PATH" for tool in ("valgrind", "setarch") if not shutil.which(tool)
    ]
    for variant in args.variant:
        binary = variant.binary or binary_path()
        if not binary.is_file():
            problems.append(f"missing binary of {variant.name}: {binary} (build it first)")
    if args.out is not None:
        for suffix in (".csv", "-summary.md"):
            if (args.out / f"{args.name}{suffix}").exists():
                problems.append(
                    f"{args.out / (args.name + suffix)} exists; counts are never overwritten"
                )
    return problems


def run(args: argparse.Namespace, root: Path, runner: icount.Runner | None = None) -> int:
    """The counting run *args* name; returns the exit code."""
    inputs = {
        "film": args.film or root / "builds" / "patch3" / "VAULT" / "LOCATION.FLM",
        "archive": args.all or root / "captures" / "vault-location" / "archives" / "LOCATION.ALL",
        "icd": args.icd or root / DEFAULT_ICD,
    }
    problems = _refusals(args, inputs, root)
    if problems:
        print("\n".join(f"icount: {p}" for p in problems), file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    scratch = SCRATCH / args.name
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    counts: list[icount.Count] = []
    names = [v.name for v in args.variant]
    for span in args.span or [DEFAULT_SPAN]:
        cell = ab_timing.Cell(span, "lavapipe")
        for repeat in range(args.repeats):
            for variant in args.variant:
                stem = f"{cell.name}-{repeat}-{variant.name}".replace(" ", "_")
                out_dir, cg_out = scratch / stem, scratch / f"{stem}.cg"
                render = ab_timing.render_argv(
                    variant.binary or binary_path(),
                    inputs["film"],
                    inputs["archive"],
                    root,
                    cell,
                    out_dir,
                )
                argv = icount.cachegrind_argv(render, cg_out, platform.machine())
                env = icount.environment(variant, inputs["icd"])
                try:
                    count = icount.count_once(
                        argv,
                        env,
                        cg_out,
                        out_dir,
                        (span, variant.name, repeat),
                        **({"run": runner} if runner else {}),
                    )
                except icount.RunError as err:
                    print(f"icount: {span} repeat {repeat} {variant.name}: {err}", file=sys.stderr)
                    return 1
                shutil.rmtree(out_dir, ignore_errors=True)
                cg_out.unlink(missing_ok=True)
                counts.append(count)
                (args.out / f"{args.name}.csv").write_text(
                    icount.write_csv(counts), encoding="utf-8", newline=""
                )
                print(
                    f"icount: {span} repeat {repeat} {variant.name}: {count.total:,} instructions"
                )
    summary = icount.summarize(counts, names, args.top)
    (args.out / f"{args.name}-summary.md").write_text(summary, encoding="utf-8", newline="")
    print(summary)
    mismatched = [
        span
        for span in dict.fromkeys(c.span for c in counts)
        if not icount.stores_match(
            [c for c in counts if c.span == span],
            [c for c in counts if c.span == span and c.variant == names[0]],
        )
    ]
    if mismatched:
        print(
            f"icount: stores differ from the baseline's on {', '.join(mismatched)}", file=sys.stderr
        )
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run(args, dataroot.data_root_flag(args.data_root))


if __name__ == "__main__":
    sys.exit(main())
