"""Dry-run a prompt through headless ``claude -p`` and report which skills each run loaded.

A skill is tested the way writing-skills asks: run a task prompt without the skill (baseline),
then with it, and compare. Each run is a plan-mode dry run, so nothing is edited. The stream-json
output says whether the skill was listed to the model (``init`` line), which skills it loaded
(``Skill`` tool calls), whether it read the plan that gives the answers away, and the cost.
Each run writes ``target/skill-eval/<skill>/<model>-<phase>-<n>.jsonl`` and the result text
beside it as ``.md``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRY_RUN = (
    "\n\nThis is a dry run: list the files you would touch and the steps you would take;"
    " edit nothing."
)
DEFAULT_BUDGET = {"opus": 2.00, "haiku": 0.50}
PEEK_MARKER = "agents-md-split"
SKILL_FILE = re.compile(r"skills[\\/]([^\\/]+)[\\/]SKILL\.md$")


@dataclass(frozen=True)
class RunOutcome:
    """What one headless run did."""

    listed: bool
    skills: list[str]
    peeked: bool
    cost: float
    text: str | None
    failed: bool


def outcome(lines: list[str], returncode: int, skill: str) -> RunOutcome:
    """Read a run's stream-json *lines*; *skill* is the one under test."""
    listed = False
    skills: list[str] = []
    peeked = False
    cost = 0.0
    text: str | None = None
    is_error = False
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            listed = skill in (event.get("skills") or [])
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                data = block.get("input") or {}
                name = block.get("name")
                if name == "Skill":
                    skills.append(str(data.get("skill")))
                elif name == "Read" and (read := SKILL_FILE.search(str(data.get("file_path", "")))):
                    # A model may read the skill file instead of calling Skill: loaded all the same.
                    skills.append(read.group(1))
                if name in ("Read", "Grep") and PEEK_MARKER in json.dumps(data):
                    peeked = True
        elif kind == "user" and PEEK_MARKER in json.dumps(event.get("message")):
            # A search can surface the plan in its results without naming it in its input.
            peeked = True
        elif kind == "result":
            text = event.get("result")
            cost = float(event.get("total_cost_usd") or 0.0)
            is_error = bool(event.get("is_error"))
    failed = returncode != 0 or text is None or is_error
    return RunOutcome(listed, skills, peeked, cost, text, failed)


def main(argv: list[str] | None = None) -> int:
    """Run the repetitions and print one line per run, then the total cost."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skill", required=True)
    parser.add_argument("--model", required=True, choices=sorted(DEFAULT_BUDGET))
    parser.add_argument("--phase", required=True, choices=["baseline", "with"])
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--budget", type=float, help="USD cap per run (default by model)")
    args = parser.parse_args(argv)
    claude = shutil.which("claude")
    if claude is None:
        print("claude not found on PATH")
        return 1
    prompt = args.prompt_file.read_text(encoding="utf-8").strip() + DRY_RUN
    budget = args.budget if args.budget is not None else DEFAULT_BUDGET[args.model]
    out_dir = REPO_ROOT / "target" / "skill-eval" / args.skill
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0.0
    any_failed = False
    for n in range(1, args.reps + 1):
        proc = subprocess.run(  # noqa: S603 - fixed argv, claude resolved from PATH
            [
                claude,
                "-p",
                "--model",
                args.model,
                "--permission-mode",
                "plan",
                "--output-format",
                "stream-json",
                "--verbose",
                "--max-budget-usd",
                f"{budget:.2f}",
                prompt,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        stem = out_dir / f"{args.model}-{args.phase}-{n}"
        stem.with_suffix(".jsonl").write_text(proc.stdout, encoding="utf-8")
        result = outcome(proc.stdout.splitlines(), proc.returncode, args.skill)
        md = stem.with_suffix(".md")
        md.write_text(result.text or proc.stderr, encoding="utf-8")
        total += result.cost
        any_failed = any_failed or result.failed
        print(
            f"run {n}: listed {'yes' if result.listed else 'no'};"
            f" skills {', '.join(result.skills) or 'none'};"
            f" peeked {'yes' if result.peeked else 'no'}; ${result.cost:.2f};"
            f" exit {proc.returncode}; {md.relative_to(REPO_ROOT).as_posix()}"
            + ("; FAILED" if result.failed else "")
        )
    print(f"total ${total:.2f}")
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
