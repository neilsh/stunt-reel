"""Measure, pin and post the class agreement: where lavapipe and the GPU draw a film differently (#908).

Usage::

    mise run agreement -- measure --gpu ROOT --lavapipe ROOT [--gpu-driver V] [--lavapipe-driver V]
    mise run agreement -- pin [--accept REASON]
    mise run agreement -- batch [--if-due] [--post] [--lavapipe-command CMD]
                                [--lavapipe-driver-command CMD]

``measure`` reads two roots laid out as ``build/parity`` is, ``ours/<film>_current`` render stores
beside ``report/<film>_current/report.json``, one drawn on the GPU and one on lavapipe, from one
``crates`` tree. It prints each reference film's residue and SSIM gap (GPU minus lavapipe
``mean_ssim_scored``), then each flag against the pinned ``agreement.toml``, or why none was
computed, and keeps the measurement in ``build/agreement/`` for ``pin``. Exit 1 when a film is
missing, its tick sets differ, or the reports disagree on the tree; 2 on a refused invocation.

``pin`` refuses a measurement with flags, or with a reason in place of flags (nothing pinned yet,
or another adapter or driver), unless ``--accept REASON``; it then runs ``mise run parity-repin --
--class gpu``, writes ``agreement.toml`` (``accepted`` holding the reason), and commits both on a
branch ``chore/agreement-<date>`` with a pull request. It writes nothing when the checkout's
``crates`` tree is not the measured one.

``batch`` skips, exit 0, while a ``stuntreel`` process runs, since two full renders at once slow
both. Otherwise it updates the worktree ``.agents/worktrees/agreement`` to ``origin/main``
(detached), and with ``--if-due`` stops there, exit 0, unless a batch is due. It renders there
with ``--lavapipe-command`` (default ``mise run parity -- --software-only``; it must leave its
renders and reports in the worktree's ``build/parity``), keeps them as ``build/agreement/lavapipe``,
renders on the GPU with ``mise run parity``, then measures, and pins when nothing flags.
With ``--if-due`` it also skips a tree it has already measured, or whose pin branch
(``chore/agreement-<tree>``) is on ``origin``, so a flagged or unmerged tree is rendered once;
a pin branch left behind by a closed pull request holds its tree until the next renderer commit.
``--post`` comments the result on the open ``Class agreement batch`` issue, once per tree, files
an issue per flag that no open ``class-agreement`` issue covers, and comments a failed
measurement. The defaults suit Linux; on local-windows the canonical lavapipe runs under WSL, so
the job passes ``wsl``-wrapped ``--lavapipe-command`` and ``--lavapipe-driver-command`` (#908).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stunt_reel.class_agreement import (
    AGREEMENT_FILE,
    Agreement,
    FilmAgreement,
    Flag,
    Residue,
    compare,
    due,
    film_stores,
    flags,
    format_agreement,
    read_agreement,
    renderer_commits_since,
)
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.parity_artifacts import ArtifactError, RenderStore, read_report
from stunt_reel.process_tree import stuntreel_running
from stunt_reel.references import reference_films

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from stunt_reel.parity_artifacts import Report

#: The GPU's pinned expected scores, which ``pin`` repins beside the agreement.
GPU_FILE = AGREEMENT_FILE.parent / "gpu.toml"
#: Where ``mise run parity`` leaves its renders and reports, relative to a checkout.
PARITY_DIR = Path("build/parity")
#: Where a measurement and the lavapipe arm's copy are kept, relative to a checkout.
STATE_DIR = Path("build/agreement")
#: The batch's worktree, relative to the primary checkout.
WORKTREE = Path(".agents/worktrees/agreement")
#: The label every agreement issue carries.
LABEL = "class-agreement"
#: The open issue each batch comments on.
STANDING_TITLE = "Class agreement batch"
#: The default command that renders every reference film on the canonical lavapipe.
LAVAPIPE_COMMAND = "mise run parity -- --software-only"
#: The default command that prints the canonical lavapipe package's version.
LAVAPIPE_DRIVER_COMMAND = "dpkg-query -W -f ${Version} mesa-vulkan-drivers"
#: The command that prints the GPU's driver version.
GPU_DRIVER_COMMAND = ("nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader")
#: A tick flag's issue title: its film and tick range.
_TICK_TITLE = re.compile(r"^Agreement: (\S+) ticks (\d+)-(\d+)$")
#: Entries requested per REST page; a shorter page is the last.
PER_PAGE = 100
#: Ends every comment and issue the batch posts.
FOOTER = "\n\n---\n_Posted by `mise run agreement -- batch --post` (#908)._\n"


def _run(argv: Sequence[str], cwd: Path) -> int:
    """Runs *argv* in *cwd*, its output passed through; its exit code, 127 when it cannot start."""
    print(f"agreement: $ {shlex.join(argv)}", flush=True)
    try:
        return subprocess.run(list(argv), cwd=cwd, check=False).returncode  # noqa: S603
    except OSError as err:
        print(f"agreement: {err}", file=sys.stderr)
        return 127


def _output(argv: Sequence[str], cwd: Path) -> str | None:
    """*argv*'s stdout, stripped; ``None`` when it fails or prints nothing."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argument vectors
            list(argv), cwd=cwd, capture_output=True, text=True, errors="replace", check=False
        )
    except OSError:
        return None
    text = done.stdout.strip()
    return text if done.returncode == 0 and text else None


class GhError(RuntimeError):
    """``gh`` failed or returned something other than JSON."""


def _gh(*args: str) -> Any:
    """``gh api <args>``'s stdout parsed as JSON, run in the primary checkout."""
    exe = shutil.which("gh")
    if exe is None:
        raise GhError("gh not found on PATH")
    done = subprocess.run(  # noqa: S603 - gh with fixed arguments
        [exe, "api", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise GhError(done.stderr.strip() or f"gh api exited {done.returncode}")
    try:
        return json.loads(done.stdout or "null")
    except json.JSONDecodeError as err:
        raise GhError(f"gh api returned no JSON: {err}") from err


def _commits(tree: str, repo: Path) -> list[str] | None:
    return renderer_commits_since(tree, rev="HEAD", repo=repo)


@dataclass
class Tools:
    """The side effects a command has, replaced in tests."""

    run: Callable[[Sequence[str], Path], int] = _run
    output: Callable[[Sequence[str], Path], str | None] = _output
    gh: Callable[..., Any] = _gh
    running: Callable[[], bool] = stuntreel_running
    commits: Callable[[str, Path], list[str] | None] = _commits
    today: Callable[[], dt.date] = dt.date.today
    films: Callable[[Path], Sequence[str]] = reference_films


@dataclass
class Measurement:
    """What ``measure`` found: the agreement, each film's SSIM gap, and any failure."""

    agreement: Agreement | None
    gaps: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _reports(root: Path, films: Sequence[str]) -> tuple[dict[str, Report], list[str]]:
    """Each film's current report under *root*, and an error for each one that cannot be read."""
    reports: dict[str, Report] = {}
    errors: list[str] = []
    for film in films:
        path = root / "report" / f"{film}_current" / "report.json"
        try:
            reports[film] = read_report(path)
        except (OSError, ArtifactError) as err:
            errors.append(f"{film}: no report at {path}: {err}")
    return reports, errors


def _adapter(
    reports: dict[str, Report], adapter_class: str, arm: str
) -> tuple[str | None, list[str]]:
    """The one adapter name *reports* were drawn on, checked to be of *adapter_class*."""
    names = {report.adapter.name for report in reports.values() if report.adapter is not None}
    classes = {r.adapter.adapter_class for r in reports.values() if r.adapter is not None}
    if (
        len(names) != 1
        or classes != {adapter_class}
        or any(report.adapter is None for report in reports.values())
    ):
        return None, [
            f"the {arm} reports name adapters {sorted(names)} of classes {sorted(classes)}"
        ]
    return names.pop(), []


def measure(
    gpu: Path,
    lavapipe: Path,
    films: Sequence[str],
    drivers: tuple[str, str],
    today: dt.date,
) -> Measurement:
    """The agreement between the *gpu* and *lavapipe* roots over *films*; errors leave it ``None``."""
    gpu_reports, errors = _reports(gpu, films)
    lav_reports, more = _reports(lavapipe, films)
    errors += more
    gpu_adapter, more = _adapter(gpu_reports, "hardware", "GPU")
    errors += more
    lav_adapter, more = _adapter(lav_reports, "cpu", "lavapipe")
    errors += more
    trees = {report.crates for report in [*gpu_reports.values(), *lav_reports.values()]}
    if len(trees) != 1 or None in trees:
        errors.append(f"the reports name crates trees {sorted(str(tree) for tree in trees)}")
    gpu_stores, lav_stores = film_stores(gpu / "ours"), film_stores(lavapipe / "ours")
    measured: dict[str, FilmAgreement] = {}
    gaps: dict[str, float] = {}
    for film in films:
        if film not in gpu_stores or film not in lav_stores:
            errors.append(f"{film}: no {film}_current store in both roots")
            continue
        first, second = RenderStore(gpu_stores[film]), RenderStore(lav_stores[film])
        if first.ticks() != second.ticks():
            errors.append(
                f"{film}: tick sets differ ({len(first.ticks())} against {len(second.ticks())})"
            )
            continue
        ticks = first.ticks()
        measured[film] = FilmAgreement.from_residue(
            Residue(film, ticks, compare(first, second, ticks))
        )
        a, b = gpu_reports.get(film), lav_reports.get(film)
        if (
            a is not None
            and b is not None
            and a.mean_ssim_scored is not None
            and b.mean_ssim_scored is not None
        ):
            gaps[film] = a.mean_ssim_scored - b.mean_ssim_scored
    if errors or gpu_adapter is None or lav_adapter is None:
        return Measurement(None, gaps, errors)
    agreement = Agreement(
        crates=str(trees.pop()),
        date=today,
        gpu_adapter=gpu_adapter,
        gpu_driver=drivers[0],
        lavapipe_adapter=lav_adapter,
        lavapipe_driver=drivers[1],
        films=measured,
    )
    return Measurement(agreement, gaps)


def describe(found: list[Flag] | str) -> list[str]:
    """One line per flag, or the line saying why none was computed."""
    if isinstance(found, str):
        return [f"no flags computed: {found}"]
    if not found:
        return ["no flags"]
    return [f"flag: {flag.title()}: {flag.reason}" for flag in found]


def table(agreement: Agreement, gaps: dict[str, float]) -> list[str]:
    """The residue table: one row per film, with its SSIM gap."""
    width = max((len(name) for name in agreement.films), default=4)
    lines = [
        (
            f"{'film':<{width}}  {'ticks':>6}  {'differing':>9}  {'mean/tick':>9}  "
            f"{'max':>6}  {'at':>6}  {'hot':>4}  {'ssim gap':>10}"
        )
    ]
    for name, film in agreement.films.items():
        gap = f"{gaps[name]:+.7f}" if name in gaps else "-"
        lines.append(
            f"{name:<{width}}  {film.ticks:>6}  {film.differing_ticks:>9}  {film.mean:>9.2f}  "
            f"{film.largest:>6}  {film.largest_tick:>6}  {len(film.hot):>4}  {gap:>10}"
        )
    return lines


def _save(state: Path, agreement: Agreement, gaps: dict[str, float], order: Sequence[str]) -> None:
    state.mkdir(parents=True, exist_ok=True)
    (state / "measured.toml").write_text(
        format_agreement(agreement, order), encoding="utf-8", newline="\n"
    )
    (state / "gaps.json").write_text(json.dumps(gaps, sort_keys=True) + "\n", encoding="utf-8")


def _forget(state: Path) -> None:
    for name in ("measured.toml", "gaps.json"):
        (state / name).unlink(missing_ok=True)


def _load(state: Path) -> tuple[Agreement, dict[str, float]] | None:
    agreement = read_agreement(state / "measured.toml")
    gaps_file = state / "gaps.json"
    if agreement is None or not gaps_file.is_file():
        return None
    return agreement, {film: float(gap) for film, gap in json.loads(gaps_file.read_text()).items()}


def run_measure(
    repo: Path, gpu: Path, lavapipe: Path, drivers: tuple[str, str], tools: Tools
) -> tuple[int, Measurement]:
    """``measure`` in checkout *repo*: prints, keeps the measurement, and returns the exit code."""
    state = repo / STATE_DIR
    _forget(state)
    order = list(tools.films(repo))
    result = measure(gpu, lavapipe, order, drivers, tools.today())
    for error in result.errors:
        print(f"agreement: {error}", file=sys.stderr)
    if result.agreement is None:
        return 1, result
    _save(state, result.agreement, result.gaps, order)
    print("\n".join(table(result.agreement, result.gaps)))
    found = flags(read_agreement(repo / AGREEMENT_FILE), result.agreement, result.gaps)
    print("\n".join(describe(found)))
    return 0, result


def _restore(repo: Path, files: Sequence[str], tools: Tools) -> None:
    """Returns *files* to ``HEAD``, index and worktree: a file ``HEAD`` lacks is unstaged and deleted."""
    for name in files:
        if tools.output(["git", "rev-parse", "--verify", "--quiet", f"HEAD:{name}"], repo):
            tools.run(
                ["git", "restore", "--source=HEAD", "--staged", "--worktree", "--", name], repo
            )
        else:
            tools.run(["git", "rm", "-q", "--cached", "--ignore-unmatch", "--", name], repo)
            (repo / name).unlink(missing_ok=True)


def pin_branch(crates: str) -> str:
    """The branch a pin of *crates* is pushed to: one per tree, so a tree is pinned once."""
    return f"chore/agreement-{crates[:7]}"


def run_pin(repo: Path, accept: str | None, tools: Tools) -> int:
    """``pin`` in checkout *repo*: the exit code."""
    loaded = _load(repo / STATE_DIR)
    if loaded is None:
        print(
            f"agreement: no measurement in {repo / STATE_DIR}: run measure first", file=sys.stderr
        )
        return 2
    measured, gaps = loaded
    found = flags(read_agreement(repo / AGREEMENT_FILE), measured, gaps)
    if (isinstance(found, str) or found) and accept is None:
        print("\n".join(describe(found)))
        print("agreement: not pinned; pin over these with --accept REASON", file=sys.stderr)
        return 1
    tree = tools.output(["git", "rev-parse", "HEAD:crates"], repo)
    if tree != measured.crates:
        print(
            f"agreement: measured on crates {measured.crates[:7]}, the checkout has {str(tree)[:7]}",
            file=sys.stderr,
        )
        return 1
    if tools.run(["mise", "run", "parity-repin", "--", "--class", "gpu"], repo) != 0:
        print("agreement: the gpu repin wrote nothing; not pinned", file=sys.stderr)
        return 1
    path = repo / AGREEMENT_FILE
    path.write_text(
        format_agreement(replace(measured, accepted=accept), list(tools.films(repo))),
        encoding="utf-8",
        newline="\n",
    )
    files = [AGREEMENT_FILE.as_posix(), GPU_FILE.as_posix()]
    if not tools.output(["git", "status", "--porcelain", "--", *files], repo):
        print("agreement: the pinned figures are unchanged; nothing to commit")
        return 0
    branch = pin_branch(measured.crates)
    subject = "chore(parity): repin class agreement (#908)"
    body = f"Measured on crates {measured.crates[:7]} on {measured.date.isoformat()}."
    if accept is not None:
        body += f"\n\nAccepted over: {accept}"
    for argv in (
        ["git", "switch", "-C", branch],
        ["git", "add", "--", *files],
        ["git", "commit", "-m", subject, "-m", body],
    ):
        if tools.run(argv, repo) != 0:
            _restore(repo, files, tools)
            print(
                f"agreement: git {argv[1]} failed; the pinned files are restored", file=sys.stderr
            )
            return 1
    if tools.run(["git", "push", "-u", "origin", branch], repo) != 0:
        print(f"agreement: the pin is committed on {branch} but not pushed", file=sys.stderr)
        return 1
    try:
        pull = tools.gh(
            "-X", "POST", "repos/{owner}/{repo}/pulls",
            "-f", f"title={subject}", "-f", f"head={branch}", "-f", "base=main",
            "-f", f"body={body}\n\n" + "\n".join(table(measured, gaps)) + FOOTER,
        )  # fmt: skip
    except GhError as err:
        print(f"agreement: pushed {branch} but opened no pull request: {err}", file=sys.stderr)
        return 1
    print(f"agreement: opened {pull.get('html_url', branch)}")
    return 0


def _pages(tools: Tools, path: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    page = 1
    sep = "&" if "?" in path else "?"
    while True:
        batch = tools.gh(f"{path}{sep}per_page={PER_PAGE}&page={page}")
        entries += batch
        if len(batch) < PER_PAGE:
            return entries
        page += 1


def _open_issues(tools: Tools) -> list[dict[str, Any]]:
    """The open issues labelled :data:`LABEL`, pull requests left out."""
    path = f"repos/{{owner}}/{{repo}}/issues?state=open&labels={LABEL}"
    return [issue for issue in _pages(tools, path) if "pull_request" not in issue]


def _standing(tools: Tools, issues: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The open standing issue among *issues*, opened when there is none."""
    found = next((issue for issue in issues if issue["title"] == STANDING_TITLE), None)
    if found is not None:
        return found
    body = "Each class agreement batch comments here once per measured `crates` tree (#908)."
    return dict(
        tools.gh(
            "-X", "POST", "repos/{owner}/{repo}/issues", "-f", f"title={STANDING_TITLE}",
            "-f", "labels[]=" + LABEL, "-f", f"body={body}{FOOTER}",
        )
    )  # fmt: skip


def covered(flag: Flag, issues: Sequence[dict[str, Any]]) -> bool:
    """Whether an open issue already covers *flag*: the same title, or for a tick flag the same film and an overlapping tick range."""
    for issue in issues:
        title = issue["title"]
        if not flag.ticks:
            if title == flag.title():
                return True
            continue
        match = _TICK_TITLE.match(title)
        if match and match[1] == flag.film:
            first, last = int(match[2]), int(match[3])
            if first <= flag.ticks[-1] and flag.ticks[0] <= last:
                return True
    return False


def summary(measured: Agreement, gaps: dict[str, float], lines: Sequence[str]) -> str:
    """The standing issue's comment for one measured tree."""
    return (
        f"Class agreement on crates `{measured.crates}`, {measured.date.isoformat()}.\n\n"
        f"GPU {measured.gpu_adapter} ({measured.gpu_driver}); lavapipe "
        f"{measured.lavapipe_adapter} ({measured.lavapipe_driver}).\n\n"
        "```\n"
        + "\n".join(table(measured, gaps))
        + "\n```\n\n"
        + "\n".join(f"- {line}" for line in lines)
        + FOOTER
    )


def post(
    measured: Agreement, gaps: dict[str, float], found: list[Flag] | str, outcome: str, tools: Tools
) -> int:
    """Comments on the standing issue once per tree and files the uncovered flags; the exit code."""
    try:
        issues = _open_issues(tools)
        number = _standing(tools, issues)["number"]
        comments = _pages(tools, f"repos/{{owner}}/{{repo}}/issues/{number}/comments")
        if any(measured.crates in str(comment.get("body", "")) for comment in comments):
            print(f"agreement: #{number} already holds crates {measured.crates[:7]}; no comment")
        else:
            body = summary(measured, gaps, [*describe(found), outcome])
            tools.gh(
                "-X",
                "POST",
                f"repos/{{owner}}/{{repo}}/issues/{number}/comments",
                "-f",
                f"body={body}",
            )
        for flag in found if isinstance(found, list) else []:
            if covered(flag, issues):
                print(f"agreement: an open issue covers {flag.title()}")
                continue
            ticks = ", ".join(str(tick) for tick in flag.ticks)
            body = (
                f"{flag.reason}.\n\nMeasured on crates `{measured.crates}`, "
                f"{measured.date.isoformat()}, in the batch on #{number}."
                + (f"\n\nTicks: {ticks}." if ticks else "")
                + FOOTER
            )
            tools.gh(
                "-X", "POST", "repos/{owner}/{repo}/issues", "-f", f"title={flag.title()}",
                "-f", "labels[]=" + LABEL, "-f", f"body={body}",
            )  # fmt: skip
    except GhError as err:
        print(f"agreement: posting failed: {err}", file=sys.stderr)
        return 1
    return 0


def post_failure(errors: Sequence[str], tools: Tools) -> None:
    """Comments a batch's failed measurement on the standing issue, so an unattended night is seen."""
    try:
        standing = _standing(tools, _open_issues(tools))
        body = "The class agreement batch measured nothing:\n\n" + "\n".join(
            f"- {error}" for error in errors
        )
        comments = _pages(tools, f"repos/{{owner}}/{{repo}}/issues/{standing['number']}/comments")
        if comments and comments[-1].get("body") == f"{body}{FOOTER}":
            print(f"agreement: #{standing['number']} already reports this failure; no comment")
            return
        tools.gh(
            "-X", "POST", f"repos/{{owner}}/{{repo}}/issues/{standing['number']}/comments",
            "-f", f"body={body}{FOOTER}",
        )  # fmt: skip
    except GhError as err:
        print(f"agreement: posting failed: {err}", file=sys.stderr)


def driver_versions(
    tools: Tools, lavapipe_command: Sequence[str], cwd: Path
) -> tuple[str | None, str | None]:
    """The GPU's driver version and the lavapipe build's; ``None`` for one that cannot be read."""
    gpu = tools.output(GPU_DRIVER_COMMAND, cwd)
    return (gpu.splitlines()[0].strip() if gpu else None), tools.output(lavapipe_command, cwd)


def run_batch(
    primary: Path,
    *,
    if_due: bool,
    post_result: bool,
    lavapipe_command: Sequence[str],
    lavapipe_driver_command: Sequence[str],
    tools: Tools,
) -> int:
    """``batch`` from the primary checkout *primary*: the exit code."""
    if tools.running():
        print("agreement batch skipped: a stuntreel process is running")
        return 0
    worktree = primary / WORKTREE
    if tools.run(["git", "fetch", "origin", "main"], primary) != 0:
        return 1
    update = (
        ["git", "-C", str(worktree), "switch", "--detach", "origin/main"]
        if worktree.exists()
        else ["git", "worktree", "add", "--detach", str(worktree), "origin/main"]
    )
    if tools.run(update, primary) != 0:
        return 1
    if if_due:
        tree = tools.output(["git", "rev-parse", "HEAD:crates"], worktree)
        held = _load(worktree / STATE_DIR)
        if tree is not None and held is not None and held[0].crates == tree:
            print(
                f"agreement batch skipped: crates {tree[:7]} is already measured; "
                "pin it with --accept or wait for the next renderer commit"
            )
            return 0
        remote = ["git", "ls-remote", "--heads", "origin", pin_branch(tree or "")]
        if tree is not None and tools.output(remote, worktree):
            print(f"agreement batch skipped: the pin of crates {tree[:7]} awaits its merge")
            return 0
        pinned = read_agreement(worktree / AGREEMENT_FILE)
        commits = tools.commits(pinned.crates, worktree) if pinned is not None else None
        reason = due(pinned, commits, tools.today())
        if reason is None:
            print("agreement batch not due")
            return 0
        print(f"agreement batch due: {reason}")
    lavapipe = worktree / STATE_DIR / "lavapipe"
    if tools.run(lavapipe_command, worktree) != 0:
        print("agreement: the lavapipe arm failed; nothing measured", file=sys.stderr)
        return 1
    shutil.rmtree(lavapipe, ignore_errors=True)
    try:
        for part in ("ours", "report"):
            shutil.copytree(worktree / PARITY_DIR / part, lavapipe / part)
    except OSError as err:
        print(f"agreement: the lavapipe arm left nothing to keep: {err}", file=sys.stderr)
        return 1
    if tools.run(["mise", "run", "parity"], worktree) != 0:
        print("agreement: the GPU arm failed; nothing measured", file=sys.stderr)
        return 1
    gpu_driver, lav_driver = driver_versions(tools, lavapipe_driver_command, worktree)
    if gpu_driver is None or lav_driver is None:
        print("agreement: a driver version could not be read; nothing measured", file=sys.stderr)
        return 1
    code, result = run_measure(
        worktree, worktree / PARITY_DIR, lavapipe, (gpu_driver, lav_driver), tools
    )
    if code != 0 or result.agreement is None:
        if post_result:
            post_failure(result.errors, tools)
        return code or 1
    found = flags(read_agreement(worktree / AGREEMENT_FILE), result.agreement, result.gaps)
    if isinstance(found, list) and not found:
        code = run_pin(worktree, None, tools)
        outcome = "pinned" if code == 0 else "pin failed; see the batch's log"
    else:
        outcome = (
            "not pinned: in the worktree "
            f"{WORKTREE.as_posix()}, `mise run agreement -- pin --accept REASON` pins over this"
        )
    print(f"agreement: {outcome}")
    if post_result and post(result.agreement, result.gaps, found, outcome, tools) != 0:
        return 1
    return code


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mise run agreement --", description=__doc__.split("\n", 1)[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    measure_cmd = commands.add_parser("measure", help="measure two render roots")
    measure_cmd.add_argument("--gpu", type=Path, required=True, metavar="ROOT")
    measure_cmd.add_argument("--lavapipe", type=Path, required=True, metavar="ROOT")
    measure_cmd.add_argument("--gpu-driver", default=None, help="default: nvidia-smi's")
    measure_cmd.add_argument("--lavapipe-driver", default=None, help="default: dpkg-query's")
    pin_cmd = commands.add_parser("pin", help="pin the last measurement")
    pin_cmd.add_argument("--accept", default=None, metavar="REASON")
    batch_cmd = commands.add_parser("batch", help="render both classes, measure, pin, post")
    batch_cmd.add_argument("--if-due", action="store_true")
    batch_cmd.add_argument("--post", action="store_true")
    batch_cmd.add_argument("--lavapipe-command", default=LAVAPIPE_COMMAND)
    batch_cmd.add_argument("--lavapipe-driver-command", default=LAVAPIPE_DRIVER_COMMAND)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, tools: Tools | None = None) -> int:
    """Runs one subcommand; its exit code."""
    args = parse_args(argv)
    try:
        return _main(args, tools or Tools())
    except ValueError as err:
        print(f"agreement: {err}", file=sys.stderr)
        return 2


def _main(args: argparse.Namespace, tools: Tools) -> int:
    if args.command == "pin":
        return run_pin(REPO_ROOT, args.accept, tools)
    if args.command == "batch":
        return run_batch(
            REPO_ROOT,
            if_due=args.if_due,
            post_result=args.post,
            lavapipe_command=shlex.split(args.lavapipe_command),
            lavapipe_driver_command=shlex.split(args.lavapipe_driver_command),
            tools=tools,
        )
    drivers = (args.gpu_driver, args.lavapipe_driver)
    if None in drivers:
        detected = driver_versions(tools, shlex.split(LAVAPIPE_DRIVER_COMMAND), REPO_ROOT)
        drivers = (drivers[0] or detected[0], drivers[1] or detected[1])
    if drivers[0] is None or drivers[1] is None:
        print(
            "agreement: pass --gpu-driver and --lavapipe-driver; one could not be read",
            file=sys.stderr,
        )
        return 2
    code, _ = run_measure(REPO_ROOT, args.gpu, args.lavapipe, (drivers[0], drivers[1]), tools)
    return code


if __name__ == "__main__":
    sys.exit(main())
