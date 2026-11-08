# Work folders

`work/` holds dated records of work: specs, plans, journals and the images they cite. The dated records under `work/<YYYY-MM>/` are not a source of truth: state a fact about the system in `research/` or `docs/`, and cite a record only as its source.

**Provenance and licensing.** These records are original writing by Stunt Reel contributors and are licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (see [`README.md` § License](../README.md#license)). Quoted third-party material and cited community research remain under their own terms and are not relicensed by this project. Game-derived constants and captured frames recorded here are not relicensed either. No game assets are distributed; see [`NOTICE.md`](../NOTICE.md).

## The one rule

A current fact goes in [`research/`](../research/README.md) or [`docs/`](../docs/) and is rewritten in place. A dated record goes in `work/` and is frozen once its work lands. ADRs are dated but immutable, and stay in [`docs/adr/`](../docs/adr/).

## Layout

A **work item** is a GitHub issue: open is active, closed as completed is landed, closed as not planned is abandoned. It gets a folder only when it has a file to keep; otherwise the issue is the record.

```text
work/
  README.md                this page
  2026-11/                 the month the work started
    307_docs-streamline/   <issue>_<slug>
      README.md            frontmatter, the question, the outcome, links to what changed
      spec.md, plan.md
      journal.md
      images/
    distill-method/        <slug>: a folder with no issue
```

- **Path.** `work/<YYYY-MM>/<issue>_<slug>/`: the month the work started, the bare issue number, and a lowercase kebab-case slug (`^[a-z0-9]+(-[a-z0-9]+)*$`). A folder with no issue is `work/<YYYY-MM>/<slug>/`. A folder never moves. The month directories are the only index.
- **Files.** `spec.md` and `plan.md` (`spec-<topic>.md` for a second spec), `journal.md` and `images/`. Other files keep their basename.
- **README frontmatter.** A `---` block of `key: value` lines: `title`, `started` (ISO date, in the folder's month), `outcome` (one line, `""` until the work lands), and, in an issue folder, `issue` (the number in its name), whose status is its issue's. A folder with no issue is a landed record unless it carries `status: abandoned`, for dropped work. No other key or `status` value is allowed.

## Tools

- `mise run work -- new <slug> [--issue N]` makes this month's folder and its README; without `--issue` it files the issue first. Run it before a brainstorming or plan-writing skill writes a file, and write `spec.md` and `plan.md` into the folder, not the skill's default location (`docs/superpowers/` fails `mise run check`).
- `mise run work -- list [--status active|landed|abandoned]` prints every folder with its issue's status, read through `gh` (`unknown` without it).
- `mise run doc-health` reports, among other things, folders that break the layout, and folders whose issue is open with no commit in 14 days or closed with no `outcome`.

## Journal entries

Each new entry in `journal.md` is a `##` heading `YYYY-MM-DD: <title>`, then:

- **Question**: what the entry set out to learn.
- **Method**: what was run, on which commit.
- **Result**: what came out, with scores stated in the text.
- **Verdict**: adopted, rejected or control.
- **Lives in**: the evergreen note or ADR that now holds the fact.

An entry a distillation writes keeps the moved text verbatim under its dated heading, then **Lives in**.

Dated and session-style headings belong in `work/` only.

## Lifecycle

Anything goes while the issue is open. The PR that finishes the work lifts durable facts into research notes, ADRs or `docs/`, writes the README `outcome`, and closes the issue (by hand for a [stacked PR](../docs/agents/issue-tracker.md#conventions)). After that the folder changes only for link fixes.

A frozen entry later found wrong is not edited. The correction is a new entry in a new work item, and the evergreen note records it under `Ruled out`.

## Links

`mise run check` enforces these on Markdown links:

- **Into a dated record** (`work/<YYYY-MM>/`) from an evergreen file, a link must follow a provenance marker on its line (`_Source:` or a legacy `_Found `, italic, at the line's start or after whitespace), sit under a `Ruled out` heading (numbered or not, any case), come from an ADR, or point into a folder's `images/`. Any other fails unless `WORK_POINTERS` lists it; that list is meant only to shrink, and an entry whose link is gone fails. Its fragment must name a heading. By convention, a `_Source:` line links a journal entry's heading.
- **From a dated record** into an evergreen file: checked for the file only, so renaming a heading in a note never breaks a frozen record. Between dated records: checked in full.

In `.rs`, `.py`, `.wgsl` and `.toml` files outside dated records, each `.md` path under `research/`, `docs/` or `work/` written from the repository root must exist and carry no heading fragment.

## Search

A root `.ignore` hides `work/` from default ripgrep and Grep tool searches. Search it with `rg <term> work/` (`path: work/` in the Grep tool), or everything with `rg --no-ignore-dot`. `git grep` and the Glob tool do not read `.ignore`.

## Images

[`NOTICE.md`](../NOTICE.md#illustrative-comparison-images) sets the limits: one 320x200 screen or a crop of one, nothing extracted from game files, and every image cited by the text that uses it.

`work/<YYYY-MM>/<folder>/images/<film>-<tick>-<topic>.png`

- **`<film>-<tick>`** is the film slug's short name and the 50 Hz film tick, for example `ctry-422`.
- **`<topic>`** says what the image shows, in a few words.

The work folder dates the set; the journal entry that cites an image names the commit whose tree made each render panel. Panels run left to right: the capture first, then each render in the order the citing entry describes. `NOTICE.md`'s limit of one screen, or a crop or enlargement of one, applies to each panel: an image sets one captured moment beside renders of that same moment, never a run of frames. An image is never replaced: a new render of the same moment takes a new `<topic>`, or a later work item's folder, so a link always shows what its text describes.
