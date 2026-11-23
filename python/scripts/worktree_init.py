"""Prepare or clean one git worktree.

A worktree needs no provisioning (ADR 0036): code reads the data root directly, mise
names the shared caches by absolute path, and ``ensure``, a dependency of every task
that builds Rust, makes the scratch folder, seeds an empty ``target/`` and sets
``core.hooksPath`` and ``blame.ignoreRevsFile`` under a lock.
``mise run init`` does the same eagerly with a full report, runs ``uv sync``, and names
any link an older ``init`` left, which ``reap`` unlinks.  ``mise run
clean`` reports the per-worktree build outputs and
removes them only with ``--yes``; the shared cache is reported, never removed.
``clean -- --parity --keep N`` narrows the same command to the parity render trees,
which accumulate one directory per render and are the one build output big enough to
need selective rotation.  ``reap`` removes merged worktrees, including branches whose pull
request was squash-merged (found with ``gh``): it unlinks every link
into the data root, proves none remain, and only then lets git delete the checkout,
because git's worktree removal has recursed through Windows junctions on some builds.
``review`` makes a reviewer's detached worktree under the primary checkout (issue #981).
The seed clones another checkout's built ``target/`` into an empty one on a ReFS volume, so
the first build compiles only the workspace crates (ADR 0030).
The script runs on the pinned Python, never whichever ``python`` PATH finds first: an interpreter
older than ``pyproject.toml``'s ``requires-python`` floor cannot parse the package's ``lazy from``
imports, so ``python_pin.guard`` runs the script again on the one ``mise which python`` names, or
reports the interpreter it found (issue #854).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import python_pin


def main(argv: list[str] | None = None) -> int:
    """Run ``init``, ``seed``, ``ensure``, ``clean``, ``review`` or ``reap``."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    status = python_pin.guard(Path(__file__).resolve(), arguments)
    if status is not None:
        return status
    # Below the guard: these modules use `lazy from` (Python 3.15), so importing one above it
    # raises SyntaxError on an older `python` before the guard can report anything (issue #854).
    from stunt_reel.worktree_clean import _clean  # noqa: PLC0415
    from stunt_reel.worktree_ensure import _ensure, _seed_command  # noqa: PLC0415
    from stunt_reel.worktree_provision import _init  # noqa: PLC0415
    from stunt_reel.worktree_reap import (  # noqa: PLC0415
        DEFAULT_MIN_FREE_GB,
        REVIEW_QUIET_HOURS,
        _reap,
    )
    from stunt_reel.worktree_review import _review  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="seed target/, set core.hooksPath and uv sync now, and report old links"
    )
    init.add_argument(
        "--migrate",
        action="store_true",
        help="convert an old-layout shared root, then move existing in-checkout data into it",
    )
    commands.add_parser("seed", help="clone another checkout's built target/ into an empty one")
    commands.add_parser(
        "ensure", help="seed an empty target/ and set core.hooksPath and the merge driver, quietly"
    )
    clean = commands.add_parser("clean", help="report or remove per-worktree build outputs")
    clean.add_argument("--yes", action="store_true", help="actually remove them")
    clean.add_argument(
        "--parity",
        action="store_true",
        help="only report or rotate the parity render trees under build/",
    )
    clean.add_argument("--keep", type=int, default=1, help="render trees to keep per root")
    review = commands.add_parser(
        "review",
        help="make a detached review worktree for a PR number or commit SHA under the primary checkout",
    )
    review.add_argument(
        "target", help="a PR number (its head is fetched from origin) or a commit SHA"
    )
    reap = commands.add_parser(
        "reap",
        help="remove merged or squash-merged worktrees after unlinking their data-root links",
    )
    reap.add_argument("--yes", action="store_true", help="actually remove them")
    reap.add_argument(
        "--cherry",
        action="store_true",
        help="also reap worktrees whose patches main already holds without a merge",
    )
    reap.add_argument(
        "--prune",
        action="store_true",
        help="also remove unregistered pool dirs and branches left without a worktree",
    )
    reap.add_argument(
        "--reviews",
        action="store_true",
        help=(
            "also reap a detached review-* worktree nothing under it or in its git dir"
            f" changed for {REVIEW_QUIET_HOURS} hours"
        ),
    )
    reap.add_argument(
        "--stash-dirty",
        action="store_true",
        help="stash a worktree's modified files instead of refusing",
    )
    reap.add_argument(
        "--discard-untracked",
        action="store_true",
        help="delete a worktree's untracked files instead of refusing",
    )
    reap.add_argument("--force", action="store_true", help="reap even when the drive has room")
    reap.add_argument(
        "--allow-stale-script",
        action="store_true",
        help="reap even when the files it runs differ from origin/main's",
    )
    reap.add_argument(
        "--min-free-gb",
        type=float,
        default=DEFAULT_MIN_FREE_GB,
        help="reap only when the drive has under this many GB free (default %(default)g)",
    )
    args = parser.parse_args(arguments)
    if args.command == "init":
        return _init(bool(args.migrate))
    if args.command == "ensure":
        return _ensure()
    if args.command == "seed":
        return _seed_command()
    if args.command == "review":
        return _review(str(args.target))
    if args.command == "reap":
        if float(args.min_free_gb) < 0:
            parser.error("--min-free-gb must not be negative")
        return _reap(
            bool(args.yes),
            include_cherry=bool(args.cherry),
            prune=bool(args.prune),
            stash_dirty=bool(args.stash_dirty),
            discard_untracked=bool(args.discard_untracked),
            force=bool(args.force),
            min_free_gb=float(args.min_free_gb),
            allow_stale_script=bool(args.allow_stale_script),
            reviews=bool(args.reviews),
        )
    if int(args.keep) < 0:
        parser.error("--keep must not be negative")
    return _clean(bool(args.yes), parity=bool(args.parity), keep=int(args.keep))


if __name__ == "__main__":
    sys.exit(main())
