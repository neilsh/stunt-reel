"""CI runs only the docs half for a docs-only pull request, and everything otherwise (ADR 0047).

The `scope` job asks `gate.py scope` whether a pull request's changed paths are all docs. The
required checks keep their names, every dependent runs unless `scope` succeeded and said
`docs_only=true`, and no workflow-level path filter can leave a required check pending. The
workflow is read as text, as `tests/test_prek_hooks.py` reads it: no YAML parser is a dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CI = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

#: The skip condition, exactly: `scope` succeeded and said docs_only=true. Matching the whole
#: text, not its two halves, fails a condition that joins them with `||` or negates one alone.
_SKIP_CONDITION = "needs.scope.result == 'success' && needs.scope.outputs.docs_only == 'true'"


def _job(name: str) -> str:
    """The block of job `name`: its key line through the line before the next job's key."""
    jobs = CI[CI.index("\njobs:\n") :]
    start = re.search(rf"^  {re.escape(name)}:\n", jobs, re.MULTILINE)
    assert start is not None, f"no job {name!r}"
    following = re.search(r"^  [\w-]+:\n", jobs[start.end() :], re.MULTILINE)
    end = start.end() + following.start() if following else len(jobs)
    return jobs[start.start() : end]


def _job_if(block: str) -> str:
    """The job-level `if:` of a job block (indented four spaces), or an empty string."""
    found = re.search(r"^    if: (.+)$", block, re.MULTILINE)
    return found.group(1) if found else ""


def _step(block: str, marker: str) -> str:
    """The step of `block` that contains `marker`, from its `- ` line to the next step's."""
    at = block.index(marker)
    start = block.rindex("\n      - ", 0, at)
    following = block.find("\n      - ", at)
    return block[start : following if following != -1 else len(block)]


def test_the_required_check_names_are_unchanged() -> None:
    """The `main` ruleset matches required checks by display name."""
    for name in ("Quality gate (ubuntu)", "Windows smoke", "MSRV check", "Dependency policy"):
        assert len(re.findall(rf"^    name: {re.escape(name)}$", CI, re.MULTILINE)) == 1, name


def test_scope_job_reads_the_pull_request_diff() -> None:
    scope = _job("scope")
    assert _job_if(scope) == "github.event_name == 'pull_request'"
    for needle in ("fetch-depth: 0", "gate.py scope", "origin/$BASE_REF", "$GITHUB_OUTPUT"):
        assert needle in scope, needle
    assert re.findall(r"install_args: (.+)", scope) == ["python"]
    assert 'MISE_AUTO_INSTALL: "false"' in scope


def test_scope_fails_on_any_line_but_docs_only() -> None:
    """Only `docs_only=true|false` reaches the output; anything else fails `scope`, which runs
    every dependent."""
    scope = _job("scope")
    guard = re.search(
        r'case "\$out" in\n\s+docs_only=true \| docs_only=false\) echo "\$out" >> '
        r'"\$GITHUB_OUTPUT" ;;\n\s+\*\) .*exit 1 ;;\n\s+esac',
        scope,
    )
    assert guard is not None
    assert scope.count("$GITHUB_OUTPUT") == 1, "the output is written only inside the guard"


def test_every_dependent_runs_unless_scope_succeeded_with_docs_only() -> None:
    for name in ("quality", "msrv", "deny", "windows-smoke"):
        block = _job(name)
        condition = _job_if(block)
        assert re.search(r"^    needs: scope$", block, re.MULTILINE), name
        assert "!cancelled()" in condition, name
        assert "always()" not in block, name
        if name == "quality":
            assert condition in {"${{ !cancelled() }}", "!cancelled()"}, name
            continue
        event = "github.event_name == 'pull_request' && " if name == "windows-smoke" else ""
        assert condition == f"${{{{ !cancelled() && {event}!({_SKIP_CONDITION}) }}}}", name
    assert "needs:" not in _job("windows")


def test_a_docs_only_quality_run_runs_check_docs_and_skips_the_full_gate() -> None:
    quality = _job("quality")
    docs_only = re.search(r"^      DOCS_ONLY: (.+)$", quality, re.MULTILINE)
    assert docs_only is not None, "quality sets DOCS_ONLY at job level"
    assert docs_only.group(1) == f"${{{{ {_SKIP_CONDITION} }}}}"
    on_docs = "if: env.DOCS_ONLY == 'true'"
    off_docs = "if: env.DOCS_ONLY != 'true'"
    assert on_docs in _step(quality, "run: mise run check-docs")
    assert off_docs in _step(quality, "run: mise run check\n")
    assert off_docs in _step(quality, "mesa-vulkan-drivers")
    assert off_docs in _step(quality, "actions/cache@")
    install = re.search(r"install_args: (.+)", quality)
    assert install is not None
    assert "env.DOCS_ONLY == 'true'" in install.group(1)
    docs_branch = re.search(r"env\.DOCS_ONLY == 'true' && '([^']*)'", install.group(1))
    assert docs_branch is not None
    assert "rust" not in docs_branch.group(1).split()
    assert "python" in docs_branch.group(1).split()


def test_ci_has_no_workflow_level_path_filters() -> None:
    """A workflow that never starts leaves its required checks pending, so none filters."""
    head = CI[: CI.index("\njobs:\n")]
    assert "paths:" not in head
    assert "paths-ignore:" not in head
