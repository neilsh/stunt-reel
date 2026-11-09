"""A film's parity score beside its committed expected score, and whether it drifted.

``references.toml`` records, for each film and renderer class, the scores reached on a measured
``crates/`` tree (``[<film>.expected.<class>]``, read by :mod:`stunt_reel.references`).
:func:`comparison_line` words one report against the entry for its adapter's class: the
expected SSIM and IoU, the SSIM delta, and a drift verdict or the reason there is none.  Drift
is judged on SSIM alone, and only when the two scores compare: the report scored frames on the
adapter the entry names, the run scored this checkout's own render, and :func:`changed_since`
finds this checkout's ``crates/`` tree and the row's pins to be the ones measured.  Nothing
here prints or chooses an exit status.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.git_env import isolated_env

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from stunt_reel.parity_artifacts import Report
    from stunt_reel.references import Expected, Reference

__all__ = ["CLASS_KEYS", "changed_since", "comparison_line", "crates_tree"]

#: The renderer class (``references.RENDERER_CLASSES``) of each adapter class a report names.
CLASS_KEYS: Mapping[str, str] = {"hardware": "gpu", "cpu": "lavapipe"}

#: Every comparison line is indented under its film's summary line.
_INDENT = " " * 6


def _git(
    repo: Path, *args: str, index: Path | None = None
) -> subprocess.CompletedProcess[bytes] | None:
    """``git -C repo args`` on *repo*'s own repository; ``None`` if git cannot start.

    Git reads *repo*'s own index, or *index* when given; the caller's environment cannot point
    it elsewhere.
    """
    env = isolated_env(keep_index=False)
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    try:
        return subprocess.run(  # noqa: S603 - fixed git arguments
            ["git", "-C", str(repo), *args],  # noqa: S607 - git from PATH, as every task
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None


def crates_tree(repo: Path = REPO_ROOT) -> str | None:
    """The tree hash *repo*'s ``crates/`` would have if committed now; ``None`` if git fails.

    It covers the working tree: tracked files as they are on disk and untracked files git does
    not ignore.  On a clean checkout it is ``git rev-parse HEAD:crates``.  It is built in a
    scratch index seeded from ``HEAD``, so *repo*'s own index is untouched; the blobs of changed
    files land in its object store.  A ``crates/`` with no file left is the empty tree.
    """
    with tempfile.TemporaryDirectory(prefix="crates-tree-") as scratch:
        index = Path(scratch) / "index"
        for args in (("read-tree", "HEAD"), ("add", "--all", "--", "crates/")):
            done = _git(repo, *args, index=index)
            if done is None or done.returncode != 0:
                return None
        root = _git(repo, "write-tree", index=index)
    if root is None or root.returncode != 0:
        return None
    tree = _git(repo, "rev-parse", "--verify", "--quiet", f"{_text(root)}:crates")
    if tree is not None and tree.returncode == 1:  # no crates/ entry: the empty tree
        tree = _git(repo, "hash-object", "-t", "tree", "--stdin")
    if tree is None or tree.returncode != 0:
        return None
    return _text(tree)


def _text(done: subprocess.CompletedProcess[bytes]) -> str:
    """The one line git printed."""
    return done.stdout.decode("ascii").strip()


def changed_since(
    expected: Expected, reference: Reference, *, repo: Path = REPO_ROOT
) -> str | None:
    """Why *reference*'s film may score differently in *repo* than when *expected* was measured.

    ``None`` when nothing has changed.  The reasons: git cannot hash ``crates/``; its tree
    (:func:`crates_tree`) is not *expected*'s ``crates``; or the film's ``sha256`` or
    ``all_sha256`` is not the one *expected* records.  No commit object is read, so a
    measurement made on a branch that was squash merged still compares.
    """
    found = crates_tree(repo)
    if found is None:
        return "git cannot hash crates/ in this checkout"
    if found != expected.crates:
        return f"crates/ changed: tree {found[:7]}, measured on {expected.crates[:7]}"
    if (expected.sha256, expected.all_sha256) != (reference.sha256, reference.all_sha256):
        return "reference pin changed since the measurement"
    return None


def comparison_line(
    reference: Reference,
    report: Report,
    *,
    rescored: str | None = None,
    changed: Callable[[Expected, Reference], str | None] = changed_since,
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
    scores = f"{_INDENT}{renderer} expected ssim {expected.ssim:.7f}  iou {expected.iou:.7f}"
    if report.mean_ssim_scored is None:
        return f"{scores}  delta n/a  not comparable: no frame scored"
    delta = report.mean_ssim_scored - expected.ssim
    head = f"{scores}  delta {delta:+.7f}"
    if report.adapter.name != expected.adapter:
        reason: str | None = f"other adapter (expected on {expected.adapter})"
    elif rescored is not None:
        reason = f"scored with {rescored}"
    else:
        reason = changed(expected, reference)
    if reason is not None:
        return f"{head}  not comparable: {reason}"
    if reference.noise_sigma is None:
        return f"{head}  drift not judged: {reference.film} has no noise_sigma"
    if abs(delta) > reference.noise_sigma:
        return (
            f"{head}  DRIFT: |delta| {abs(delta):.7f} > noise_sigma "
            f"{reference.noise_sigma:.7f} on {report.adapter.name}"
        )
    return f"{head}  no drift"
