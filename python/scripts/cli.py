"""The command-line surface ``parity_run.py`` and ``parity_sweep.py`` share.

Five flags mean the same thing in both scripts, and so does the ``--films`` contract.
They are defined once here so help text, defaults and refusals cannot drift apart; a flag
that only one of the two takes stays in that script.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from stunt_reel import dataroot, references

__all__ = [
    "DEFAULT_JOBS",
    "ParityOptions",
    "UsageError",
    "add_parity_options",
    "parity_options",
    "resolve_jobs",
]


class UsageError(ValueError):
    """An invocation the parity scripts refuse before doing any work.

    It stays a ``ValueError`` so ``parity_sweep.main``'s existing refusal path keeps
    catching the options it validates itself.
    """


@dataclass(frozen=True)
class ParityOptions:
    """The options both parity scripts accept, parsed and resolved."""

    films: tuple[str, ...]
    data_root: Path
    no_build: bool
    reuse: Path | None
    retime: int | None
    jobs: int | None


#: The most pairs run at once by default: about 3x one job's throughput on an 8-core machine with
#: an RTX 4070, at about 300 MiB of RAM and 200 MiB of VRAM per job (research/parity/method.md).
DEFAULT_JOBS = 8


def resolve_jobs(requested: int | None, pairs: int) -> int:
    """How many (variant, film) pairs run at once: *requested*, else the default, never above *pairs*."""
    wanted = requested if requested is not None else min(DEFAULT_JOBS, os.cpu_count() or 1)
    return max(1, min(wanted, pairs))


def _positive_int(text: str) -> int:
    """``--jobs``: a whole number of at least 1."""
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a whole number of at least 1, got {text!r}")
    return value


def add_parity_options(parser: argparse.ArgumentParser) -> None:
    """Add ``--films``, ``--data-root``, ``--no-build``, ``--reuse``, ``--retime`` and ``--jobs``.

    ``--films`` defaults to every film the data root's ``references.toml`` pins, resolved by
    :func:`parity_options` once ``--data-root`` is known; without the flag the configured data
    root is read, with the primary checkout's ``corpus/`` as its fallback (ADR 0036).
    """
    parser.add_argument(
        "--films", default=None, help="comma list; default: every film references.toml pins"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="read the corpus and captures from DIR, as STUNT_DATA_ROOT=DIR would",
    )
    parser.add_argument("--no-build", action="store_true", help="reuse the release binary")
    parser.add_argument(
        "--reuse", type=Path, default=None, help="score DIR/<film> without rendering"
    )
    parser.add_argument(
        "--retime", type=int, default=None, metavar="N", help="relabel each film by N ticks"
    )
    parser.add_argument(
        "--jobs",
        type=_positive_int,
        default=None,
        metavar="N",
        help=(
            f"render and score N (variant, film) pairs at once; default {DEFAULT_JOBS}, capped by "
            "cores and pairs; each job takes about 300 MiB of RAM and 200 MiB of VRAM"
        ),
    )


def parity_options(args: argparse.Namespace) -> ParityOptions:
    """Validate the shared flags against the films the resolved data root pins."""
    root = dataroot.data_root_flag(args.data_root)
    films = references.reference_films(root)
    if args.films is None:
        names = list(films)
    else:
        names = [name.strip() for name in str(args.films).split(",") if name.strip()]
    unknown = [name for name in names if name not in films]
    if unknown or not names:
        raise UsageError(f"--films must be from {', '.join(films)}, got {args.films!r}")
    return ParityOptions(
        films=tuple(names),
        data_root=root,
        no_build=bool(args.no_build),
        reuse=args.reuse,
        retime=args.retime,
        jobs=args.jobs,
    )
