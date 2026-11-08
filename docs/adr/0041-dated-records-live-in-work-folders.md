# Dated records live in work folders

## Status

accepted 2026-11-07. Designed in the
[docs-streamline spec](../../work/2026-11/307_docs-streamline/spec.md) and built by its
[plan](../../work/2026-11/307_docs-streamline/plan.md), work item
[#307](https://github.com/neilsh/stunt-reel/issues/307).

## Context

On 2026-11-07 the repository held about 2.2 MB of Markdown. The 2026-10-23 reorganization had
split the 102 KB `parity-findings.md` and set a 20 KB note guideline, yet two weeks later fifteen
research notes were over it again, led by `capture-dosbox-automation.md` at 64 KB and
`parity/method.md` at 57 KB. Investigations appended dated rounds to the note for their subject,
and nothing made a writer replace the text a round superseded, so moving files again would only
have reset the clock.

Other costs found in the same survey:

- `docs/process/plans/` was 790 KB in 45 files, a third of all docs, mostly landed spec and plan
  pairs, and every search from the root returned them.
- `research/parity/log.md` (72 KB, 126 rows) had become a general lab journal. Its Notes cells held
  paragraphs, notes in `playone-exe/` and `makeone-exe/` cited it for findings with no score, about 35 provenance
  lines linked the whole file rather than a row, and its `merge=union` attribute does not apply to
  merges on GitHub, so parallel PRs conflicted on it.
- No index said what `research/` knew, so an agent guessed a file or searched 970 KB.

## Decision

**The one rule.** A current fact goes in `research/` or `docs/` and is rewritten in place. A dated
record goes in `work/` and is frozen once its work lands. ADRs are dated but immutable decisions
and stay in `docs/adr/`; `research/**/*.ksy` and `research/parity/*.toml` are evergreen.

**Work items and work folders.** A work item is a GitHub issue, and its status is the issue's:
open is active, closed as completed is landed, closed as not planned is abandoned. It gets a work
folder only when it has a file to keep.

- **Path.** `work/<YYYY-MM>/<issue>_<slug>/`: the month the work started, the bare issue number
  and a lowercase kebab-case slug. Work with no issue (a migrated plan no longer in flight, a
  distillation) is `work/<YYYY-MM>/<slug>/`. A folder never moves, and the month directories are
  the only index; `mise run work -- list` prints them with each issue's status.
- **README frontmatter.** `title`, `started` (an ISO date) and `outcome` (empty until the work
  lands), plus `issue` (the number) in an issue folder. A folder with no issue is a landed record
  unless it carries `status: abandoned`; that is the only `status` value, and the frontmatter
  check refuses `status: landed`.
- **Files.** `spec.md` and `plan.md` for brainstorming and plan-writing output, `journal.md` for
  dated entries, `images/` for comparison images.
- **Journal entries.** A `##` heading `YYYY-MM-DD: <title>`, then Question, Method, Result (scores
  in the text), Verdict (adopted, rejected or control) and Lives in (the evergreen note or ADR that
  now holds the fact). Dated and session-style headings belong in `work/` only.
- **Lifecycle.** Anything goes while the issue is open. The PR that finishes the work lifts durable
  facts into research notes, ADRs or `docs/`, writes the README's `outcome` and closes the issue.
  Afterwards the folder changes only for link fixes; a frozen entry later found wrong is corrected
  by a new entry in a new work item, and the evergreen note records it under Ruled out.

`docs/process/` moved into work folders and is gone; `mise run check` fails if it, or the
plan-writing skills' default `docs/superpowers/`, exists.

**Retiring the parity log.** `research/parity/log.md` moved verbatim to
`work/2026-10/parity-log/log.md`, an issue-less landed record, and its `merge=union` line went.
Each use of it has a new home:

| Use | New home |
| --- | --- |
| "Was this already tried?" before a parity attempt | The residual's Ruled out section, then `rg <term> work/` |
| Provenance | A provenance line linking a journal entry's heading |
| The current baseline | Each film's expected tables in `research/parity/references.toml`, which `mise run parity` reads ([#308](https://github.com/neilsh/stunt-reel/pull/308)) |
| Appending a row per attempt | A journal entry in the attempt's own work folder; no shared file |

**Links into dated records, as built.** The spec states the rule more narrowly (sections 4.2 and
4.3) and keeps it as written; `tests/test_doc_invariants.py` enforces this. From an evergreen file,
a link into a dated record (`work/<YYYY-MM>/`) is allowed:

- in a provenance span: `_` or `*`, then `Source:` or `Found `, at the line's start or after
  whitespace, running to the end of the line;
- in the section under a Ruled out heading, with an optional section number, in any case, until
  the next heading at its level or above;
- from an ADR;
- into any dated folder's `images/`.

Every other such link fails unless `WORK_POINTERS` lists it, and that list only shrinks: a listed
link that is gone fails too. A fragment in a link into a dated record must name a heading, since
frozen headings never change. A link from a dated record into an evergreen file is checked for the
file only, so distilling a note breaks no frozen record; links between dated records are checked
in full. `work/README.md` is evergreen, so links to and from it are ordinary links. Code cites a
document by its path or a registered anchor token, never by a heading.

## Considered Options

- **Move the large notes again, or split them.** Rejected: the cause was where dated text went,
  so the notes would regrow.
- **Keep the parity log, with `merge=union`.** Rejected: GitHub merges ignore the attribute, so
  parallel PRs still conflicted.
- **lat.md for internal links.** Rejected: it requires a `lat.md/` vault, its wiki links render as
  raw text on GitHub, and its heading-path section ids break on every heading rename, which
  distillation does often.
- **lychee for internal links.** Rejected: code cites documents 287 times by anchor token, which
  lychee cannot see. It is kept for external URLs, which the gardening routine checks.

## Consequences

- **Frozen folders.** Once its issue closes, a folder is history: nothing appends to it, a later
  investigation opens its own work item, and a note cites the entry rather than restating the
  record. Distilling a note changes no frozen record.
- **Status lives on the issue.** `mise run work -- list` and `mise run doc-health` read it through
  `gh`; without `gh`, `list` shows it as unknown and `doc-health` skips its two issue checks with a
  note. A stacked PR's issue is closed by hand once the stack
  lands on `main`, since a closing keyword fires only on the default branch. An issue-less folder
  states its own status.
- **`.ignore`.** A root `.ignore` holding `/work/` keeps dated records out of default ripgrep and
  Grep tool searches. `rg <term> work/` or `path: work/` searches them, `rg --no-ignore-dot`
  searches everything, and `git grep` and the Glob tool do not read `.ignore`, so they still
  return them.
- **No shared append-only file.** Parity attempts in parallel PRs write journal entries in their
  own work folders rather than rows of one log.
