#!/usr/bin/env python3
"""Write `moves.toml` for the #307 docs moves and print each new work folder's inferred state.

One-off, kept beside its output as the record of how `moves.toml` was made (plan.md, Task 9).

Each top-level `docs/process/plans/*.md` joins the folder of its topic (its name without the date
and `-implementation`) and its date (the name's, else the day git added it). A spec and its
implementation plan become `spec.md` and `plan.md`; a lone file becomes `plan.md` when it has a
Task heading, else `spec.md`; a retro or a note (`NOTES`) keeps its name. `architecture-deepening/`,
the sandbox note, `TEAM_SHEET.md`, the two image sets and the parity log go where Task 9 says.
`research/images/README.md` is not listed: Task 10 deletes it by hand.

A folder is in flight when spec section 3.2 names it, else landed when its Status line says
`implemented`, `landed`, `closed`, `done` or `complete`, else unknown; `DECISIONS` holds what the
user settled at the Task 9 checkpoint. A landed folder's outcome is its Status line, whole
sentences up to 200 characters, unless `OUTCOMES` picks the sentences that hold the result. A landed folder carries no `status` (an issue-less folder is
landed unless `status = "abandoned"`), an in-flight one its `issue`. An in-flight folder with no
issue is written with `issue = 0` and an unknown one with `status = "unknown"`, both refused by
`move-docs`, so neither is applied before a person decides. The state table goes to stdout, rows
needing a decision first.

Usage: `mise exec -- uv run python work/2026-11/307_docs-streamline/plan_moves.py`
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import NamedTuple

from stunt_reel.work_items import folder_name

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "moves.toml"
PLANS = "docs/process/plans"


class Decision(NamedTuple):
    """A state a person set: `landed`, `abandoned` or `in-flight`, with its issue and outcome."""

    state: str
    issue: int | None = None
    outcome: str | None = None


#: The plans spec section 3.2 names as in flight, by topic (`retro` is `retro-2026-11-07.md`).
IN_FLIGHT = frozenset(
    (
        "vault-parity-films",
        "retro",
        "capture-store-deepening",
        "debugger-breakpoints",
        "scoring-failures",
    )
)
#: The issue an in-flight plan names as its own. vault-parity-films: "tickets filed (#242, § 8)".
ISSUES = {"vault-parity-films": 242}
#: What the user settled at the Task 9 checkpoint (2026-11-08), by topic. An outcome given here
#: is the closing line that shows the work landed, or a draft where the record has none.
DECISIONS: dict[str, Decision] = {
    "vault-parity-films": Decision("in-flight", 242),
    "capture-store-deepening": Decision(
        "landed",
        outcome="Every issue the plan lists is closed as completed; its decisions are ADR 0028 "
        "and ADR 0029.",
    ),
    "debugger-breakpoints": Decision(
        "landed",
        outcome="Approved 2026-11-04; the issues it served, #65 and #66, the #69 they blocked "
        "and the #78 it depended on, are closed as completed.",
    ),
    "retro": Decision("landed"),
    "scoring-failures": Decision("abandoned"),
    "batch-parity": Decision(
        "landed",
        outcome="Tasks 1 to 4 landed as planned; Task 5 stopped on purpose at 79 of 529 films "
        "scored, with the results in research/parity/batch.md.",
    ),
    "dosbox-automation-switch": Decision(
        "landed",
        outcome="Tasks 1 to 5 are done on branch `worktree-dosbox-automation-spike`, and Task 7 "
        "except 7.5's process reaping, which is the user's.",
    ),
    "prek-hooks": Decision(
        "landed",
        outcome="Executed. Tasks 1 to 4 landed as planned, plus CodeRabbit's two plan comments, "
        "and Task 5 passed on Windows.",
    ),
    "python-3-13-3-15-stack": Decision(
        "landed",
        outcome="A five-branch stack from Python 3.12 to 3.15.2 and ruff target py315; main "
        "carries both pins (mise.toml, pyproject.toml).",
    ),
    "stack-review-and-tear-palette": Decision(
        "landed",
        outcome="Tasks 0 to 8 are done and Task 9 ran; layer 3 is `claude/tear-palette-skip`.",
    ),
    "tear-palette-investigation": Decision(
        "landed",
        outcome="Read-only investigation; stack-review-and-tear-palette built the tear skip it "
        "recommended, and its live recaptures flagged exactly these tear counts.",
    ),
    "windows-sandbox-integrity-label": Decision(
        "landed",
        outcome="The root's Low integrity label most likely came from a Claude Code sandbox "
        "release; the fix is to relabel the root alone to Medium and rebuild .venv.",
    ),
}
#: Outcomes picked from a Status line whose result lies past its first 200 characters.
OUTCOMES = {
    "capture-frame-storage": "Capture half replaced by `video-parity-2026-10-31.md`, which "
    "records each film as one AVI instead of frame dumps. The render half landed in #44.",
}
#: Lone files that are neither spec nor plan, so keep their names, with what makes each a note.
NOTES = {
    "review-dsh-friction-salvage.md": "an inventory of a salvaged branch",
    "scoring-failures-2026-10-31.md": "titled investigation notes",
    "tear-palette-investigation-2026-10-31.md": "titled an investigation",
}

_DATE_SUFFIX = re.compile(r"-([0-9]{4}-[0-9]{2}-[0-9]{2})$")
_LANDED = re.compile(r"\b(implemented|landed|closed|done|complete)\b", re.IGNORECASE)
_STATUS = re.compile(r"\**Status\**:\**\s*")
_TASK_HEADING = re.compile(r"#{2,}\s+Task\b")
_HINT_HEADING = re.compile(r"#{2,}\s+(Status|Handoff|Outcome)\b", re.IGNORECASE)
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_FENCE = ("```", "~~~")
_MAX_OUTCOME = 200


@dataclass
class Folder:
    """One work folder the moves create: its files, where they go, and how its state was read."""

    slug: str
    started: date
    title: str
    state: str
    state_source: str
    #: The Status line as plain text, whole sentences up to 200 characters, or "".
    status_text: str
    #: (source path, path inside the folder); a directory source moves whole.
    files: list[tuple[str, str]] = field(default_factory=list)
    issue: int | None = None
    #: The README outcome when it is not `status_text`.
    outcome: str | None = None
    #: What a reviewer should know about the entry, for the table.
    note: str = ""

    @property
    def path(self) -> str:
        """`work/<month>/<name>`; an in-flight folder with no issue yet is `0_<slug>`."""
        month = self.started.strftime("%Y-%m")
        if self.state != "in-flight":
            return f"work/{month}/{folder_name(None, self.slug)}"
        if self.issue is None:
            return f"work/{month}/0_{self.slug}"
        return f"work/{month}/{folder_name(self.issue, self.slug)}"

    @property
    def label(self) -> str:
        """The state as the table shows it."""
        return "NEEDS ISSUE" if self.state == "in-flight" and self.issue is None else self.state

    @property
    def readme_outcome(self) -> str:
        """The README `outcome`: empty while the work is open."""
        if self.state == "in-flight":
            return ""
        return self.status_text if self.outcome is None else self.outcome


def main() -> None:
    """Write `moves.toml` beside this file and print the state table."""
    tracked = set(_git("ls-files").splitlines())
    folders = [*_plan_folders(tracked), *_special_folders(tracked)]
    by_slug = {folder.slug: folder for folder in folders}
    if len(by_slug) != len(folders):
        raise SystemExit("two folders share a slug")
    by_slug["aircraft-render"].files.append(("research/parity/aircraft", "images"))
    for folder in folders:
        _decide(folder)
    _check_coverage(folders, tracked)
    OUT.write_text(_toml(folders), encoding="utf-8", newline="\n")
    print(_table(folders))  # noqa: T201 - the table is the output


def _plan_folders(tracked: set[str]) -> list[Folder]:
    """The folders of the top-level files in `docs/process/plans/`, one per topic and date."""
    groups: dict[tuple[str, date], dict[str, str]] = {}
    for path in sorted(p for p in tracked if p.startswith(f"{PLANS}/") and p.count("/") == 3):
        stem = path.rsplit("/", 1)[1].removesuffix(".md")
        if match := _DATE_SUFFIX.search(stem):
            day = date.fromisoformat(match[1])
            stem = stem[: match.start()]
        else:
            day = _added(path)
        role = "plan" if stem.endswith("-implementation") else "spec"
        topic = stem.removesuffix("-implementation")
        group = groups.setdefault((topic, day), {})
        if role in group:
            raise SystemExit(f"{path} and {group[role]} share a topic, date and role")
        group[role] = path
    folders: list[Folder] = []
    for (topic, day), group in sorted(groups.items()):
        lead = group.get("spec") or group["plan"]
        folder = _folder(_slug(topic), day, lead, [group.get("spec"), group.get("plan")])
        for role in ("spec", "plan"):
            if source := group.get(role):
                folder.files.append((source, _name(source, role, paired=len(group) == 2)))
        if reason := NOTES.get(lead.rsplit("/", 1)[1]):
            folder.note = f"keeps its name: {reason}"
        folders.append(folder)
    return folders


def _special_folders(tracked: set[str]) -> list[Folder]:
    """The folders Task 9 names one by one."""
    deepening = f"{PLANS}/architecture-deepening"
    inside = sorted(p for p in tracked if p.startswith(f"{deepening}/"))
    readme = f"{deepening}/README.md"
    architecture = _folder(
        "architecture-deepening", min(_added(p) for p in inside), readme, [readme]
    )
    architecture.files = [
        (p, "overview.md" if p == readme else p.rsplit("/", 1)[1]) for p in inside
    ]
    architecture.note = "README.md becomes overview.md; the folder README is new"

    sandbox = "docs/process/research/windows-sandbox-integrity-label-2026-11-01.md"
    windows = _folder("windows-sandbox-integrity-label", date(2026, 11, 1), sandbox, [sandbox])
    windows.files = [(sandbox, sandbox.rsplit("/", 1)[1])]

    sheet = "docs/process/TEAM_SHEET.md"
    team = Folder(
        slug="team-sheet",
        started=_added(sheet),
        title=_title(sheet),
        state="landed",
        state_source="spec section 3.2: frozen history",
        status_text="",
        files=[(sheet, "TEAM_SHEET.md")],
        outcome="Frozen history: ticket status from before work items became GitHub issues (#307)",
        note="outcome drafted",
    )
    lavapipe = Folder(
        slug="lavapipe-nan-shade",
        started=date(2026, 11, 7),
        title="Lavapipe clips a polygon's shade to NaN: comparison images",
        state="landed",
        state_source="its images show the fix merged in 7549be8 (#264)",
        status_text="",
        files=[("research/images/2026-11-07-72028d1", "images")],
        outcome="Fixed in #264: fragment_index keeps a polygon's index when its shade is not finite",
        note="title and outcome drafted; research/parity/lavapipe.md holds the finding",
    )
    log = Folder(
        slug="parity-log",
        started=date(2026, 10, 21),
        title="Parity results log, 2026-10-21 to 2026-11-07",
        state="landed",
        state_source="plan.md Task 9",
        status_text="",
        files=[("research/parity/log.md", "log.md")],
        outcome="Retired for journal entries and expected scores in references.toml (#307)",
    )
    return [architecture, windows, team, lavapipe, log]


def _folder(slug: str, day: date, lead: str, sources: list[str | None]) -> Folder:
    """A folder titled by *lead*'s heading, its state read from the first of *sources* with a
    Status line."""
    status = next(
        (found for path in sources if path and (found := _status(path)) is not None), None
    )
    if slug in IN_FLIGHT:
        state, source = "in-flight", "spec section 3.2 names it in flight"
    elif status is not None and (word := _LANDED.search(status[1])):
        state, source = "landed", f"Status line, {status[0]}: '{word[0]}'"
    else:
        state = "unknown"
        source = f"Status line, {status[0]}: none of the landed words" if status else ""
        source = source or "no Status line"
    text = _whole_sentences(_STATUS.sub("", status[1], count=1)) if status else ""
    folder = Folder(slug, day, _title(lead), state, source, text, issue=ISSUES.get(slug))
    if outcome := OUTCOMES.get(slug):
        folder.outcome = outcome
        folder.note = "outcome picked from the Status line's first and last sentences"
    if state == "unknown" and not text:
        hints = (found for path in sources if path and (found := _hint(path)) is not None)
        if hint := next(hints, None):
            folder.note = f"{hint[0]} says: {hint[1]}"
    return folder


def _decide(folder: Folder) -> None:
    """Apply the user's decision for *folder*, if there is one."""
    decision = DECISIONS.get(folder.slug)
    if decision is None:
        return
    folder.state_source = f"user, Task 9 checkpoint (was {folder.state}: {folder.state_source})"
    folder.state, folder.issue = decision.state, decision.issue
    if decision.outcome is not None:
        folder.outcome = decision.outcome
        folder.note = "outcome set at the checkpoint"
    if folder.state in ("landed", "abandoned") and not folder.readme_outcome:
        raise SystemExit(f"DECISIONS[{folder.slug!r}] needs an outcome: it has no Status line")


def _check_coverage(folders: list[Folder], tracked: set[str]) -> None:
    """Exit unless every file in `docs/process/` moves, once, and no two land on one path."""
    sources = [source for folder in folders for source, _ in folder.files]
    targets = [f"{folder.path}/{name}" for folder in folders for _, name in folder.files]
    process = {p for p in tracked if p.startswith("docs/process/")}
    missing = process - set(sources)
    if missing or len(set(sources)) != len(sources) or len(set(targets)) != len(targets):
        raise SystemExit(f"moves do not cover docs/process/ once each: {sorted(missing)}")


def _name(path: str, role: str, *, paired: bool) -> str:
    """*path*'s name in its folder."""
    base = path.rsplit("/", 1)[1]
    if paired:
        return f"{role}.md"
    if base.startswith("retro-") or base in NOTES:
        return base
    return "plan.md" if _has_task_heading(path) else "spec.md"


def _slug(topic: str) -> str:
    """*topic* as a kebab-case slug: `python-3.13-3.15-stack` is `python-3-13-3-15-stack`."""
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")


def _lines(path: str) -> list[tuple[int, str]]:
    """(line number, line) of each line of *path* outside fenced code."""
    out: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith(_FENCE):
            fenced = not fenced
        elif not fenced:
            out.append((number, line))
    return out


def _paragraph(lines: list[tuple[int, str]], start: int) -> str:
    """The paragraph of *lines* from index *start* to the next blank line, joined."""
    parts: list[str] = []
    for _, line in lines[start:]:
        if not line.strip():
            break
        parts.append(line.strip())
    return " ".join(parts)


def _status(path: str) -> tuple[str, str] | None:
    """(`L<n>` of *path*, its Status paragraph) for the first line starting `Status:`."""
    lines = _lines(path)
    for index, (number, line) in enumerate(lines):
        if _STATUS.match(line):
            return f"{path.rsplit('/', 1)[1]}:{number}", _paragraph(lines, index)
    return None


def _hint(path: str) -> tuple[str, str] | None:
    """(`<file>:<n>`, first sentence) of the paragraph under *path*'s first Status, Handoff
    or Outcome heading, for a person deciding an unknown state."""
    lines = _lines(path)
    for index, (_, line) in enumerate(lines):
        if _HINT_HEADING.match(line):
            for at, (number, text) in enumerate(lines[index + 1 :], index + 1):
                if text.strip() and not text.startswith(("|", "#")):
                    sentence = _first_sentence(_paragraph(lines, at))
                    return f"{path.rsplit('/', 1)[1]}:{number}", sentence
    return None


def _first_sentence(paragraph: str) -> str:
    """*paragraph*'s first sentence, as `_whole_sentences` writes it."""
    return _whole_sentences(paragraph, limit=0)


def _whole_sentences(paragraph: str, limit: int = _MAX_OUTCOME) -> str:
    """*paragraph* as plain text, links reduced to their text, up to the last sentence end
    within *limit* characters; at least the first sentence, cut at a word past 200 characters."""
    text = _LINK.sub(r"\1", paragraph).replace("**", "").strip()
    text = text[:1].upper() + text[1:]
    ends = [match.end() for match in _SENTENCE_END.finditer(text)] or [len(text)]
    kept = text[: max([ends[0], *(end for end in ends if end <= limit)])]
    if len(kept) > _MAX_OUTCOME:
        kept = kept[: _MAX_OUTCOME - 3].rsplit(" ", 1)[0] + "..."
    return kept


def _has_task_heading(path: str) -> bool:
    return any(_TASK_HEADING.match(line) for _, line in _lines(path))


def _title(path: str) -> str:
    """*path*'s first `# ` heading."""
    for _, line in _lines(path):
        if line.startswith("# "):
            return line[2:].strip()
    raise SystemExit(f"{path} has no title")


def _added(path: str) -> date:
    """The day git added *path*, as Task 9 dates a file with no date in its name."""
    return date.fromisoformat(_git("log", "--diff-filter=A", "--format=%cs", "-1", "--", path))


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git commands
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


def _toml(folders: list[Folder]) -> str:
    """The moves file: `[[folder]]` by path, then `[[move]]` by source path."""
    out = [
        "# Generated by plan_moves.py and reviewed by hand; regenerate it after changing that",
        "# script's DECISIONS rather than editing it here.",
        "#",
        "# The states were confirmed with the user at the Task 9 checkpoint. A [[folder]] with",
        '# neither issue nor status is landed; status = "abandoned" marks dropped work.',
        "# research/images/README.md is not listed: Task 10 deletes it by hand.",
    ]
    for folder in sorted(folders, key=lambda f: f.path):
        out.append("")
        if folder.label == "NEEDS ISSUE":
            out.append("# NEEDS ISSUE: file one, then set issue and the path's prefix to it.")
        elif folder.state == "unknown":
            out.append("# UNKNOWN: set status to landed or abandoned, or file an issue.")
        out += ["[[folder]]", f"path = {_quote(folder.path)}", f"title = {_quote(folder.title)}"]
        out.append(f"started = {folder.started.isoformat()}")
        if folder.state == "in-flight":
            out.append(f"issue = {folder.issue or 0}")
        elif folder.state != "landed":
            out.append(f"status = {_quote(folder.state)}")
        out.append(f"outcome = {_quote(folder.readme_outcome)}")
        out.append(f"state_source = {_quote(folder.state_source)}")
    moves = sorted(
        (source, f"{folder.path}/{name}") for folder in folders for source, name in folder.files
    )
    for source, target in moves:
        out += ["", "[[move]]", f"from = {_quote(source)}", f"to = {_quote(target)}"]
    return "\n".join(out) + "\n"


def _quote(value: str) -> str:
    """*value* as a TOML basic string; JSON's escapes are all TOML escapes."""
    return json.dumps(value, ensure_ascii=False)


def _table(folders: list[Folder]) -> str:
    """The state table in Markdown, rows needing a decision first."""
    order = {"NEEDS ISSUE": 0, "unknown": 1, "in-flight": 2, "abandoned": 3, "landed": 4}
    rows = [
        "| Source file(s) | Target folder | State | Outcome | State source |",
        "| --- | --- | --- | --- | --- |",
    ]
    for folder in sorted(folders, key=lambda f: (order[f.label], f.path)):
        sources = ", ".join(f"`{_short(source)}`" for source, _ in folder.files)
        outcome = folder.readme_outcome or folder.status_text
        if folder.note:
            outcome = f"{outcome} *({folder.note})*" if outcome else f"*({folder.note})*"
        cells = [sources, f"`{folder.path}/`", folder.label, outcome, folder.state_source]
        rows.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    return "\n".join(rows)


def _short(path: str) -> str:
    """*path* without `docs/process/`, which every plan shares; a directory ends in `/`."""
    return path.removeprefix("docs/process/") + ("/" if (ROOT / path).is_dir() else "")


if __name__ == "__main__":
    main()
