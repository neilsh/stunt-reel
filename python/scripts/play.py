"""Play a Stunt Island film in PLAYONE.EXE on dosbox-automation, for a person to watch.

Stages the film (with its sibling .ALL) under the data root, launches the emulator with the
key presses that pick the film, and then leaves the window to the user until it is closed.
Reads a proprietary executable from the local, gitignored corpus/.

Usage: mise run play [-- --film corpus/stisldem/VAULT/CTRY.FLM]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stunt_reel import dataroot
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.tac import automation, luagen, playone, staging

DEFAULT_FILM: Path = Path("corpus/stisldem/VAULT/CTRY.FLM")
#: Seconds the key script may take (boot to the film dialog, then the key presses).
KEYS_TIMEOUT: float = 120.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--film", type=Path, default=DEFAULT_FILM, help="film to play")
    parser.add_argument(
        "--game-root",
        type=Path,
        default=None,
        help="game tree whose PLAYONE.EXE to run, such as <data root>/builds/patched",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    """Stage the film, pick it in the dialog and wait for the window to be closed."""
    film = args.film if args.film.is_absolute() else dataroot.REPO_ROOT / args.film
    root = args.game_root
    if root is not None and not root.is_absolute():
        root = dataroot.REPO_ROOT / root
    try:
        staged = staging.stage_film(film, root)
    except OSError as exc:
        print(f"[play] {exc}", file=sys.stderr)
        return 1
    emulator = automation.DosboxAutomation(staged.write_conf)
    try:
        client = emulator.start()
        client.run_script(
            luagen.keys_script(playone.film_selection_names(film.stem)), timeout=KEYS_TIMEOUT
        )
        emulator.wait()
    except (automation.ScriptError, RuntimeError, TimeoutError, OSError) as exc:
        print(f"[play] {exc}", file=sys.stderr)
        return 1
    finally:
        emulator.stop(10.0)
        staging.unstage(staged)
    return 0


def main() -> int:
    """Run the player."""
    if not ensure_links_or_report("play"):
        return 2
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
