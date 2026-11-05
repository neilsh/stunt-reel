"""Run one breakpoint plan on DOSBox-X's debugger link and record its hits as JSON lines.

`mise run debug-x -- --plan tools/dosbox-x/plans/smoke.toml [--film F] [--build patch3]`
boots the film, arms the plan's probes, writes
`<data root>/debug/<film stem>/<plan>-<build>-<UTC stamp>[-<n>].jsonl` (`-<n>` only when a run
in the same second took the name), prints a summary of at most 40 lines and exits: 0 when the
run ended normally (spent, stop_tick or timeout), 1 when a build's `PLAYONE.EXE`, the emulator
or the link failed, 2 when the plan, the patched mapping or a probe site was refused. Plan offsets are unpatched
image and DS offsets; `--build patch3` maps them through #78's pairing
(`docs/process/plans/debugger-breakpoints-2026-11-04.md`).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from build_pairing import load_image, pair_images
from dbx.addr import Runtime, vm_paragraph
from dbx.boot import DOSBOX_X_VERSION, booted
from dbx.link import LinkError
from dbx.plan import PlanError, for_patched, load_plan
from dbx.run import run_plan

from stunt_reel import dataroot, game_builds
from stunt_reel.tac.emulator import EmulatorUnavailable, GuestTimeout
from stunt_reel.tac.playone import PATCH3, UNPATCHED

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

SUMMARY_LINES: int = 40
DISTINCT: int = 8


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    root = dataroot.data_root()
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--plan", type=Path, required=True, help="plan TOML (tools/dosbox-x/plans/)"
    )
    parser.add_argument(
        "--film", type=dataroot.data_path_arg, default="corpus/stisldem/VAULT/CTRY.FLM"
    )
    parser.add_argument("--build", choices=game_builds.BUILD_NAMES, default="unpatched")
    parser.add_argument("--out", type=Path, default=root / "debug", help="output root")
    return parser.parse_args(argv)


def _top(values: Iterable[int]) -> str:
    counts = Counter(values)
    return ", ".join(f"{v:#x} x{n}" for v, n in counts.most_common(DISTINCT)) or "-"


def summary(records: Iterable[Mapping[str, Any]]) -> list[str]:
    """At most `SUMMARY_LINES` lines: per probe its hits, ignored, callers and writers."""
    rows = list(records)
    end = next((r for r in rows if r.get("type") == "end"), {})
    hits = [r for r in rows if r.get("type") == "hit"]
    lines = [f"end: {end.get('reason', '?')}, spurious {end.get('spurious', 0)}"]
    if end.get("detail"):
        lines.append(f"  {end['detail']}"[:200])
    for name, count in dict(end.get("hits", {})).items():
        mine = [h for h in hits if h.get("probe") == name]
        lines.append(f"{name}: hits {count}, ignored {end.get('ignored', {}).get(name, 0)}")
        callers = [h["return_far_image"] for h in mine if h.get("return_far_image") is not None]
        writers = [
            h["writer"]["image"]
            for h in mine
            if h.get("writer") and h["writer"].get("image") is not None
        ]
        if callers:
            lines.append(f"  return_far_image: {_top(callers)}")
        if writers:
            lines.append(f"  writer image: {_top(writers)}")
    return lines[:SUMMARY_LINES]


def reserve_output(directory: Path, stem: str) -> Path:
    """Create and return `<stem>.jsonl` in *directory*, or `<stem>-<n>.jsonl` if it exists.

    Creation is exclusive, so two runs started in the same second never share a file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        path = directory / (f"{stem}.jsonl" if n == 1 else f"{stem}-{n}.jsonl")
        try:
            path.open("x", encoding="utf-8").close()
        except FileExistsError:
            n += 1
            continue
        return path


def main(argv: list[str] | None = None) -> int:
    """Run the plan; see the module docstring for the exit codes."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if dataroot.require_corpus_or_report("mise run debug-x") is None:
        return 1
    try:
        plan = load_plan(args.plan)
    except (PlanError, OSError) as exc:
        print(f"debug-x: {exc}", file=sys.stderr)
        return 2
    builds = dataroot.data_root() / game_builds.BUILDS_DIR
    try:
        image = load_image(game_builds.build_tree(builds, args.build) / "PLAYONE.EXE")
        unpatched = (
            load_image(builds / "unpatched" / "PLAYONE.EXE") if args.build == "patch3" else None
        )
    except (OSError, ValueError) as exc:  # no build there, or not LZEXE
        print(f"debug-x: {exc}", file=sys.stderr)
        return 1
    layout = UNPATCHED if args.build == "unpatched" else PATCH3
    notes: dict[str, str] = {}
    if unpatched is not None:
        try:
            plan, notes = for_patched(plan, pair_images(unpatched, image))
        except (PlanError, ValueError) as exc:  # unmappable probe, or unpairable builds
            print(f"debug-x: {exc}", file=sys.stderr)
            return 2
    vm = vm_paragraph(image)
    unloaded = Runtime(image, 0, layout.dgroup_paragraph, vm)
    for probe in plan.probes:
        if probe.kind == "break" and probe.at is not None:
            try:
                unloaded.code_site(probe.at, probe.cs)
            except ValueError as exc:
                print(f'debug-x: probe "{probe.name}": {exc}', file=sys.stderr)
                return 2
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = reserve_output(args.out / args.film.stem, f"{plan.name}-{args.build}-{stamp}")
    header = {
        "build": args.build,
        "film": args.film.name,
        "emulator": f"dosbox-x {DOSBOX_X_VERSION}",
        "vm": vm,
        "dgroup_paragraph": layout.dgroup_paragraph,
        "patched_mapping": notes,
    }
    try:
        with (
            booted(args.film, args.build, cycles=plan.cycles) as boot,
            path.open("w", encoding="utf-8", newline="\n") as out,
        ):
            rt = Runtime(image, boot.load, layout.dgroup_paragraph, vm)
            result = run_plan(
                boot.link, rt, plan, layout.film_clock, out, header=header, start=boot.start
            )
    except (EmulatorUnavailable, GuestTimeout, LinkError) as exc:
        print(f"debug-x: {exc}", file=sys.stderr)
        return 1
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    print(path)
    print("\n".join(summary(records)))
    return {"refused": 2, "link_lost": 1, "error": 1}.get(result.reason, 0)


if __name__ == "__main__":
    raise SystemExit(main())
