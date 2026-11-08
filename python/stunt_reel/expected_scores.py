"""A film's parity score beside its committed expected score, and whether it drifted.

``references.toml`` records, for each film and renderer class, the scores a measured commit
reached (``[<film>.expected.<class>]``, read by :mod:`stunt_reel.references`).
:func:`comparison_line` words one report against the entry for its adapter's class: the
expected SSIM and IoU, the SSIM delta, and a drift verdict or the reason there is none.  Drift
is judged on SSIM alone, and only when the two scores compare: the report scored frames on the
adapter the entry names, the run scored this checkout's own render, and :func:`changed_since`
finds nothing under ``crates/`` and neither of the row's pins changed since the measured
commit.  Nothing here prints or chooses an exit status.
"""

from __future__ import annotations

import subprocess
import tomllib
from typing import TYPE_CHECKING

from stunt_reel import parity_layout
from stunt_reel.dataroot import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from stunt_reel.parity_artifacts import Report
    from stunt_reel.references import Reference

__all__ = ["CLASS_KEYS", "changed_since", "comparison_line"]

#: The renderer class (``references.RENDERER_CLASSES``) of each adapter class a report names.
CLASS_KEYS: Mapping[str, str] = {"hardware": "gpu", "cpu": "lavapipe"}

#: Every comparison line is indented under its film's summary line.
_INDENT = " " * 6


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes] | None:
    """``git -C repo args``, or ``None`` when git cannot be started."""
    try:
        return subprocess.run(  # noqa: S603 - fixed git arguments
            ["git", "-C", str(repo), *args],  # noqa: S607 - git from PATH, as every task
            capture_output=True,
            check=False,
        )
    except OSError:
        return None


def _pins_at(repo: Path, commit: str, film: str) -> tuple[object, object] | None:
    """Row *film*'s ``sha256`` and ``all_sha256`` in ``references.toml`` at *commit*, if any."""
    shown = _git(repo, "show", f"{commit}:{parity_layout.REFERENCES_FILE.as_posix()}")
    if shown is None or shown.returncode != 0:
        return None
    try:
        document = tomllib.loads(shown.stdout.decode("utf-8"))
    except UnicodeDecodeError, tomllib.TOMLDecodeError:
        return None
    row = document.get(film)
    if not isinstance(row, dict):
        return None
    return row.get("sha256"), row.get("all_sha256")


def changed_since(commit: str, reference: Reference, *, repo: Path = REPO_ROOT) -> str | None:
    """Why *reference*'s film may score differently in *repo* than at *commit*; ``None`` if not.

    The reasons: *commit* is not in this clone (any git failure reads so); a file under
    ``crates/`` differs from *commit*, tracked or untracked and not ignored; or the film's row
    at *commit* is missing or pins another ``sha256`` or ``all_sha256``.
    """
    short = commit[:7]
    resolved = _git(repo, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
    if resolved is None or resolved.returncode != 0:
        return f"commit {short} is not in this clone"
    full = resolved.stdout.decode("ascii").strip()
    tracked = _git(repo, "diff", "--quiet", full, "--", "crates/")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard", "--", "crates/")
    if tracked is None or untracked is None or tracked.returncode > 1 or untracked.returncode:
        return f"commit {short} is not in this clone"
    if tracked.returncode == 1 or untracked.stdout.strip():
        return f"crates/ changed since {short}"
    if _pins_at(repo, full, reference.film) != (reference.sha256, reference.all_sha256):
        return f"reference pin changed since {short}"
    return None


def comparison_line(
    reference: Reference,
    report: Report,
    *,
    rescored: str | None = None,
    changed: Callable[[str, Reference], str | None] = changed_since,
) -> str:
    """One line, indented six spaces: *report* against *reference*'s expected score.

    *rescored* is the flag (``--retime``, ``--reuse``) when the run scored a tree other than
    this checkout's render. *changed* is :func:`changed_since`, asked only when every earlier
    reason leaves the scores comparable.
    """
    if report.adapter is None:
        return f"{_INDENT}no adapter in the report: re-render to compare"
    renderer = CLASS_KEYS[report.adapter.adapter_class]
    expected = reference.expected.get(renderer)
    if expected is None:
        return f"{_INDENT}no expected score for {renderer} yet: add it"
    scores = f"{_INDENT}{renderer} expected ssim {expected.ssim:.6f}  iou {expected.iou:.6f}"
    if report.mean_ssim_scored is None:
        return f"{scores}  delta n/a  not comparable: no frame scored"
    delta = report.mean_ssim_scored - expected.ssim
    head = f"{scores}  delta {delta:+.6f}"
    if report.adapter.name != expected.adapter:
        reason: str | None = f"other adapter (expected on {expected.adapter})"
    elif rescored is not None:
        reason = f"scored with {rescored}"
    else:
        reason = changed(expected.commit, reference)
    if reason is not None:
        return f"{head}  not comparable: {reason}"
    if reference.noise_sigma is None:
        return f"{head}  drift not judged: {reference.film} has no noise_sigma"
    if abs(delta) > reference.noise_sigma:
        return (
            f"{head}  DRIFT: |delta| {abs(delta):.6f} > noise_sigma "
            f"{reference.noise_sigma:.6f} on {report.adapter.name}"
        )
    return f"{head}  no drift"
