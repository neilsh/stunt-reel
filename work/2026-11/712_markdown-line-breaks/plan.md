# Markdown line breaks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** State the one-sentence-per-line guidance, reflow the existing evergreen Markdown once, and keep `git blame` usable across the reflow.

**Architecture:** Three pull requests, merged in order.
Each comes from branch `ccr-29c97b3c-adsthg`, restarted from `main` after the previous one merges, since a cloud session can neither merge nor arm a stacked PR.
PR 1 adds the guidance, the ADR, the one-off reflow script and every tooling fix the reflow needs.
PR 2 holds only the reflowed Markdown.
PR 3 lists PR 2's squash commit in `.git-blame-ignore-revs` and closes the work.

**Tech Stack:** Python 3 run with `mise exec -- uv run`.
`markdown-it-py` is in `uv.lock` only as a dependency of `rich`, which is enough for a one-off script.
The script reuses `stunt_reel.markdown_links`.

**Spec:** [`spec.md`](spec.md); evidence in [`journal.md`](journal.md).

## Global Constraints

- Reflow scope: tracked `*.md` minus `work/**`, `docs/adr/**`, `tests/fixtures/**`, `corpus/**`, `research/MAP.md` and `.github/pull_request_template.md` (spec § Reflow scope); 129 files at `d4e01df`.
- PR 2's diff is line breaks, plus list and blockquote continuation prefixes: no word, link or file outside the reflow scope changes.
- Never stage with `git add -A` or `git commit -a`, and never stage a path under `corpus/`.
- Every commit passes `mise run check`.
  PR 2 also passes `mise run check -- --full` before it is pushed.
- Every new or edited Markdown file in this work follows the new guidance.
- A commit changing `spec.md` or `plan.md` carries a `Fresh-review:` trailer.
- `AGENTS.md` stays within 8,192 bytes (`test_agents_md_fits_its_budget`).

## Review Focus

1. **Code that reads Markdown up to a line end.**
   A split there loses text while the rendered HTML stays the same.
   Known readers:
   - `evidence_tiers` in `python/stunt_reel/site_pages.py` reads a tier's meaning to the end of its first line, and no test checks the real SPEC's full meanings (Task 3).
   - The provenance rule in `tests/test_doc_invariants.py` reads a `_Source:` span to its line end, so the splitter never splits inside a `_Source:` span (Task 2 case table).
   - `TIER_LIKE_REGEX` in `python/scripts/formats_docs/tiers.py` is applied per line; tier tags hold no sentence end, so no split falls inside one.
   - `prose()` in `stunt_reel.markdown_links` toggles a fence on any line starting with three backticks; the splitter never starts a line with one.
   Task 5's dry run with `--full` covers what these do not.
2. **A link or code span across a line end.**
   It renders the same, but `MARKDOWN_LINK_REGEX` and `_INLINE_CODE` stop at a line end and skip it.
   `reflow.py verify` compares their per-file counts (Task 2).
3. **A split that starts a line with block syntax** (`- `, `* `, `+ `, `1. `, `#`, `>`, `|`, `<`, three backticks, `$$`, `[label]:`, a setext `===` or `---` line).
   Such a split turns prose into a list, heading, quote, table, fence or definition.
   The splitter refuses it, and `verify` catches any it misses (Task 2).
4. **An abbreviation or number read as a sentence end** (`e.g.`, `i.e.`, `cf.`, `vs.`, `etc.`, `Fig. 3`, `No. 2`).
   The split renders the same but reads badly, so only the reviewer's spot-check sees it (Task 7).
5. **An ADR number taken by a concurrent branch**, as happened to 0048 (#679).
   Task 6 checks `main` and open PRs for `0051` just before pushing.

---

### Task 1: Commit the spec, plan and journal

**Files:**
- Create: `work/2026-11/712_markdown-line-breaks/{spec.md,plan.md,journal.md}` (written)
- Modify: `work/2026-11/712_markdown-line-breaks/README.md` (the question, and links to the three files)

- [ ] **Step 1:** Run `mise run check`.
  Expected: PASS.
- [ ] **Step 2:** Commit the four files by name, subject `docs(work): plan Markdown line breaks (#712)`, with a `Fresh-review:` trailer naming what the reviewer read.

### Task 2: The one-off reflow script

**Files:**
- Create: `work/2026-11/712_markdown-line-breaks/reflow.py` (`work/` is outside ruff's scope, like other work-folder scripts)

**Interfaces:**
- Produces: `reflow.py {selftest | scope | write PATH... | verify --base REF PATH...}`, run as `mise exec -- uv run python work/2026-11/712_markdown-line-breaks/reflow.py …`.
  - `scope` prints the reflow-scope paths (Global Constraints) from `git ls-files`, one per line.
  - `write` rewrites each path in place with `reflow_text`.
  - `verify` exits 1 naming each failing path, else prints `N files: HTML, links and code spans unchanged`.
  - `selftest` asserts every case below and exits 1 on the first mismatch.
- Functions: `join_paragraphs(text: str) -> str` joins each paragraph's lines and splits nothing.
  `reflow_text(text: str) -> str` is `join_paragraphs` followed by the sentence splits.

- [ ] **Step 1: Write the `selftest` case table**, each pair asserted through `reflow_text`:

```python
CASES = [
    ("One. Two.\n", "One.\nTwo.\n"),
    ("One two\nthree. Four.\n", "One two three.\nFour.\n"),        # hard wrap joined
    ("Why? Because! Yes.\n", "Why?\nBecause!\nYes.\n"),
    ("It **ends.** Next.\n", "It **ends.**\nNext.\n"),             # closing ** kept
    ("See e.g. Foo. Bar.\n", "See e.g. Foo.\nBar.\n"),             # abbreviation kept
    ("At 0x40. The end.\n", "At 0x40.\nThe end.\n"),
    ("Read [`a.md`](a.md). Then go.\n", "Read [`a.md`](a.md).\nThen go.\n"),
    ("[Do it. Now](x.md) ok.\n", "[Do it. Now](x.md) ok.\n"),       # not inside link text
    ("`a. B` c. D.\n", "`a. B` c.\nD.\n"),                          # not inside a code span
    ("$a. B$ c.\n", "$a. B$ c.\n"),                                 # not inside inline math
    ("Claim. _Source: [A. B](../work/x.md)._\n",
     "Claim.\n_Source: [A. B](../work/x.md)._\n"),                 # not inside a _Source: span
    ("- One. Two.\n", "- One.\n  Two.\n"),
    ("- One two\n  three. Four.\n", "- One two three.\n  Four.\n"), # hard-wrapped item
    ("1. One. Two.\n", "1. One.\n   Two.\n"),
    ("> One. Two\n> three. Four.\n", "> One.\n> Two three.\n> Four.\n"),
    ("One.  \nTwo. Three.\n", "One.  \nTwo.\nThree.\n"),          # hard break kept
    ("Done. 1. is odd.\n", "Done. 1. is odd.\n"),                   # no split before a digit
    ("Done. [x]: y\n", "Done. [x]: y\n"),                           # would start a definition
    ("| a. B | c. D |\n|---|---|\n", "| a. B | c. D |\n|---|---|\n"),
    ("# One. Two\n", "# One. Two\n"),
    ("```\nOne. Two.\n```\n", "```\nOne. Two.\n```\n"),
    ("---\nsummary: One. Two.\n---\nA. B.\n", "---\nsummary: One. Two.\n---\nA. B.\n"),
    ("One. Two\n---\n", "One. Two\n---\n"),                         # setext heading untouched
]
```

- [ ] **Step 2:** Run `selftest`.
  Expected: FAIL, `reflow_text` not defined.
- [ ] **Step 3: Implement `join_paragraphs` and `reflow_text`.**
  - Leave untouched: YAML front matter, fenced code, `$$` blocks, HTML blocks and comments, headings (ATX and setext), any line starting with `|`, link reference definitions, thematic breaks, and any line indented 4 or more spaces outside a list item.
  - Join: within each remaining paragraph, including one inside a list item or blockquote, join the lines with one space.
    A line ending in two spaces or `\` keeps its break.
  - Split: after `.`, `?` or `!`, and any `)`, `"`, `*` or `_` right after it, followed by one space, when the next character is an uppercase letter, `` ` ``, `[`, `(`, `"`, `*` or `_`.
  - Do not split inside a code span, link text or URL, inline math, an HTML tag, or a `_Source:` span.
    Do not split after `e.g.`, `i.e.`, `cf.`, `vs.`, `etc.`, `approx.`, `Fig.`, `No.` or a single capital letter.
    Do not split where the new line would start with block syntax (Review Focus 3).
  - A continuation line takes the item's content indent in a list item, and the `> ` prefix in a blockquote.
- [ ] **Step 4:** Run `selftest`.
  Expected: PASS.
- [ ] **Step 5: Implement `verify`.**
  For each path, read the base text with `git show REF:PATH` and the working-tree text.
  Strip front matter from both, render each with `MarkdownIt("commonmark").enable(["table", "strikethrough"])`, collapse every whitespace run to one space, and compare.
  Then compare the counts of `MARKDOWN_LINK_REGEX` and `_INLINE_CODE` matches in the working text with those in `join_paragraphs(base)`.
  The base is joined first because a code span or link that a hard wrap already split is missed in the base and found once joined: `docs/harness.md` has three such code spans at `d4e01df`.
- [ ] **Step 6:** On a throwaway local branch, run `write` and then `verify --base HEAD` on `docs/harness.md`.
  Expected: PASS.
  Insert `- ` at the start of one reflowed line and rerun.
  Expected: FAIL naming the file.
  Discard the branch.
- [ ] **Step 7:** Commit `reflow.py`, subject `docs(work): one-off script that reflows Markdown to one sentence per line (#712)`.

### Task 3: Tier meanings survive a line break

**Files:**
- Modify: `python/stunt_reel/site_pages.py:52` (`_TIER_BULLET`) and `evidence_tiers`
- Test: `tests/test_site_pages.py`

**Interfaces:**
- Unchanged: `evidence_tiers(spec: str) -> list[dict[str, str]]`.

- [ ] **Step 1: Write `test_evidence_tiers_joins_a_meaning_split_across_lines`.**
  The section 2.4 input has a `[Hypothesis]` bullet `  * **\`[Hypothesis]\`**: Proposed from reasoning.\n    Never cite as fact.\n`, then an `[Established]` bullet.
  Assert the meanings are `"Proposed from reasoning. Never cite as fact."` and the next bullet's own.
- [ ] **Step 2: Write `test_evidence_tiers_of_the_real_spec_keep_every_sentence`.**
  Assert the real SPEC's `Hypothesis` meaning ends with `"Never cite as fact."`, so the dry run catches the truncation.
- [ ] **Step 3:** Run `mise run test-py -- tests/test_site_pages.py`.
  Expected: Step 1's test FAILS with the meaning cut at `reasoning.`; Step 2's passes.
- [ ] **Step 4:** Make the bullet's meaning run through its continuation lines, meaning lines indented deeper than its marker that start no new bullet, joined with one space.
- [ ] **Step 5:** Run the same command.
  Expected: PASS, the existing tier tests included.
- [ ] **Step 6:** Commit, subject `fix(site): read a tier's meaning across its continuation lines (#712)`.

### Task 4: The guidance and its ADR

**Files:**
- Create: `docs/adr/0051-markdown-breaks-lines-at-sentences.md`
- Modify: `docs/development.md` (new `### Markdown line breaks` after `### Docstrings and doc comments`)
- Modify: `AGENTS.md` (one line under `### Docstrings`)

- [ ] **Step 1: Write the ADR** with ADR 0047's sections (`Status`, `Context`, `Decision`, `Considered Options`, `Consequences`), one sentence per line.
  - Status: accepted on the merge date, for #712, designed in this folder's [`spec.md`](spec.md).
  - Context: the two wrap styles and their counts at `d4e01df`; what a one-line paragraph costs diffs, review comments and blame.
    Separate lines make a conflict less likely, but git still conflicts on edits to adjacent lines, so the ADR claims fewer conflicts, not none.
  - Decision: spec decisions 1 to 5, with the exceptions in full: old `work/` folders, accepted ADRs, GitHub bodies, tables, and links kept on their `_Source:` line.
  - Considered Options: a lint check or formatter (rejected by the owner: guidance only), keeping two styles, required clause breaks (no tool can place them), hard wrap at a column.
  - Consequences: the blame limits from the journal's first entry, bounded by the count of hard-wrapped files in scope (12 of 129 at `d4e01df`); `git log -L` and `-S` ignore the file; tables keep long lines; nothing enforces the rule.
- [ ] **Step 2: Write the `docs/development.md` section.**
  The file has 226 bytes left under its 20,480-byte budget, so the section is short and the ADR carries the exceptions:

```markdown
### Markdown line breaks

Start each sentence on its own line, and never break inside a link, code span or inline math: the link checker's regexes stop at a line end.
Exceptions and why: [ADR 0051](adr/0051-markdown-breaks-lines-at-sentences.md).
```

  `mise run doc-health` may still report the file over budget once PR 2 adds list indents.
  The report never fails the check; the owner decides whether to distil the file.
- [ ] **Step 3: Add the `AGENTS.md` line** under `### Docstrings`, as its own paragraph: `Markdown starts each sentence on its own line: [Markdown line breaks](docs/development.md#markdown-line-breaks).`
- [ ] **Step 4:** Run `mise run check`.
  Expected: PASS, `test_agents_md_fits_its_budget` included.
- [ ] **Step 5:** Commit the three files by name, subject `docs(adr): Markdown breaks lines at sentences (#712)`.

### Task 5: Dry run of the reflow

No file is committed from this task's throwaway branch.
It runs after Task 4, so the guidance's own lines and `AGENTS.md`'s budget are in it.

- [ ] **Step 1:** On a throwaway local branch from Task 4's commit, run `write` on every path `scope` prints, then `verify --base HEAD` on the same paths.
  Expected: PASS.
  On a failure, add the failing input to `CASES`, fix the script on the PR 1 branch, commit, and repeat.
- [ ] **Step 2:** Run `mise run check -- --full`.
  Expected: PASS.
  For each failure, fix the code or test that reads Markdown to a line end on the PR 1 branch, with a test as Task 3 does, and repeat.
  If `AGENTS.md` goes over its budget, or a fix would change what a document says or what a test means, ask the owner.
- [ ] **Step 3:** Add a `journal.md` entry `2026-11-DD: Reflow dry run` on the PR 1 branch: the commit, files changed, line counts before and after, `AGENTS.md`'s size, and each failure with its fix.
  Delete the throwaway branch.

### Task 6: Review and open PR 1

- [ ] **Step 1:** A fresh reviewer runs the `AGENTS.md` § Committing rule 5 pass over the branch diff, including the `site/guides/` reread for each changed file.
- [ ] **Step 2:** Fix what it reports, and rerun `mise run check`.
- [ ] **Step 3:** Confirm `0051` is still free on `origin/main` and in open PRs; renumber if not.
- [ ] **Step 4:** Push, and open PR 1 through the REST route in `cloud.md`, titled `docs: break Markdown lines at sentences (#712, 1/3)`, with the body from `.github/pull_request_template.md`.
  Subscribe to its activity.

### Task 7: PR 2, the reflow

Starts after PR 1 merges.

- [ ] **Step 1:** Restart `ccr-29c97b3c-adsthg` from `origin/main`.
- [ ] **Step 2:** Rerun the journal's branch survey.
  If any branch other than this one holds unmerged changes to a scope path, stop and ask the owner (spec decision 6).
- [ ] **Step 3:** Run `selftest`, then `write` on every path `scope` prints, then `verify --base origin/main` on the same paths.
  Expected: PASS.
- [ ] **Step 4:** Confirm that `git diff --stat origin/main` names only scope paths, and that `git diff --word-diff=porcelain origin/main` adds or removes no word other than `>`.
- [ ] **Step 5:** Run `mise run check -- --full`.
  Expected: PASS.
  A failure means Task 5 missed a reader: stop, and fix it in its own PR before this one.
- [ ] **Step 6:** A fresh reviewer reads at least 20 reflowed paragraphs across `research/`, `docs/` and `.agents/skills/`, those with the most splits, and reports splits after abbreviations or numbers (Review Focus 4).
  Fix each by moving the line break by hand, which keeps the diff to line breaks, and rerun `verify`.
  The script does not change in this PR; PR 3's journal entry lists the hand fixes.
- [ ] **Step 7:** Commit the scope paths by name, subject `style(docs): one sentence per line (#712, 2/3)`.
  The body says what the reflow did and quotes the `verify` line.
  Its trailer is `Fresh-review: verify (HTML, link and code-span counts unchanged for N files) and a reviewer's spot-check of M paragraphs`.
- [ ] **Step 8:** Push, open PR 2 titled as the commit subject, and subscribe.

### Task 8: PR 3, the blame entry and the outcome

Starts after PR 2 merges.

- [ ] **Step 1:** Restart the branch from `origin/main`, and read PR 2's squash commit hash from `main`'s log.
- [ ] **Step 2:** Append a block to `.git-blame-ignore-revs` in the existing entries' shape: a blank line, `# 2026-11-DD style(docs): one sentence per line (#712, #<PR 2>)`, then the full hash.
- [ ] **Step 3:** Run `git blame --ignore-revs-file .git-blame-ignore-revs` on one formerly one-line-paragraph file and one formerly hard-wrapped file.
  Confirm the reflowed lines show earlier commits.
- [ ] **Step 4:** Write the work README's `outcome` line, and a `journal.md` entry recording Step 3's result and Task 7 Step 6's hand fixes.
- [ ] **Step 5:** Run `mise run check`, commit, push, and open PR 3 titled `chore(git): ignore the sentence reflow in blame (#712, 3/3)`.
  Subscribe, and close #712 when it merges.
