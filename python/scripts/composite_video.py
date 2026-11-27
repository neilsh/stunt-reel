"""Compose one labelled video of a reference film shown several ways, its panels in a grid.

Each view is a panel: ``capture`` is the film's reference capture (PLAYONE's frames, each held
until the next, starting at the render tick the scorer pairs it with), and ``mode13h``,
``modern`` and ``diagnostic`` are ``stuntreel --look`` renders of the film at the parity
geometry. The panels play on one clock in real time, scaled up without smoothing and labelled.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
lazy from collections.abc import Sequence

from PIL import Image

from stunt_reel import all_archive, dataroot, parity_pipeline
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.link import binary_path
from stunt_reel.parity_artifacts import read_capture, read_capture_palette

#: Every view a panel can show, with its label.
VIEWS = {
    "capture": "Capture (PLAYONE)",
    "diagnostic": "Diagnostic",
    "mode13h": "Classic (Mode 13h)",
    "modern": "Modern",
}
#: Film ticks per second.
TICK_HZ = 50
#: The capture's last frame is held this many ticks.
LAST_HOLD_TICKS = TICK_HZ
#: Label fonts tried in order (Linux, then Windows); with none, fontconfig's sans.
FONT_FILES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments; ``views`` becomes a list of known view names."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--film", default="ctry", help="the research/parity/references.toml row (default ctry)"
    )
    parser.add_argument(
        "--views",
        default="capture,diagnostic,mode13h,modern",
        help=f"comma-separated panels in reading order, from {', '.join(VIEWS)} "
        "(default %(default)s)",
    )
    parser.add_argument(
        "--columns",
        type=int,
        default=None,
        help="panels per row (default 2 for four views, else all in one row)",
    )
    parser.add_argument(
        "--scale", type=int, default=3, help="pixel scale of each 320x200 panel (default 3)"
    )
    parser.add_argument("--fps", type=int, default=25, help="output frame rate (default 25)")
    parser.add_argument(
        "--software-only", action="store_true", help="render on lavapipe even beside a GPU"
    )
    parser.add_argument(
        "--data-root", type=Path, default=None, help="data root (default: the configured one)"
    )
    parser.add_argument("--out", type=Path, required=True, help="the video to write (.mp4)")
    args = parser.parse_args(argv)
    args.views = [view.strip() for view in args.views.split(",") if view.strip()]
    unknown = [view for view in args.views if view not in VIEWS]
    if unknown or not args.views:
        parser.error(f"unknown or no views {unknown}; choose from {', '.join(VIEWS)}")
    if args.columns is not None and args.columns < 1:
        parser.error("--columns must be at least 1")
    if args.scale < 1 or args.fps < 1:
        parser.error("--scale and --fps must be at least 1")
    return args


def hold_seconds(render_ticks: Sequence[int]) -> list[float]:
    """How long each capture frame shows: from its tick (the first from 0) to the next one's."""
    starts = [0, *render_ticks[1:]]
    ends = [*render_ticks[1:], render_ticks[-1] + LAST_HOLD_TICKS]
    return [(end - start) / TICK_HZ for start, end in zip(starts, ends, strict=True)]


def concat_listing(names: Sequence[str], seconds: Sequence[float]) -> str:
    """An ffmpeg concat list showing each image in *names* for its *seconds*."""
    lines = []
    for name, duration in zip(names, seconds, strict=True):
        lines += [f"file '{name}'", f"duration {duration:.4f}"]
    # The concat demuxer drops the last entry's duration unless the file is listed again.
    lines.append(f"file '{names[-1]}'")
    return "\n".join(lines) + "\n"


def filter_graph(labels: Sequence[str], columns: int, scale: int, fps: int, font: str) -> str:
    """The ``-filter_complex`` that scales, labels and lays out one input per label as ``[out]``."""
    width, height = 320 * scale, 200 * scale
    filters = []
    for index, label in enumerate(labels):
        text = label.replace("\\", "").replace("'", "").replace(":", r"\:")
        filters.append(
            f"[{index}:v]fps={fps},scale={width}:{height}:flags=neighbor,setsar=1,"
            f"drawtext={font}:text='{text}':x={4 * scale}:y={4 * scale}:fontsize={8 * scale}:"
            f"fontcolor=white:box=1:boxcolor=black@0.6:boxborderw={2 * scale}[p{index}]"
        )
    if len(labels) == 1:
        return filters[0].removesuffix("[p0]") + "[out]"
    layout = "|".join(
        f"{(index % columns) * width}_{(index // columns) * height}" for index in range(len(labels))
    )
    panels = "".join(f"[p{index}]" for index in range(len(labels)))
    filters.append(f"{panels}xstack=inputs={len(labels)}:layout={layout}:fill=black[out]")
    return ";".join(filters)


def font_option() -> str:
    """The drawtext font option for this machine."""
    for font in FONT_FILES:
        if font.is_file():
            # A drive letter's colon would end the option, so it is escaped.
            return "fontfile='" + font.as_posix().replace(":", r"\:") + "'"
    return "font=Sans"


def capture_clip(capture: Path, out: Path, work: Path) -> None:
    """Write the capture directory's frames as a video on the render clock."""
    frames = read_capture(capture).frames
    names = []
    for index, frame in enumerate(frames):
        palette = read_capture_palette(capture / frame.palette_file)
        image = Image.frombytes("P", (320, 200), (capture / frame.frame_file).read_bytes())
        image.putpalette([channel for rgb in palette for channel in rgb])
        name = f"capture_{index:04d}.png"
        image.convert("RGB").save(work / name)
        names.append(name)
    listing = work / "capture.txt"
    listing.write_text(concat_listing(names, hold_seconds([frame.render_tick for frame in frames])))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-fps_mode", "vfr", "-pix_fmt", "yuv420p", str(out)])  # fmt: skip


def render_clip(
    job: parity_pipeline.FilmJob, look: str, out: Path, args: argparse.Namespace
) -> None:
    """Render the whole film in *look* to the video *out*."""
    archive = all_archive.resolve_all(
        job.flm,
        REPO_ROOT,
        job.slug,
        link_build=all_archive.link_build_in(REPO_ROOT, build=False),
        pinned=job.all_sha256,
        data=job.root,
    )
    argv = [
        str(binary_path()), "--headless", str(job.flm), "--all", str(archive),
        "--sidata", str(dataroot.corpus_of(job.root) / parity_pipeline.SIDATA),
        *parity_pipeline.RENDER_FLAGS, "--look", look, "--fps", str(args.fps), "--video", str(out),
    ]  # fmt: skip
    if args.software_only:
        argv.append("--software-only")
    run(argv)


def run(argv: list[str]) -> None:
    """Run *argv*, raising on failure."""
    subprocess.run(argv, check=True)  # noqa: S603 - our binary and ffmpeg, argv from flags


def main(argv: list[str] | None = None) -> int:
    """Render each view, then compose them into ``--out``."""
    args = parse_args(argv)
    root = dataroot.data_root_flag(args.data_root)
    if any(view != "capture" for view in args.views):
        parity_pipeline.build_release()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with (
        parity_pipeline.reference_job(root, args.film) as job,
        tempfile.TemporaryDirectory() as scratch,
    ):
        work = Path(scratch)
        clips = []
        for view in args.views:
            clip = work / f"{view}.mp4"
            if view == "capture":
                capture_clip(job.capture, clip, work)
            else:
                render_clip(job, view, clip, args)
            clips.append(clip)
        columns = args.columns or (2 if len(clips) == 4 else len(clips))
        graph = filter_graph(
            [VIEWS[view] for view in args.views], columns, args.scale, args.fps, font_option()
        )
        argv = ["ffmpeg", "-y", "-v", "error"]
        for clip in clips:
            argv += ["-i", str(clip)]
        run([*argv, "-filter_complex", graph, "-map", "[out]", "-c:v", "libx264", "-crf", "18",
             "-pix_fmt", "yuv420p", str(args.out)])  # fmt: skip
    print(f"composite-video: wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
