"""The command-line surface ``parity_run.py`` and ``parity_sweep.py`` share.

Five flags mean the same thing in both scripts, and so does the ``--films`` contract.
They are defined once here so help text, defaults and refusals cannot drift apart; a flag
that only one of the two takes stays in that script.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ParityOptions",
    "UsageError",
    "add_parity_options",
    "parity_options",
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


def add_parity_options(
    parser: argparse.ArgumentParser, *, films: Mapping[str, object], data_root: Path
) -> None:
    """Add ``--films``, ``--data-root``, ``--no-build``, ``--reuse`` and ``--retime``."""
    parser.add_argument("--films", default=",".join(films), help="comma list; default: all")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=data_root,
        help="score another checkout's corpus and captures; this one is linked on first read",
    )
    parser.add_argument("--no-build", action="store_true", help="reuse the release binary")
    parser.add_argument(
        "--reuse", type=Path, default=None, help="score DIR/<film> without rendering"
    )
    parser.add_argument(
        "--retime", type=int, default=None, metavar="N", help="relabel each film by N ticks"
    )


def parity_options(args: argparse.Namespace, *, films: Mapping[str, object]) -> ParityOptions:
    """Validate the shared flags and resolve the data root."""
    names = [name.strip() for name in str(args.films).split(",") if name.strip()]
    unknown = [name for name in names if name not in films]
    if unknown or not names:
        raise UsageError(f"--films must be from {', '.join(films)}, got {args.films!r}")
    return ParityOptions(
        films=tuple(names),
        data_root=Path(args.data_root).resolve(),
        no_build=bool(args.no_build),
        reuse=args.reuse,
        retime=args.retime,
    )
