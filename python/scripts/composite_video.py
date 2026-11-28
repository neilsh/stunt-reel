"""Compose one labelled video of a reference film shown several ways, its panels in a grid.

Each view is a panel: ``capture`` is the film's reference capture (PLAYONE's frames, each held
until the next, starting at the render tick the scorer pairs it with), and ``mode13h``,
``modern`` and ``diagnostic`` are ``stuntreel --look`` renders of the film at the parity
geometry. The panels play on one clock in real time, scaled up without smoothing and labelled.

With ``--as-seen`` the capture panel is the film's full-rate video recording instead
(``captures-video/<slug>``): every frame as the emulator recorded it, torn frames included, at the
recording's own rate. Each render panel shows the film tick the frame's ``render_tick`` names.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
lazy from collections.abc import Sequence

import numpy as np
from PIL import Image

from stunt_reel import (
    all_archive,
    batch_films,
    dataroot,
    parity_layout,
    parity_pipeline,
    references,
    video_check,
)
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.link import binary_path
from stunt_reel.parity_artifacts import load_video_capture, read_capture, read_capture_palette

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
#: The recording's frame rate when its ``meta.json`` records none: PLAYONE's, 2190197/31250 Hz.
NATIVE_RATE = (2190197, 31250)
#: A panel's size in pixels before scaling.
PANEL = (320, 200)
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
    parser.add_argument(
        "--as-seen",
        action="store_true",
        help="use every frame of the film's full-rate video recording, torn frames included, "
        "at its own rate (--fps is then ignored)",
    )
    parser.add_argument(
        "--video-dir",
        type=Path,
        default=None,
        help="with --as-seen, the video capture directory (default: the film's captures-video)",
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
    if args.video_dir is not None and not args.as_seen:
        parser.error("--video-dir needs --as-seen")
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
    job: parity_pipeline.FilmJob, look: str, out: Path, args: argparse.Namespace, fps: int
) -> None:
    """Render the whole film in *look* to the video *out*, *fps* samples per second."""
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
        *parity_pipeline.RENDER_FLAGS, "--look", look, "--fps", str(fps), "--video", str(out),
    ]  # fmt: skip
    if args.software_only:
        argv.append("--software-only")
    run(argv)


def grid_filter(labels: Sequence[str], columns: int, scale: int, font: str) -> str:
    """The ``-vf`` that scales a grid of native-size panels and labels each one in place."""
    width, height = PANEL[0] * scale, PANEL[1] * scale
    filters = [f"scale={columns * width}:-1:flags=neighbor", "setsar=1"]
    for index, label in enumerate(labels):
        text = label.replace("\\", "").replace("'", "").replace(":", r"\:")
        x = (index % columns) * width + 4 * scale
        y = (index // columns) * height + 4 * scale
        filters.append(
            f"drawtext={font}:text='{text}':x={x}:y={y}:fontsize={8 * scale}:"
            f"fontcolor=white:box=1:boxcolor=black@0.6:boxborderw={2 * scale}"
        )
    return ",".join(filters)


def lay_out(panels: Sequence[np.ndarray], columns: int) -> np.ndarray:
    """*panels* as rows of *columns*, the last row padded with black."""
    blank = np.zeros_like(panels[0])
    cells = [*panels, *[blank] * (-len(panels) % columns)]
    rows = [
        np.concatenate(cells[at : at + columns], axis=1) for at in range(0, len(cells), columns)
    ]
    return np.concatenate(rows, axis=0)


def tick_panels(clip: Path, ticks: set[int]) -> dict[int, bytes]:
    """The frames of the 50 fps render *clip* at film *ticks*, compressed.

    A tick past the clip's end shows its last frame.
    """
    held: dict[int, bytes] = {}
    last = b""
    for tick, frame in enumerate(video_check.iter_video_frames(clip, *PANEL)):
        last = zlib.compress(frame.tobytes(), 1)
        if tick in ticks:
            held[tick] = last
    return held | {tick: last for tick in ticks if tick not in held}


def native_rate(video: Path) -> tuple[int, int]:
    """The recording's exact frame rate, as ``meta.json`` records it."""
    info = load_video_capture(video).video
    return NATIVE_RATE if info is None else info.frame_rate


def as_seen_job(root: Path, film: str) -> parity_pipeline.FilmJob:
    """The film's ``.FLM`` and archive pin from its ``references.toml`` row, without its capture."""
    pointer = references.read_reference(root, film)
    found = batch_films.find(dataroot.corpus_of(root), pointer.slug)
    if found is None:
        raise parity_pipeline.FilmInputError(
            f"no .FLM of {pointer.slug} under {root} (try --data-root)"
        )
    return parity_pipeline.FilmJob(
        pointer.film, pointer.slug, found.flm, root, root, pointer.sha256, pointer.all_sha256
    )


def compose_as_seen(
    job: parity_pipeline.FilmJob, video: Path, args: argparse.Namespace, work: Path
) -> None:
    """Write ``--out``: each recorded frame beside the renders of the ticks it names."""
    looks = [view for view in args.views if view != "capture"]
    ticks = {frame.render_tick for frame in video_check.iter_capture_frames(video)}
    renders: dict[str, dict[int, bytes]] = {}
    for look in looks:
        clip = work / f"{look}.mp4"
        render_clip(job, look, clip, args, fps=TICK_HZ)
        renders[look] = tick_panels(clip, ticks)
    columns = args.columns or (2 if len(args.views) == 4 else len(args.views))
    graph = grid_filter([VIEWS[view] for view in args.views], columns, args.scale, font_option())
    rate = native_rate(video)
    rows = -(-len(args.views) // columns)
    size = f"{columns * PANEL[0]}x{rows * PANEL[1]}"
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", size,
               "-r", f"{rate[0]}/{rate[1]}", "-i", "-", "-vf", graph, "-c:v", "libx264",
               "-crf", "18", "-pix_fmt", "yuv420p", str(args.out)]  # fmt: skip
    with subprocess.Popen(command, stdin=subprocess.PIPE) as process:  # noqa: S603
        stdin = process.stdin
        if stdin is None:
            raise RuntimeError("ffmpeg gave no input stream")
        try:
            for frame in video_check.iter_capture_frames(video):
                panels = [
                    frame.rgb
                    if view == "capture"
                    else np.frombuffer(
                        zlib.decompress(renders[view][frame.render_tick]), dtype=np.uint8
                    ).reshape(PANEL[1], PANEL[0], 3)
                    for view in args.views
                ]
                stdin.write(lay_out(panels, columns).tobytes())
        finally:
            stdin.close()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command)


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
    if args.as_seen:
        job = as_seen_job(root, args.film)
        video = args.video_dir or root / parity_layout.video_path(job.slug)
        with tempfile.TemporaryDirectory() as scratch:
            compose_as_seen(job, video, args, Path(scratch))
        print(f"composite-video: wrote {args.out}")
        return 0
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
                render_clip(job, view, clip, args, args.fps)
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
