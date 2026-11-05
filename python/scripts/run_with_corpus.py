"""Run a command with ``STUNT_CORPUS`` naming the corpus the data root resolves to.

Usage: python python/scripts/run_with_corpus.py <command> [args...]

``dataroot`` is the one place that finds the game files: ``STUNT_DATA_ROOT``, else
``<primary>.data``, else the primary checkout's own ``corpus/`` (ADR 0036). The Rust readers
(``stuntreel sod-census`` and the corpus tests) take the result from this variable, so the
rule is not written again in Rust or in a mise template, and the path never passes through
a shell, where a ``$(...)`` or a quote in it would run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from stunt_reel import dataroot

#: The variable the Rust corpus readers take the corpus directory from.
CORPUS_ENV = "STUNT_CORPUS"


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write("usage: run_with_corpus.py <command> [args...]\n")
        return 2
    # Resolved here, not by CreateProcess, so a .cmd shim on PATH is found as a shell finds it.
    command = shutil.which(argv[0]) or argv[0]
    env = {**os.environ, CORPUS_ENV: str(dataroot.corpus_root())}
    return subprocess.run([command, *argv[1:]], env=env, check=False).returncode  # noqa: S603


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
