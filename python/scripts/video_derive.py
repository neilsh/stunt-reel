"""Derive a video capture's per-frame columns and check it against the pinned frames.

Subcommands, each on one video capture directory (``<data root>/captures-video/<slug>`` or any
``--dir``, such as a ``capture-video --out`` recording):

* ``derive``: write ``derived.json`` beside ``meta.json``: ``source`` hashes of ``meta.json`` and
  the AVI, the ``rules``, and the columns ``render_tick`` (ADR 0057) and ``palette_step``. The file is local only, never archived, and rewritten freely.
* ``reference-check <film>``: compare the video with the film's pinned frame capture
  (``references.toml``): offset histogram, pixel-equal fractions, and each page as exact, split or band. Derives the
  columns first and writes the check into ``derived.json``. With ``--stream``, compare the stream
  (``stream.mkv``) instead, by palette index; this writes nothing.
* ``replay <dir> <dir>``: say whether two recordings of one film are identical, AVI and log, and the stream's
  recorded hashes when both have a ``stream.json``.
* ``pairing``: test ADR 0057's pairing rule on the last frame of each slot_clock run, without a render (does a
  key name one picture) and, with ``--render <store>``, against a render store of the film. With ``--stream``,
  the pictures come from the stream and the AVI is not decoded.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
lazy from collections.abc import Sequence

from stunt_reel import dataroot, parity_layout, references, video_check
from stunt_reel.parity_artifacts import (
    RenderStore,
    VideoDerived,
    derive_video,
    load_video_capture,
    read_video_derived,
    write_video_derived,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-root", type=Path, default=None, help="data root (default: configured)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def add_target(command: argparse.ArgumentParser, *, film: bool) -> None:
        if film:
            command.add_argument("film", help="the research/parity/references.toml row, e.g. ctry")
        command.add_argument(
            "--dir",
            type=dataroot.data_path_arg,
            default=None,
            help="the video capture directory (default: the film's captures-video folder)",
        )

    derive = commands.add_parser("derive", help="write derived.json beside meta.json")
    derive.add_argument("film", nargs="?", help="a references.toml row (or name --dir)")
    derive.add_argument("--dir", type=dataroot.data_path_arg, default=None)
    check = commands.add_parser("reference-check", help="compare with the pinned frame capture")
    add_target(check, film=True)
    check.add_argument(
        "--search",
        type=int,
        default=video_check.REFERENCE_SEARCH,
        help="largest offset searched, at least 4",
    )
    check.add_argument(
        "--stream",
        action="store_true",
        help="compare the stream (stream.mkv) by palette index; writes nothing",
    )
    replay = commands.add_parser("replay", help="compare two recordings of one film")
    replay.add_argument("first", type=dataroot.data_path_arg)
    replay.add_argument("second", type=dataroot.data_path_arg)
    pairing = commands.add_parser("pairing", help="test the pairing rule on run-end frames")
    add_target(pairing, film=False)
    pairing.add_argument("film", nargs="?", help="a references.toml row (or name --dir)")
    pairing.add_argument(
        "--key-row",
        choices=("last", "first"),
        default="last",
        help="the row of each run of one slot_clock whose words key the picture (default last)",
    )
    pairing.add_argument(
        "--render", type=dataroot.data_path_arg, default=None, help="a render store of the film"
    )
    pairing.add_argument(
        "--stream",
        action="store_true",
        help="take the pictures from stream.mkv, not the AVI (the AVI is not decoded)",
    )
    return parser.parse_args(argv)


def resolve_dir(args: argparse.Namespace, root: Path) -> Path:
    """The video capture directory the arguments name."""
    if args.dir is not None:
        directory: Path = args.dir
        return directory
    if not args.film:
        raise SystemExit("video-derive: name a film or --dir")
    pointer = references.read_reference(root, args.film)
    return root / parity_layout.video_path(pointer.slug)


def report(line: str) -> None:
    """Print one line the way the capture scripts do."""
    print(f"[video-derive] {line}", flush=True)


def kept_check(directory: Path, derived: VideoDerived) -> VideoDerived:
    """*derived* with the ``reference_check`` of the file already in *directory*, when that file
    was derived from the same two files and its check still stands."""
    try:
        old = read_video_derived(directory)
    except OSError, ValueError:
        return derived
    if old.source != derived.source or old.rules != derived.rules:
        return derived
    return replace(derived, reference_check=old.reference_check)


def run_derive(directory: Path) -> int:
    """Write ``derived.json`` for *directory*, keeping a reference check made from the same files."""
    derived = kept_check(directory, derive_video(directory))
    write_video_derived(directory, derived)
    rows = len(derived.frames.render_tick)
    report(
        f"{directory}: {rows} rows, render_tick {derived.rules.render_tick}, "
        f"{sum(derived.frames.palette_step)} palette steps"
    )
    return 0


def run_reference_check(directory: Path, film: str, root: Path, search: int) -> int:
    """Compare the video with *film*'s pinned frame capture and record the check."""
    capture = load_video_capture(directory)
    with references.open_reference(root, film) as held:
        matches, skipped = video_check.page_matches(directory, capture, held, search=search)
        digest = references.capture_digest(held)
    check = video_check.summarise(matches, skipped, digest=digest, search=search)
    write_video_derived(directory, derive_video(directory, check))
    report(f"{film}: {check.pages} pages ({check.skipped} skipped), digest {digest[:12]}")
    report(f"offsets from emu_frame - capture_start_frame - 1: {check.offsets}")
    report(
        f"pixel-equal rows {check.rows[0]}..{check.rows[1]}: min {check.pixel_equal.min:.4%}, "
        f"median {check.pixel_equal.median:.4%}; exact {check.exact_pages}, "
        f"split {check.split_pages}, band {check.band_pages} of {len(matches)}"
    )
    return 0


def run_stream_check(directory: Path, film: str, root: Path, search: int) -> int:
    """Compare *directory*'s stream with *film*'s pinned frame capture; writes nothing."""
    capture = load_video_capture(directory)
    with references.open_reference(root, film) as held:
        matches, skipped = video_check.stream_page_matches(directory, capture, held, search=search)
    check = video_check.summarise_stream(matches, skipped)
    report(f"{film}: {check.pages} pages ({check.skipped} skipped), stream from {directory}")
    report(f"offsets from emu_frame: {check.offsets}")
    report(
        f"exact {check.exact_pages}, on held frames {check.on_held_pages}, "
        f"palette equal {check.palette_equal_pages} of {len(matches)} compared"
    )
    return 0


def run_replay(first: Path, second: Path) -> int:
    """Report whether two recordings are identical; 1 when they differ."""
    replay = video_check.replay_report(first, second)
    report(f"AVI bytes identical: {replay.video_identical}")
    report(f"meta.json bytes identical: {replay.meta_identical}")
    if replay.stream_identical is None:
        report("stream: not compared (a recording lacks stream.json)")
    else:
        report(f"stream hashes identical: {replay.stream_identical}")
    for column, index in replay.differing.items():
        report(f"differs: {column} (first at {index})")
    return 0 if replay.identical else 1


def run_pairing(directory: Path, render: Path | None, key_row: str, *, stream: bool) -> int:
    """Test the pairing rule on *directory*'s run-end frames, pictures from the stream if asked."""
    capture = load_video_capture(directory)
    derived = read_video_derived(directory)
    store = RenderStore(render) if render is not None else None
    check = video_check.pairing_check(
        directory,
        capture,
        derived.frames.render_tick,
        store=store,
        key_row=key_row,
        stream=video_check.load_stream(directory) if stream else None,
    )
    report(
        f"{check.runs} runs of one slot_clock, {check.multi_frame_runs} of two or more frames, "
        f"slot_ticks varies in {check.ticks_vary} of those; words from the {key_row} row"
    )
    report(
        f"{check.frames} frames, {check.run_ends} run ends, {check.in_palette_window} in a "
        f"palette write's lag window, {check.compared} compared"
    )
    for name, groups in (("render_tick", check.by_render_tick), ("film_tick", check.by_film_tick)):
        report(
            f"key {name}: {groups.shared} shared keys, {groups.conflicting} name more than one "
            f"picture ({groups.conflicting_frames} frames)"
        )
    report(f"render_tick falls between consecutive compared frames: {check.render_tick_falls}")
    if stream:
        report(f"stream: {check.held_dropped} run-end rows on held frames left out")
    if check.render is not None:
        pairing = check.render
        report(
            f"render, {pairing.compared} frames: best offset from render_tick {pairing.best_offset}"
        )
        report(f"mean SSIM by offset {pairing.mean_ssim}")
        report(
            f"tag SSIM {pairing.tag_ssim:.4f}; rule no lower on {pairing.rule_not_worse}, "
            f"higher on {pairing.rule_better_where_differs} of {pairing.tag_differs} frames "
            "where the tag differs"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand; 0 done, 1 recordings differ, 2 refused."""
    args = parse_args(argv)
    root = dataroot.data_root_flag(args.data_root)
    try:
        if args.command == "replay":
            return run_replay(args.first, args.second)
        directory = resolve_dir(args, root)
        if args.command == "derive":
            return run_derive(directory)
        if args.command == "reference-check":
            if args.stream:
                return run_stream_check(directory, args.film, root, args.search)
            return run_reference_check(directory, args.film, root, args.search)
        run_derive(directory)
        return run_pairing(directory, args.render, args.key_row, stream=args.stream)
    except (ValueError, references.ReferenceCaptureError, video_check.VideoCheckError) as err:
        print(f"video-derive: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
