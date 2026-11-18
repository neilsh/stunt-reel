# Markdown breaks lines at sentences

## Status

Accepted 2026-11-18 for [#712](https://github.com/neilsh/stunt-reel/issues/712), designed in its [spec](../../work/2026-11/712_markdown-line-breaks/spec.md).

## Context

At `d4e01df` (2026-11-18) the repository's Markdown was wrapped two ways: 158 tracked files kept each paragraph on one line, and 103 hard-wrapped near 100 columns.
With a paragraph on one line, an edit to one sentence rewrites the whole line, so its diff, a review comment on it and `git blame` all cover the whole paragraph.
With a hard-wrapped paragraph, an edit reflows the lines after it, and the diff and blame cover those too.
Either way, two branches that touch the same paragraph conflict.
Separate lines make that rarer, though git still conflicts on edits to adjacent lines.

Some of the repository's checks read Markdown one line at a time.
The link checker's link and code-span regexes in [`markdown_links.py`](../../python/stunt_reel/markdown_links.py) stop at a line end.
`tests/test_doc_invariants.py` allows a link to a dated record only after a `_Source:` or `_Found` marker on the same line.

## Decision

- **One sentence per line.**
  Each sentence starts on a new line.
  A long sentence may also break after a clause; nothing requires it.
- **No break inside a link, a code span or inline math**, which the line-based regexes would then miss.
- **A `_Source:` or `_Found` span stays on one line with its links.**
- **Left as they are:** tables, headings, front matter, and fenced, `$$` and HTML blocks.
- **Scope.**
  The rule covers evergreen Markdown, `work/` folders created after this ADR, and new ADRs.
  It does not cover existing `work/` folders, which are dated records, or accepted ADRs, which are immutable.
  Nor does it cover text sent to GitHub as an issue, pull request or comment body, `.github/pull_request_template.md` included: GitHub renders each newline there as a line break.
- **Guidance, not a check.**
  [`docs/development.md`](../development.md#markdown-line-breaks) states the rule, `AGENTS.md` points to it, and no task enforces it.
- **One reflow.**
  The existing evergreen files are reflowed once, by the one-off [`reflow.py`](../../work/2026-11/712_markdown-line-breaks/reflow.py), in a pull request that changes nothing else.
  The script checks that every file renders to the same HTML apart from whitespace, and that the link checker finds as many links and code spans as in the old text with each paragraph joined onto one line.
  A fresh reviewer also reads a sample of the reflowed paragraphs.
  The reflow's squash commit is listed in [`.git-blame-ignore-revs`](../../.git-blame-ignore-revs).

## Considered Options

- **A lint check or formatter.**
  Rejected by the owner: the rule is guidance.
  A formatter would also have to know every line-based reader above.
- **Keeping both styles.**
  Rejected: each edit to a one-line paragraph keeps rewriting it.
- **Required clause breaks (semantic line breaks).**
  Rejected: no tool can place them, so neither a reflow nor a check could apply them.
  Clause breaks stay optional.
- **A hard wrap at a fixed column.**
  Rejected: an edit reflows the rest of the paragraph.

## Consequences

- `git blame` with the ignore file, tried on git 2.43.0 ([journal](../../work/2026-11/712_markdown-line-breaks/journal.md#2026-11-18-blame-across-a-sentence-reflow-with-an-ignored-revision)):
  - For a paragraph that was on one line, every sentence line is blamed on the last commit that changed the paragraph, and `blame.markIgnoredLines` marks it `?`.
    Nothing is lost: blame never knew which sentence each commit wrote.
  - For a hard-wrapped paragraph, git's fuzzy line matching guesses, and in the experiment one sentence was blamed on the wrong author.
    12 of the 129 files the reflow covers were hard-wrapped at `d4e01df`.
- `git log -L` and `git log -S` do not read the ignore file, so they show the reflow commit.
- Tables keep their long lines.
- Nothing enforces the rule, so a multi-sentence line can land; it is split when next edited.
- Code that reads Markdown to a line end has to read continuation lines too.
  `evidence_tiers` in [`site_pages.py`](../../python/stunt_reel/site_pages.py) was changed with this ADR to read a tier's meaning across lines.
