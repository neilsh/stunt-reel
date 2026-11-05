"""Play a Stunt Island film in PLAYONE.EXE on dosbox-automation, for a person to watch.

Stages the film (with its sibling .ALL) under the data root, launches the emulator with the
key presses that pick the film, and then leaves the window to the user until it is closed.
Reads a proprietary executable from the local, gitignored corpus/.

Usage: mise run play [-- --film corpus/stisldem/VAULT/CTRY.FLM]
"""

from __future__ import annotations

import argparse

from stunt_reel import capture_run, dataroot, parity_layout, references
from stunt_reel.dataroot import data_path_arg
from stunt_reel.tac import automation, luagen, playone

#: Seconds the key script may take (boot to the film dialog, then the key presses).
KEYS_TIMEOUT: float = 120.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--film",
        type=data_path_arg,
        default=dataroot.DEFAULT_FILM,
        help="film to play",
    )
    parser.add_argument(
        "--game-root",
        type=data_path_arg,
        default=None,
        help="game tree whose PLAYONE.EXE to run, such as <data root>/builds/patch3",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    """Stage the film, pick it in the dialog and wait for the window to be closed."""
    film = args.film if args.film.is_absolute() else dataroot.REPO_ROOT / args.film
    root = args.game_root
    if root is not None and not root.is_absolute():
        root = dataroot.REPO_ROOT / root
    try:
        with capture_run.staged_film(film, root) as staged:
            # The film's row in references.toml names the builds it may play on (ADR 0029); a
            # film with no row is not checked, so its PLAYONE need not be a known build.
            try:
                slug: str | None = parity_layout.slug_for(film)
            except ValueError:
                slug = None  # no valid slug, so no row can name this film
            if slug is not None and references.read_builds(dataroot.REPO_ROOT, slug) is not None:
                references.require_builds(
                    dataroot.REPO_ROOT,
                    slug,
                    playone=playone.layout_for(staged.mount / "PLAYONE.EXE").name,
                    makeone=references.archive_makeone_build(
                        dataroot.REPO_ROOT, slug, film.with_suffix(".ALL")
                    ),
                )
            emulator = automation.DosboxAutomation(staged.write_conf)
            try:
                client = emulator.start()
                client.run_script(
                    luagen.keys_script(playone.film_selection_names(film.stem)),
                    timeout=KEYS_TIMEOUT,
                )
                emulator.wait()
            finally:
                emulator.stop(10.0)
    except (
        references.ReferenceCaptureError,
        playone.UnknownBuild,
        RuntimeError,
        TimeoutError,
        ValueError,
        OSError,
    ) as exc:
        capture_run.report_failure("play", exc)
        return 1
    return 0


def main() -> int:
    """Run the player."""
    args = parse_args()
    if dataroot.require_corpus_or_report("play") is None:
        return 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
