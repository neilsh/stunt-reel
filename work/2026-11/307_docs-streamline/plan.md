# Docs Streamline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the docs into evergreen notes (`research/`, `docs/`) and dated work folders (`work/YYYY-MM/<issue>_<slug>/`), move `docs/process/` and the parity log into `work/` with history intact, and add the tooling that keeps notes distilled.

**Architecture:** Four stacked PRs. (1) Tooling: a stdlib frontmatter reader, a work-folder model, `mise run work`, the knowledge-map generator, `mise run doc-health`, the new link rules in `tests/test_doc_invariants.py`, and a reusable `move_docs.py`. (2) Moves: `move_docs.py` runs `git mv` from a reviewed `moves.toml` (`docs/process/`, the image sets and the parity log) and rewrites links in files that did not move. (3) Relink: the same tool rewrites links inside the moved files. Keeping the log's own link rewrite out of the PR that moves it keeps it a 100% rename after the squash; its many linked rows could otherwise fall under git's 50% similarity threshold. (4) Rules: AGENTS.md, skills, glossary, ADR, summaries. Distillations and the gardening routine follow as separate PRs.

**Tech Stack:** Python 3.13+ stdlib only (no YAML library: `dependencies = []`), pytest with the `docs` marker, mise tasks, `gh` and `gh stack`, git.

**Spec:** [`spec.md`](spec.md) (issue [#307](https://github.com/neilsh/stunt-reel/issues/307)). The expected-scores PR (spec section 6, first paragraph) touches the Rust render pipeline and the parity report schema, so it gets its own plan, `plan-expected-scores.md`, written next. PR 4 here, which tells agents to update expected scores instead of appending log rows, merges after it.

## Global Constraints

* `mise run check` passes with no warnings before every commit; the commit body ends with the gate line it prints (`docs/development.md#commit-messages`). Stage paths by name; never `git add -A`; never anything under `corpus/`.
* `AGENTS.md` stays at or under 8192 bytes (`AGENTS_MD_MAX_BYTES`; 8073 today, so every AGENTS.md edit is roughly net zero). Each `SKILL.md` stays under 500 words (`SKILL_MAX_WORDS`; `recording-findings` is at 495).
* No new runtime or dev dependency for parsing: frontmatter is a `---` block of `key: value` scalars read with the stdlib.
* Work folder path: `work/<YYYY-MM>/<issue>_<slug>/` with the bare issue number (`307_docs-streamline`); issue-less folders are `work/<YYYY-MM>/<slug>/`. Slugs match `^[a-z0-9]+(-[a-z0-9]+)*$`.
* README frontmatter: `title`, `started` (ISO date), `outcome` (string, may be empty), and exactly one of `issue` (int) or `status` (only `landed`).
* Research note frontmatter: `summary`, one sentence, at most 200 characters.
* Size budget: 20 KB (20480 bytes) for evergreen markdown.
* Python files follow the repo pattern: module docstring with a `Usage:` line, `from __future__ import annotations`, scripts in `python/scripts/` loaded by tests through `importlib.util.spec_from_file_location` (as `tests/test_superset_all_script.py` does), library code in `python/stunt_reel/`. Docs tests set `pytestmark = pytest.mark.docs`.
* Files are LF (`.editorconfig`); `move_docs.py` preserves each file's bytes apart from rewritten paths.
* Stack: `gh stack init` from the first branch, `gh stack submit --auto`; each PR passes CI at its own head; the stack squash-merges one commit per PR. A PR that changes `research/` or `NOTICE.md` gets a fresh-reviewer read of its diff before push (AGENTS.md working rule 7).

## Review Focus

1. **Reference-style link definitions** (`[label]: ../process/plans/x.md`) pointing at a moved file must be rewritten like inline links; a reader expects every link form to survive the move. Test in Task 7.
2. **Links between two moved files**, and links to a moved *directory* (`[aircraft/](../parity/aircraft/)`), must resolve after both ends move. Test in Task 7.
3. **`gh` missing or not signed in** (cloud sessions, CI) must leave `work list` and `doc-health` working, with status shown as unknown and one note on stderr, not a traceback. Test in Tasks 3 and 6.
4. **A "Ruled out" section written as a bold lead-in** (`**Ruled out:**`, the form `research/README.md` § Note shape shows) rather than a heading must still count as an allowed context for links into `work/`. Test in Task 5.
5. **Fragments in links from `work/`** into a note whose heading was later renamed must not fail the check (file-level only), while a fragment in a link *into* `work/` that names no heading must fail. Test in Task 5.

---

## PR 1: Tooling (branch: this branch, `claude/docs-reorganization-agent-85ba65`, which already holds the spec)

### Task 1: Frontmatter reader

**Files:**
- Create: `python/stunt_reel/frontmatter.py`
- Test: `tests/test_frontmatter.py`

**Interfaces:**
- Produces: `class FrontmatterError(ValueError)`; `read_frontmatter(text: str) -> tuple[dict[str, str | int], str]` returning the fields and the body after the block; a text with no leading `---` line returns `({}, text)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_reads_scalars_and_returns_the_body():
    fields, body = read_frontmatter('---\ntitle: Docs streamline\nissue: 307\noutcome: ""\n---\n# H\n')
    assert fields == {"title": "Docs streamline", "issue": 307, "outcome": ""}
    assert body == "# H\n"

def test_text_without_a_block_is_all_body():
    assert read_frontmatter("# H\n") == ({}, "# H\n")

def test_quoted_value_keeps_colons():
    assert read_frontmatter('---\nsummary: "a: b"\n---\n')[0] == {"summary": "a: b"}

@pytest.mark.parametrize("text", ["---\ntitle: x\n", "---\nnot a pair\n---\n", "---\na: 1\na: 2\n---\n"])
def test_malformed_blocks_raise(text):
    with pytest.raises(FrontmatterError):
        read_frontmatter(text)
```

- [ ] **Step 2: Run `uv run pytest tests/test_frontmatter.py -q`**; expected: FAIL (module missing).
- [ ] **Step 3: Implement `read_frontmatter`.** An unquoted value of digits is an `int`; a double-quoted value is unquoted with `\"` unescaped; anything else is the stripped string. An unclosed block, a line without `: `, or a repeated key raises `FrontmatterError` naming the line.
- [ ] **Step 4: Run the tests**; expected: PASS. Run `mise run typecheck` and `mise run lint-py`.
- [ ] **Step 5: Commit** `feat(tooling): read markdown frontmatter without a YAML dependency`.

### Task 2: Work folder model and its docs check

**Files:**
- Create: `python/stunt_reel/work_items.py`
- Create: `tests/test_work_items.py` (unit), `tests/test_work_folders.py` (docs-marked check over the repo's `work/`)

**Interfaces:**
- Consumes: `read_frontmatter`, `FrontmatterError` (Task 1).
- Produces:
  - `WORK_ROOT = REPO_ROOT / "work"`
  - `@dataclass(frozen=True) class WorkFolder: path: Path; month: str; issue: int | None; slug: str; title: str; started: date; outcome: str; status: Literal["landed"] | None`
  - `class WorkFolderError(ValueError)`
  - `folder_name(issue: int | None, slug: str) -> str`
  - `parse_folder(path: Path) -> WorkFolder` (raises `WorkFolderError`)
  - `scan(root: Path = WORK_ROOT) -> list[WorkFolder]` sorted by month, then issue (issue-less last, by slug)

- [ ] **Step 1: Write the failing unit tests**

```python
def test_folder_name_is_bare_issue_then_slug():
    assert folder_name(307, "docs-streamline") == "307_docs-streamline"
    assert folder_name(None, "parity-log") == "parity-log"

def test_parses_an_issue_folder(tmp_path): ...      # work/2026-11/307_docs-streamline/README.md with title, started 2026-11-07, issue 307
    # assert folder.issue == 307 and folder.status is None and folder.month == "2026-11"

def test_parses_an_issue_less_landed_folder(tmp_path): ...   # status: landed, no issue -> issue None, status "landed"

@pytest.mark.parametrize("problem", [
    "both issue and status", "neither issue nor status", "status: active",
    "issue in name but not frontmatter", "frontmatter issue differs from name",
    "started month differs from parent month", "slug with capitals", "missing README.md", "missing title",
])
def test_invalid_folders_raise(tmp_path, problem): ...
```

- [ ] **Step 2: Write the docs test** in `tests/test_work_folders.py`: `pytestmark = pytest.mark.docs`; `test_every_work_folder_is_valid` calls `scan()` and asserts no `WorkFolderError`, listing each bad folder and its reason; `test_month_directories_hold_only_work_folders` asserts every entry under `work/<YYYY-MM>/` is a directory and every top-level entry of `work/` is `README.md` or a `YYYY-MM` directory.
- [ ] **Step 3: Run both test files**; expected: FAIL.
- [ ] **Step 4: Implement `work_items.py`.** A folder is the directory under `work/<YYYY-MM>/`; its name matches `^(\d+)_([a-z0-9-]+)$` (issue) or `^([a-z0-9-]+)$` (issue-less, `status: landed` required).
- [ ] **Step 5: Run the tests**; expected: PASS (the repo's only folder, `work/2026-11/307_docs-streamline/`, is valid).
- [ ] **Step 6: Commit** `feat(tooling): model work folders and check every one under work/`.

### Task 3: `mise run work` (new, list)

**Files:**
- Create: `python/scripts/work.py`
- Modify: `mise.toml` (add `[tasks.work]`, `run = "uv run python python/scripts/work.py"`, description naming `new <slug> [--issue N]` and `list [--status active|landed|abandoned]`)
- Test: `tests/test_work_script.py`

**Interfaces:**
- Consumes: `folder_name`, `scan`, `WorkFolder`, `WORK_ROOT` (Task 2).
- Produces:
  - `Runner = Callable[[list[str]], str]` (runs a command, returns stdout; raises `FileNotFoundError` or `subprocess.CalledProcessError`)
  - `issue_statuses(numbers: Iterable[int], run: Runner) -> dict[int, str] | None`: `"active"` for OPEN, `"landed"` for CLOSED+COMPLETED, `"abandoned"` for CLOSED+NOT_PLANNED; `None` when `gh` is unavailable or fails. One call: `gh issue list --state all --limit 2000 --json number,state,stateReason`.
  - `create_folder(slug: str, issue: int, title: str, today: date, root: Path) -> Path`
  - `main(argv: list[str] | None = None, run: Runner = ..., today: date | None = None) -> int`

- [ ] **Step 1: Write the failing tests**

```python
def test_new_with_issue_makes_this_months_folder(tmp_path): ...
    # main(["new", "docs-streamline", "--issue", "307"], root=tmp_path, today=date(2026,11,7))
    # -> tmp_path/"2026-11"/"307_docs-streamline"/"README.md" with title from `gh issue view 307 --json title`, started 2026-11-07, outcome ""

def test_new_without_issue_files_one_after_checking_the_repo(tmp_path): ...
    # fake runner answers `gh repo view --json nameWithOwner` with "neilsh/stunt-reel" and
    # `gh issue create` with ".../issues/412"; asserts folder "412_<slug>" and the create call's --title

def test_new_refuses_an_existing_folder(tmp_path): ...

def test_list_maps_issue_states(tmp_path, capsys): ...
    # OPEN -> active, CLOSED/COMPLETED -> landed, CLOSED/NOT_PLANNED -> abandoned, issue-less -> landed

def test_list_without_gh_shows_unknown_and_one_note(tmp_path, capsys): ...
    # runner raises FileNotFoundError; status column "unknown"; stderr has exactly one "gh unavailable" line; exit 0

def test_list_filters_by_status(tmp_path, capsys): ...
```

- [ ] **Step 2: Run `uv run pytest tests/test_work_script.py -q`**; expected: FAIL.
- [ ] **Step 3: Implement `work.py`** (`main` takes a `--root` option defaulting to `WORK_ROOT`, used by the tests). `list` prints one line per folder: month, folder name, status, title, outcome.
- [ ] **Step 4: Run the tests**; expected: PASS.
- [ ] **Step 5: Commit** `feat(tooling): start and list work items with mise run work`.

### Task 4: Knowledge map

**Files:**
- Create: `python/scripts/knowledge_map.py`
- Create: `research/MAP.md` (generated)
- Modify: `mise.toml` `[tasks.fix]` (append `"uv run python python/scripts/knowledge_map.py --write"`), add `[tasks.knowledge-map]`
- Modify: `research/README.md` (one line linking `MAP.md`)
- Test: `tests/test_knowledge_map.py`

**Interfaces:**
- Consumes: `read_frontmatter` (Task 1).
- Produces: `render_map(research_root: Path) -> str`; `main(argv) -> int` with `--write` (rewrite `research/MAP.md`) and `--check` (exit 1 and name the file when stale).

- [ ] **Step 1: Write the failing tests**

```python
def test_groups_notes_by_folder_with_summaries(tmp_path): ...
    # research/playone-exe/lod.md with summary "LOD rules." -> a "## playone-exe" section holding
    # "- [`playone-exe/lod.md`](playone-exe/lod.md): LOD rules."

def test_note_without_summary_says_so(tmp_path): ...     # "...: no summary yet"

def test_skips_readme_map_and_non_markdown(tmp_path): ...  # README.md, MAP.md, *.ksy, *.toml, images

def test_output_is_stable(tmp_path): ...                  # sorted by path; same input, same bytes
```

and a docs-marked `test_research_map_is_current` asserting `render_map(REPO_ROOT / "research") == (REPO_ROOT / "research" / "MAP.md").read_text()` with the message "run mise run fix".

- [ ] **Step 2: Run them**; expected: FAIL.
- [ ] **Step 3: Implement `render_map`.** Header line: `<!-- Generated by mise run fix from each note's summary; do not edit. -->`, then `# Research map`, then one `##` section per folder (top-level notes such as `handbook.md` under `## research`), notes sorted by path. A note whose frontmatter raises `FrontmatterError` is listed as `no summary yet` too; doc-health reports it.
- [ ] **Step 4: Run `mise run knowledge-map -- --write`**, then the tests; expected: PASS. Every note reads "no summary yet" until PR 5.
- [ ] **Step 5: Commit** `feat(tooling): generate research/MAP.md from note summaries`.

### Task 5: Link rules

**Files:**
- Modify: `tests/test_doc_invariants.py`
- Create: `.ignore` (one line: `/work/`)

**Interfaces:**
- Produces (module-level, used by PR 2):
  - `WORK_DIR = REPO_ROOT / "work"`
  - `WORK_POINTERS: frozenset[tuple[str, str]]` (empty in this PR; may only shrink once filled)
  - `LINK_SOURCES_SKIPPED: tuple[str, ...] = ()` (PR 2 sets `("work/",)`, PR 3 empties it)
  - `def _work_links() -> set[tuple[str, str, bool]]`: (source, target, allowed) for every link from an evergreen markdown file into `work/`

- [ ] **Step 1: Write the failing tests** (in `tests/test_doc_invariants.py`, using `tmp_path` fixtures for the classifier and the repo for the invariants)

```python
def test_provenance_and_ruled_out_links_into_work_are_allowed(tmp_path): ...
    # a note with "_Source: [e](../../work/2026-11/x/journal.md#e)._" and a link under "## Ruled out"
    # and a link after a "**Ruled out:**" lead-in -> all allowed

def test_other_links_from_evergreen_files_into_work_fail(tmp_path): ...   # a link in a body paragraph -> not allowed

def test_adrs_may_cite_work_freely(tmp_path): ...

def test_links_from_work_check_the_file_not_the_heading(tmp_path): ...
    # work/x/journal.md -> ../../research/n.md#gone passes; -> ../../research/missing.md fails

def test_links_into_work_check_the_heading(tmp_path): ...   # research note -> work/.../journal.md#missing fails

def test_evergreen_files_link_into_work_only_where_allowed():  # the repo invariant, replacing the process test
def test_code_citations_name_no_heading():                     # no CODE_DOC_PATH_REGEX match followed by "#"
def test_no_docs_superpowers_directory():                      # (REPO_ROOT / "docs" / "superpowers").exists() is False
```

- [ ] **Step 2: Run `mise run test-docs`**; expected: FAIL.
- [ ] **Step 3: Implement.** Refactor `test_markdown_links_resolve` around one helper `_check_link(source, target) -> str | None` so the `work/` rules live in one place. A link is in an allowed context when its line, stripped, starts with `_Source:` or `*Source:`, or when it sits under a heading whose text is `Ruled out` (until the next heading of the same or higher level), or in the list or paragraph that follows a `**Ruled out:**` lead-in (until the next blank line followed by a non-list line, or the next heading). `CODE_DOC_PATH_REGEX` widens to `(?:research|docs|work)/`. Keep `test_sources_of_truth_do_not_link_into_process_docs` and `PROCESS_POINTERS` unchanged in this PR: `docs/process/` still exists until PR 2.
- [ ] **Step 4: Run `mise run test-docs`**; expected: PASS.
- [ ] **Step 5: Commit** `test(docs): links into work/ only from provenance and Ruled out; .ignore hides work/`.

### Task 6: `mise run doc-health`

**Files:**
- Create: `python/scripts/doc_health.py`
- Modify: `mise.toml` (add `[tasks.doc-health]`)
- Test: `tests/test_doc_health.py`

**Interfaces:**
- Consumes: `read_frontmatter` (Task 1), `scan` (Task 2), `issue_statuses`, `Runner` (Task 3).
- Produces: `@dataclass(frozen=True) class Finding: path: str; kind: Literal["size", "summary", "heading", "stale-issue", "missing-outcome"]; detail: str; weight: int`; `collect(repo_root: Path, run: Runner, today: date) -> list[Finding]` sorted by `weight` descending; `main(argv) -> int` printing a table, or JSON with `--json`; always exit 0.
- Values: `SIZE_BUDGET = 20480`; evergreen globs `research/**/*.md`, `docs/*.md`, `docs/agents/*.md`, `docs/howto/*.md`; exempt `research/MAP.md`, `research/formats/sod-opcode-coverage.md`, `docs/adr/**`; `STALE_DAYS = 14`; heading patterns: an ISO date `\b\d{4}-\d{2}-\d{2}\b`, an ordinal round `\b(first|second|third|fourth|fifth|\d+(st|nd|rd|th))\s+round\b`, or a heading starting with `Update`, `Follow-up`, `Handoff` or `Session` (case-insensitive). Weight of a size finding is its byte count; other kinds weigh 1.

- [ ] **Step 1: Write the failing tests**

```python
def test_flags_an_oversized_note_and_ranks_it_first(tmp_path): ...
def test_exempts_generated_tables_and_adrs(tmp_path): ...
def test_flags_a_research_note_without_summary(tmp_path): ...
@pytest.mark.parametrize("heading,flagged", [
    ("## 4.1 Second Round: Seven Questions", True), ("## 2026-11-06 sweep", True),
    ("### Update: lavapipe", True), ("### Dependency updates", False), ("## Ruled out", False)])
def test_session_style_headings(tmp_path, heading, flagged): ...
def test_flags_an_open_issue_untouched_for_14_days(tmp_path): ...     # last commit date from `git log -1 --format=%cs -- <folder>`
def test_flags_a_closed_issue_with_empty_outcome(tmp_path): ...
def test_without_gh_skips_issue_checks_with_a_note(tmp_path, capsys): ...
def test_json_output_lists_findings(tmp_path, capsys): ...
```

- [ ] **Step 2: Run them**; expected: FAIL.
- [ ] **Step 3: Implement `doc_health.py`.** The `Runner` also runs `git log` so tests stay offline.
- [ ] **Step 4: Run the tests, then `mise run doc-health`** on the repo; expected: the 15 research notes over 20 KB appear, `capture-dosbox-automation.md` first.
- [ ] **Step 5: Commit** `feat(tooling): report oversized, unsummarized and session-style docs with mise run doc-health`.

### Task 7: `move_docs.py` (used by PRs 2 and 3)

**Files:**
- Create: `python/scripts/move_docs.py`
- Modify: `mise.toml` (add `[tasks.move-docs]`)
- Test: `tests/test_move_docs.py` (builds a throwaway git repo in `tmp_path`)

**Interfaces:**
- Produces:
  - `moves.toml` schema: `[[move]]` tables with `from` and `to` (repo-relative; a directory moves as a whole), plus optional `[[folder]]` tables (`path`, `title`, `started`, `issue` or `status`, `outcome`, `state_source`) that `apply` writes as README files for new work folders.
  - `load_moves(path: Path) -> list[tuple[str, str]]` expanded to file level, and `path_map(moves) -> dict[str, str]` covering files and directories.
  - `rewrite_text(text: str, source_old: str, source_new: str, mapping: dict[str, str], *, markdown: bool) -> str`: for Markdown, inline links, image links and reference-style definitions whose resolved target is in `mapping` (or whose source moved) get a new relative path with the fragment kept; for any text file, exact repo-root-relative path strings in `mapping` are replaced.
  - `main(argv) -> int` with `apply <moves.toml> --phase move|inside [--dry-run]`. `move`: `git mv` each entry, write `[[folder]]` READMEs, rewrite every tracked text file that did not move. `inside`: rewrite the moved files only. Prints the old-to-new table as Markdown for the PR body.

- [ ] **Step 1: Write the failing tests**

```python
def test_inline_link_from_unmoved_file_follows_the_move(): ...
def test_reference_style_definition_follows_the_move(): ...           # Review Focus 1
def test_fragment_is_kept(): ...
def test_link_between_two_moved_files_resolves_in_inside_phase(): ...  # Review Focus 2
def test_link_to_a_moved_directory_follows_it(): ...                   # Review Focus 2
def test_root_relative_path_in_code_comment_is_replaced(): ...         # e.g. "docs/process/plans/x.md" in a .py comment
def test_links_inside_code_spans_and_fences_are_left_alone(): ...
def test_move_phase_leaves_moved_files_bytes_identical(tmp_path): ...   # so git sees a 100% rename
def test_line_endings_are_preserved(tmp_path): ...
def test_dry_run_changes_nothing(tmp_path): ...
```

- [ ] **Step 2: Run `uv run pytest tests/test_move_docs.py -q`**; expected: FAIL.
- [ ] **Step 3: Implement `move_docs.py`.** Reuse the link regexes from `tests/test_doc_invariants.py` by moving them into `python/stunt_reel/markdown_links.py` (`MARKDOWN_LINK_REGEX`, `LINK_DEFINITION_REGEX`, `prose(text) -> str` positions preserved) and importing them in both places.
- [ ] **Step 4: Run the tests and `mise run test-docs`**; expected: PASS.
- [ ] **Step 5: Commit** `feat(tooling): move docs and rewrite every link to them with mise run move-docs`.

### Task 8: `work/README.md` and PR 1 wrap-up

**Files:**
- Create: `work/README.md`

- [ ] **Step 1: Write `work/README.md`** under 6 KB: the one rule (spec section 3), the layout and naming (section 3.1), frontmatter fields, the lifecycle and correction rule, journal entry fields, search (`path: work/`, `--no-ignore-dot`), the image rules copied from `research/images/README.md` (paths become `work/<month>/<folder>/images/<film>-<tick>-<topic>.png`), and the CC BY 4.0 license line as `research/README.md` words it.
- [ ] **Step 2: Run `mise run check`**; expected: PASS. Run `mise run doc-health` and keep its output for the PR body.
- [ ] **Step 3: Commit** `docs(work): describe work folders`, then `gh stack init claude/docs-reorganization-agent-85ba65` and open the PR "Docs streamline 1/5: tooling (#307)".

---

## PR 2: Moves (branch `docs/307-moves`, stacked)

### Task 9: Plan the moves and confirm plan states

**Files:**
- Create: `work/2026-11/307_docs-streamline/plan_moves.py` (one-off, kept as a record)
- Create: `work/2026-11/307_docs-streamline/moves.toml` (its output, reviewed)

- [ ] **Step 1: Write `plan_moves.py`** to emit `moves.toml`:
  * Each `docs/process/plans/*.md`: topic = filename minus `-implementation` and the date suffix; date = filename date, else `git log --diff-filter=A --format=%cs -1`; a spec and plan with one topic and date share a folder as `spec.md` and `plan.md`; a file without an implementation partner becomes `spec.md` if it has no `## Task` headings, else `plan.md`; files that are neither (`TEAM_SHEET.md`, `retro-*.md`, notes) keep their basename.
  * `architecture-deepening/` moves whole to `work/2026-10/architecture-deepening/`; `docs/process/research/windows-sandbox-integrity-label-2026-11-01.md` to `work/2026-11/windows-sandbox-integrity-label/`; `TEAM_SHEET.md` to `work/<first-commit month>/team-sheet/`.
  * `research/images/2026-11-07-72028d1/` to `work/2026-11/lavapipe-nan-shade/images/`; `research/parity/aircraft/` to the aircraft-render folder's `images/`; `research/images/README.md` is deleted (its rules are in `work/README.md`).
  * `research/parity/log.md` to `work/2026-10/parity-log/log.md`, folder `status = "landed"`, started 2026-10-21, title "Parity results log, 2026-10-21 to 2026-11-07", outcome "Retired for journal entries and expected scores in references.toml (#307)".
  * State: `landed` when the Status line matches `implemented|landed|closed|done|complete`, `in-flight` for the five the spec names, else `unknown`; `outcome` is the Status line's first sentence, at most 200 characters.
- [ ] **Step 2: Run it** (`mise exec -- uv run python work/2026-11/307_docs-streamline/plan_moves.py`) and print the state table.
- [ ] **Step 3: Checkpoint with the user.** Show the table; the user sets each `unknown`, and approves filing an issue for each in-flight plan without one (`vault-parity-films` uses #242). Record the issue numbers in `moves.toml` (`issue = N`, folder `<N>_<slug>`).
- [ ] **Step 4: Commit** `docs(work): plan the docs/process moves (#307)`.

### Task 10: Apply the moves

**Files:**
- Moves: everything in `moves.toml`
- Modify: `tests/test_doc_invariants.py` (`LINK_SOURCES_SKIPPED = ("work/",)`; delete `test_sources_of_truth_do_not_link_into_process_docs`, `PROCESS_DIR`, `PROCESS_FREE`, `PROCESS_POINTERS`; fill `WORK_POINTERS` with the six rewritten pointers; add `test_no_docs_process_directory`)
- Modify: `NOTICE.md` (where comparison images go), `.gitattributes` (delete the `merge=union` line and its comment), plus every file `move_docs.py` rewrites

- [ ] **Step 1: Run `mise run move-docs -- apply work/2026-11/307_docs-streamline/moves.toml --phase move --dry-run`** and read the rewrite list; then run it without `--dry-run`.
- [ ] **Step 2: Verify renames**: `git diff --cached -M100% --name-status | grep -c '^R100'` equals the number of moved files.
- [ ] **Step 3: Edit `tests/test_doc_invariants.py`** as listed; edit the `NOTICE.md` sentences naming `research/images/` to name `work/<month>/<folder>/images/`.
- [ ] **Step 4: Run `mise run fix` and `mise run check`**; expected: PASS (`MAP.md` drops `parity/log.md`).
- [ ] **Step 5: Fresh-reviewer read** of the diff for `NOTICE.md` and `research/` (rule 7).
- [ ] **Step 6: Commit** `docs: move docs/process and image sets into work/ (#307)` with the old-to-new table in the PR body; `gh stack` adds the branch.

## PR 3: Links inside moved files (branch `docs/307-relink`, stacked)

### Task 11: Relink and drop the skip

- [ ] **Step 1: Run `mise run move-docs -- apply work/2026-11/307_docs-streamline/moves.toml --phase inside`.**
- [ ] **Step 2: Set `LINK_SOURCES_SKIPPED = ()`**, delete the constant if nothing else reads it.
- [ ] **Step 3: Run `mise run check`**; expected: PASS.
- [ ] **Step 4: Commit** `docs(work): rewrite links inside the moved records (#307)`.

## PR 4: Rules (branch `docs/307-rules`, stacked; merge after the expected-scores PR)

### Task 12: AGENTS.md, research/README.md, parity wording, glossary, ADR

**Files:**
- Modify: `AGENTS.md`, `research/README.md`, `GLOSSARY.md`, `docs/SPEC.md` (its `research/parity/` row: "method, residuals"; no results log), `docs/development.md` § Docstrings and doc comments (code cites a document by anchor token or path, never a heading), `docs/harness.md` (delete the paragraph on appending to the log), `research/parity/method.md` step 7 and section 5 (a journal entry instead of a row; section 5 points at the moved log as history), `python/scripts/parity_probe.py` docstring and `mise.toml` `parity-probe` description ("the rows the parity log needs" becomes "the scores a journal entry quotes")
- Create: `docs/adr/0041-dated-records-live-in-work-folders.md` (next free number at the time)

- [ ] **Step 1: Edit AGENTS.md** per spec section 5.5, keeping the file at or under 8192 bytes: directive 4 states the one rule; the section 2 table gains three rows and the `docs/process/` paragraph becomes the `work/` sentence; working rules 4 and 6 change; one new line on `mise run work -- new`, superpowers output and searching `work/`. Shorten wording elsewhere in the same file to pay for it.
- [ ] **Step 2: Edit `research/README.md`** per spec section 4.5 and section 4.1 (rules 3 to 5, the how-to test, the Size section's pointer to `mise run doc-health`, the `summary:` requirement in Note shape).
- [ ] **Step 3: Add glossary entries** for work item, work folder, journal entry, evergreen note, each two sentences at most, in `GLOSSARY.md`'s existing format.
- [ ] **Step 4: Write the ADR** in the repo's ADR format (status accepted 2026-11-07, citing `spec.md`): context (section 1), decision (sections 3 and 4.4), consequences (frozen folders, issue status, `.ignore`).
- [ ] **Step 5: Make the parity wording edits** listed under Files.
- [ ] **Step 6: Run `mise run check`**; expected: PASS, including `test_agents_md_fits_its_budget`.
- [ ] **Step 7: Commit** `docs: route dated records to work folders in AGENTS.md and research/README.md (#307)`.

### Task 13: Skills

**Files:**
- Modify: `.agents/skills/recording-findings/SKILL.md`, `.agents/skills/improving-render-parity/SKILL.md`
- Create: `.agents/skills/distilling-notes/SKILL.md`, `.agents/skills/distilling-notes/routine.md`

- [ ] **Step 1: `recording-findings`.** Step 1 says a journal entry in the work folder instead of a log row; step 5 adds "add or update `summary:`"; quick reference gains `research/MAP.md` and `mise run work`. Stay under 500 words by tightening existing lines.
- [ ] **Step 2: `improving-render-parity`.** "What was already tried" reads the residual's **Ruled out** then `rg <term> work/`; checklist item 2 likewise; "Finishing an item" says a journal entry, and that adopting a change updates the expected scores in `references.toml`.
- [ ] **Step 3: `distilling-notes/SKILL.md`** (frontmatter `name`, `description` triggering on "distill", "note over budget", doc-health findings): the procedure of spec section 5.4 as numbered steps with a done-when line each; under 500 words.
- [ ] **Step 4: `distilling-notes/routine.md`**: the weekly routine's prompt, as spec section 5.4 describes it (doc-health JSON, top offender, fresh reviewer, `lychee --no-progress --exclude-path work .` for external links, a draft PR listing dead links and stale folders, never merge).
- [ ] **Step 5: Run `mise run check`**; expected: PASS (`test_skills_fit_their_budget`).
- [ ] **Step 6: Commit** `docs(skills): journal entries, distilling notes and the gardening routine (#307)`.

### Task 14: Summaries on every research note

- [ ] **Step 1: Dispatch subagents** (one per research folder; cheaper model) each with: the note paths, the 200-character limit, "one sentence saying what the note establishes, present tense, no dates", and output as `path<TAB>summary` lines.
- [ ] **Step 2: Review the drafts** for claims broader than the note, then insert each as a frontmatter block at the top of its note.
- [ ] **Step 3: Run `mise run fix`** (regenerates `research/MAP.md`) and `mise run check`; expected: PASS; `mise run doc-health` reports no missing summary.
- [ ] **Step 4: Fresh-reviewer read** of the summaries (rule 7), then commit `docs(research): a one-line summary on every note and the generated map (#307)`, and `gh stack submit --auto`.

---

## After the stack

### Task 15: Blame ignores the migration

**Files:**
- Create: `.git-blame-ignore-revs` (the squashed commits of PRs 2 and 3, each with a comment line)
- Modify: `python/scripts/worktree_init.py` (set `blame.ignoreRevsFile` beside `core.hooksPath`), its test

- [ ] **Step 1: Write the failing test** that `init` sets `blame.ignoreRevsFile` to `.git-blame-ignore-revs` when the file exists, and prints the line it set.
- [ ] **Step 2: Implement, run, commit** `build(git): blame skips the docs migration commits (#307)`.

### Task 16: Distill the four worst files (independent PRs off `main`, one session each)

For each of `research/playone-exe/capture-dosbox-automation.md`, `research/parity/method.md` (its section 1 loop to `docs/howto/parity-loop.md`), `research/parity/framing-and-actors.md`, and `docs/development.md` (Workflows to `docs/howto/`): follow `distilling-notes`; verify with `mise run doc-health` that the file is under 20 KB and `git log -S '<a moved sentence>'` finds the journal; fresh-reviewer read; PR. Then split `research/playone-exe/memory-map.md` by segment with `move-docs` for any new files, keeping every `[MEM-*]` anchor registered in `doc_anchors.py`.

### Task 17: Schedule the gardening routine

- [ ] **Step 1:** Add `lychee` to `mise.toml` `[tools]` (current release, `aqua:lycheeverse/lychee`), commit.
- [ ] **Step 2:** With the user, create the weekly cloud routine through `/schedule`, its prompt "Follow `.agents/skills/distilling-notes/routine.md`".
- [ ] **Step 3:** After its first run, check its draft PR against the skill, then close #307 with the outcome and set the README `outcome`.
