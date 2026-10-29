"""Where the parity artifacts live, and the rule for what the rotation may delete.

Every path here is relative; callers join it with the root they mean: renders, reports and
staging are per checkout, while a capture lives in the shared data root and is linked into
the checkout (ADR 0008 governs those links). Nothing here resolves a root, touches the
filesystem, or decides how a capture runs; it answers "where", so no caller spells the
layout again.

The rotation's rule lives here too. :data:`RENDER_ROOTS` holds the roots whose child
directories are throwaway render trees, and :func:`is_protected_render` names the ones that
hold a baseline and must survive. The prior render is not a protected *suffix*: it is
:func:`previous_dir`, a root the rotation never scans.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "BASE_SUFFIX",
    "CURRENT_SUFFIX",
    "PROTECTED_SUFFIXES",
    "RENDER_ROOTS",
    "capture_dir",
    "capture_root",
    "is_protected_render",
    "manual_report_dir",
    "previous_dir",
    "render_dir",
    "render_scratch_dir",
    "report_dir",
    "retime_dir",
    "stage_conf",
    "stage_dir",
    "stage_root",
    "sweep_root",
]

#: The two roots every other location derives from; the only literals the layout spells.
_PARITY = Path("build/parity")
_SCRATCH = Path("build/scratch")

_CAPTURE = _PARITY / "reference"
_RENDER = _PARITY / "ours"
_REPORT = _PARITY / "report"
_PREVIOUS = _PARITY / "previous"
_STAGE = _PARITY / "stage"
_RENDER_SCRATCH = _SCRATCH / "parity"
_RETIME = _SCRATCH / "retime"
_SWEEP = _SCRATCH / "sweep"

#: The suffix of the latest render and report pair, ``<film>_current``.
CURRENT_SUFFIX = "_current"
#: The suffix of a pinned baseline a reader copies by hand, ``<film>_base``.
BASE_SUFFIX = "_base"
#: Directory-name suffixes under :data:`RENDER_ROOTS` that hold a baseline, not a scratch tree.
#:
#: A ``_previous`` suffix would match nothing the run writes: the prior render is renamed to
#: :func:`previous_dir`, a root the rotation does not scan.
PROTECTED_SUFFIXES: tuple[str, ...] = (CURRENT_SUFFIX, BASE_SUFFIX)

#: Roots whose child directories are throwaway render trees a rotation may remove.
RENDER_ROOTS: tuple[Path, ...] = (_RENDER, _SWEEP)


def _film_name(film: str) -> str:
    """The lower-case name a film contributes to a directory."""
    return film.lower()


def capture_root() -> Path:
    """The directory holding every capture; the shared data root links it into a checkout."""
    return _CAPTURE


def capture_dir(film: str) -> Path:
    """The capture directory of *film*, relative to the data root."""
    return _CAPTURE / _film_name(film)


def render_dir(film: str) -> Path:
    """The latest render of *film*, relative to the checkout."""
    return _RENDER / f"{_film_name(film)}{CURRENT_SUFFIX}"


def previous_dir(film: str) -> Path:
    """The prior render of *film*, kept by a rename in a root the rotation does not scan."""
    return _PREVIOUS / _film_name(film)


def report_dir(film: str, suffix: str = "") -> Path:
    """The latest report of *film*: ``<report root>/<film>_current<suffix>``.

    *suffix* distinguishes a retimed copy from the baseline. A hand-run report that omits the
    baseline suffix is :func:`manual_report_dir`.
    """
    return _REPORT / f"{_film_name(film)}{CURRENT_SUFFIX}{suffix}"


def manual_report_dir(film: str) -> Path:
    """A hand-run report of *film*, named for the film rather than the managed baseline.

    ``docs/development.md`` writes this directory with a direct ``stuntreel parity --output``;
    ``mise run parity`` writes the ``_current`` baseline that :func:`report_dir` names.
    """
    return _REPORT / _film_name(film)


def render_scratch_dir(film: str) -> Path:
    """The throwaway render of *film* before it replaces :func:`render_dir`."""
    return _RENDER_SCRATCH / _film_name(film)


def retime_dir(film: str, suffix: str = "") -> Path:
    """The throwaway retimed copy of *film*; *suffix* is the caller's retime marker."""
    return _RETIME / f"{_film_name(film)}{CURRENT_SUFFIX}{suffix}"


def stage_dir(film: str, label: str) -> Path:
    """The DOSBox-X mount that stages *film* alone for one session (ADR 0021)."""
    return _STAGE / f"{_film_name(film)}-{label}"


def stage_conf(film: str, label: str) -> Path:
    """The generated conf beside :func:`stage_dir` that mounts it."""
    return _STAGE / f"stage-{_film_name(film)}-{label}.conf"


def stage_root() -> Path:
    """The directory holding the stage mounts and their generated confs."""
    return _STAGE


def sweep_root() -> Path:
    """The directory holding a candidate sweep's variant render trees."""
    return _SWEEP


def is_protected_render(name: str) -> bool:
    """True when a name under :data:`RENDER_ROOTS` holds a baseline the rotation must keep."""
    return name.endswith(PROTECTED_SUFFIXES)
