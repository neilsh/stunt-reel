# Guides for new readers and project docs on the research site: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A question-card home page, five plain-language guides, and the project's main `docs/` pages on the research site, with sidebar labels taken from page titles.

**Architecture:** `site/published.toml` gains two optional keys per section (`group`, `title`). With them, the guides (`site/guides/`) and the docs are ordinary published sections, and the prep code needs no special cases for them. `site_pages.page_text` takes sidebar labels from titles, numbers ADR labels, and passes a page's `order:` through to Starlight. The home page stays plain Markdown: each card is a Markdown link inside `<div>` wrappers, so the prep rewrites its links and both link checks read them.

**Tech Stack:** Python 3 (`python/stunt_reel/site_pages.py`, pytest), Astro Starlight in `site/`, `mise run site`.

**Spec:** [spec.md](spec.md). The plan argues from it; read both.

## Global Constraints

- Three PRs, in order, each passing `mise run site` and `mise run check`.
- No new dependencies and no custom theme. The cards use one small stylesheet.
- Guides: plain words, no hex, offsets or code in the body. No measured figures. Under 1,000 words. Each ends with the notes to read next, in order.
- Game imagery only from `research/parity/error-examples/`.
- Guide titles, fixed by the spec: "What's in a film", "How the game draws a frame", "The island", "How close is the reconstruction", "How Stunt Reel is developed". `site/reading.md` is retitled "How we know what we know".
- Home opening text, verbatim: *Stunt Island* (1992) is a game for staging and filming stunts. Stunt Reel is a new film player, written from scratch, that plays the game's films at modern resolutions. To build it, we study how the original player behaves and check our frames against its own.
- A change to `docs/*.md`, `site/guides/` or `site/reading.md` gets a fresh review before push (AGENTS.md § Committing item 5).
- Stage by name, Conventional Commit subjects, and end each commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never `gh pr merge --delete-branch`.

## Decisions this plan makes beyond the spec

- **Glossary title.** Once a file section's label no longer replaces its page title, `GLOSSARY.md` would be titled by its heading, "Stunt Reel". A section may set `title = "…"` in `published.toml` to replace the page title, and the Glossary section sets `title = "Glossary"`.
- **Guides are a published section** (`source = "site/guides"`, `dest = "guides"`, label "Guides"), not a second `_HAND_WRITTEN` list. The sidebar order then follows `published.toml`.
- **Guide order** comes from an integer `order:` in each guide's front matter, which `page_text` writes as Starlight's `sidebar.order`.
- **Labels from titles move to PR 1.** ADR labels need them, so the PR 2 item "sidebar labels from titles" lands with them.
- **Link-check globs** are `site/*.md` and `site/guides/*.md`, not the spec's `site/**/*.md`. The recursive glob would also scan `site/node_modules/` and the generated `site/src/content/docs/`.
- **Guide rules become a test** (`tests/test_site_guides.py`). The test enforces the parts a machine can check: no backticks or non-Mermaid fences, the `0x…` and `…h` hex forms, the word cap, a "Read next" list of links, and `order:`. Offsets written another way, and measured figures, are left to the PR 3 fresh review.

## Review Focus

1. **A `published.toml` source that the Pages workflow's paths miss.** A change to it would never rebuild the site. Task 3 adds a test that every source matches a `pages.yml` path.
2. **A group whose members are not adjacent in `published.toml`.** All its members should nest under one group, at the first member's position. Task 1 tests this.
3. **An `INDEX.md` or `README.md` that carries a `title:`.** It should keep its fixed label ("Index", "About this folder"). Task 2 tests this.
4. **A guide written without `order:`.** Starlight would sort it after the others, out of card order. Task 4's guide test requires it.
5. **A heading with markup used as a label** (a code span or a link). The label should be plain text, as titles already are. Task 2 tests this.

---

## PR 1: publish the docs

Branch: `claude/site-guides`, the branch that already holds the spec, and later this plan.

### Task 1: section groups and section titles

**Files:**
- Modify: `python/stunt_reel/site_pages.py` (`Section`, `load_sections`, `prepare`)
- Test: `tests/test_site_prep.py`

**Interfaces:**
- Produces: `Section(source: str, dest: str, label: str, group: str | None = None, title: str | None = None)`. `load_sections` reads the optional `group` and `title` keys, and rejects a present key that is not a non-empty string ("section N: 'group' …").
- Produces: `prepare` passes `title=section.title` to `page_text`, so a file section's `label` no longer reaches the page title. In `sidebar.json`, sections that share a `group` nest as `{"label": group, "items": [...]}` at the position of the group's first member, each member shaped as today.

- [ ] **Step 1: Write the failing tests.** Change the fixture: `PUBLISHED`'s Glossary entry gains `title = "Glossary"`, and the fixture `GLOSSARY.md` heading becomes `# Stunt Reel`. Then add:

```python
GROUPED = PUBLISHED + """
[[section]]
source = "docs/SPEC.md"
dest = "docs/spec.md"
label = "Spec"
group = "Project docs"

[[section]]
source = "NOTES.md"
dest = "notes.md"
label = "Notes"

[[section]]
source = "docs/adr"
dest = "docs/adr"
label = "Decisions"
group = "Project docs"
"""

def _grouped(repo: Path) -> None:
    _write(repo / "docs/SPEC.md", "# SPEC: Stunt Reel, a long title\n")
    _write(repo / "docs/adr/0041-dated.md", "# Dated records\n")
    _write(repo / "NOTES.md", "# N\n")
    _write(repo / "site/published.toml", GROUPED)
    prepare(repo, repo / "site")

def test_prepare_nests_a_group_at_its_first_member(repo: Path) -> None:
    _grouped(repo)
    sidebar = json.loads((repo / "site/src/generated/sidebar.json").read_text())
    assert sidebar[3:] == [
        {"label": "Project docs", "items": [
            {"label": "Spec", "slug": "docs/spec"},
            {"label": "Decisions", "items": [{"autogenerate": {"directory": "docs/adr"}}]},
        ]},
        {"label": "Notes", "slug": "notes"},
    ]

def test_prepare_keeps_a_file_sections_own_title(repo: Path) -> None:
    _grouped(repo)
    spec = (repo / "site/src/content/docs/docs/spec.md").read_text(encoding="utf-8")
    assert spec.startswith('---\ntitle: "SPEC: Stunt Reel, a long title"\n')
```

Rename `test_prepare_titles_a_file_section_by_its_label` to `test_prepare_titles_a_file_section_by_its_title_key`. It keeps its assertion (`title: "Glossary"`), which the `title` key now produces. Add `test_load_sections_rejects_a_non_string_group`, with `group = 1` → `ValueError` matching `section 1`.

- [ ] **Step 2: Run the tests and confirm they fail.** Run `mise run test-py -- tests/test_site_prep.py`. Expected: the new tests fail with `TypeError` or a sidebar mismatch.
- [ ] **Step 3: Implement** the `Section` fields, the optional-key validation in `load_sections`, the `title=section.title` change in `prepare` (drop the `titles` dict), and group nesting while building `sidebar`.
- [ ] **Step 4: Run the tests and confirm they pass.** Run `mise run test-py -- tests/test_site_prep.py tests/test_site_pages.py`. Expected: all pass.
- [ ] **Step 5: Commit.** Use `feat(site): published sections may share a sidebar group and set a page title (#588)`.

### Task 2: sidebar labels from titles; numbered ADR labels; `order`

**Files:**
- Modify: `python/stunt_reel/site_pages.py` (`page_text`)
- Test: `tests/test_site_pages.py`

**Interfaces:**
- Produces: `page_text` writes `sidebar.label` as follows, first match wins:
  1. A stem in `_SIDEBAR_LABELS` gets its fixed label, even when the page has a `title:`.
  2. A stem matching `^\d{4}-` gets `f"{stem[:4]} {title}"`.
  3. Any other page gets its plain title: `_plain` of the `title:` field, else of the `# ` heading.

  Rule 1 reverses today's precedence, where a `title:` beats the fixed label (`site_pages.py:183,190`).
  
  The label never comes from the `title=` override. A front-matter `order:` that is an int is written as `sidebar.order`. A non-int `order:` raises `ValueError` naming the source.

- [ ] **Step 1: Write the failing tests.** `_fields` already reads every `sidebar.*` key as JSON, so `order` comes back as an int.

```python
def test_page_text_sidebar_labels(site: Site) -> None:
    for source, text, label in [
        ("research/formats/sod.md", "# Spec: `.SOD` [VM](x.md)\n", "Spec: .SOD VM"),
        ("research/formats/INDEX.md", '---\ntitle: "Formats"\n---\n', "Index"),
        ("research/README.md", "# T\n", "About this folder"),
        ("docs/adr/0041-dated-records.md", "# Dated records live in work folders\n",
         "0041 Dated records live in work folders"),
    ]:
        fields, _ = _fields(page_text(text, source, site, set()))
        assert fields["sidebar.label"] == label

def test_page_text_label_ignores_a_given_title(site: Site) -> None:
    fields, _ = _fields(page_text("# Stunt Reel\n", "GLOSSARY.md", site, set(), title="Glossary"))
    assert fields["sidebar.label"] == "Stunt Reel"  # a file section's sidebar label comes from published.toml

def test_page_text_passes_order_through(site: Site) -> None:
    fields, _ = _fields(page_text('---\ntitle: "G"\norder: 2\n---\n', "site/guides/g.md", site, set()))
    assert fields["sidebar.order"] == 2

def test_page_text_rejects_a_non_int_order(site: Site) -> None:
    with pytest.raises(ValueError, match=r"site/guides/g\.md"):
        page_text('---\ntitle: "G"\norder: "first"\n---\n', "site/guides/g.md", site, set())
```

- [ ] **Step 2: Run and confirm failure.** Run `mise run test-py -- tests/test_site_pages.py`. Expected: the label tests fail with "sod" where a title was expected.
- [ ] **Step 3: Implement the label rule and `order` in `page_text`.**
- [ ] **Step 4: Run and confirm pass.** Run `mise run test-py -- tests/test_site_pages.py tests/test_site_prep.py`. Then run `mise run site` and check the research sidebar shows titles. Expected: tests pass and the build succeeds. A long title is #589's concern, not a failure.
- [ ] **Step 5: Commit.** Use `feat(site): label the sidebar with page titles, ADRs with their numbers (#588)`.

### Task 3: publish `docs/`

**Files:**
- Modify: `site/published.toml`, `.github/workflows/pages.yml`
- Modify as the build requires: `docs/SPEC.md` (always: the `G07` row's `$<TAB>ext{…}` becomes `$\text{…}`), and any other `docs/` page the build rejects
- Test: `tests/test_site_prep.py`

**Interfaces:**
- Consumes: `group` and `title` (Task 1).
- Produces: these `published.toml` sections, in this order:

| source | dest | label | group |
|---|---|---|---|
| `research` | `research` | Research notes | |
| `docs/SPEC.md` | `docs/spec.md` | Spec | Project docs |
| `docs/ARCHITECTURE.md` | `docs/architecture.md` | Architecture | Project docs |
| `docs/development.md` | `docs/development.md` | Development | Project docs |
| `docs/harness.md` | `docs/harness.md` | Agents | Project docs |
| `docs/howto` | `docs/howto` | How-to | Project docs |
| `docs/adr` | `docs/adr` | Decisions | Project docs |
| `GLOSSARY.md` | `glossary.md` | Glossary (`title = "Glossary"`) | |

  The `pages.yml` `paths` list gains `docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/development.md`, `docs/harness.md`, `docs/howto/**` and `docs/adr/**`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_site_pages.py`, add the case `("../../docs/SPEC.md#24-x", "/stunt-reel/docs/spec/#24-x")` with a second fixture `Site` that publishes `docs/SPEC.md` at `docs/spec.md`, so the existing GitHub-URL case stays. In `tests/test_site_prep.py`, against the real repository:

```python
def test_pages_workflow_watches_every_published_source() -> None:
    root = SCRIPTS.parent.parent
    sections = load_sections((root / "site/published.toml").read_text(encoding="utf-8"))
    # the quoted `- "…"` entries under `paths: &paths`, read line by line (no YAML dependency)
    paths = _workflow_paths(root / ".github/workflows/pages.yml")
    for section in sections:
        probe = section.source if (root / section.source).is_file() else f"{section.source}/x.md"
        assert any(fnmatch.fnmatch(probe, p.replace("**", "*")) for p in paths), section.source
```

- [ ] **Step 2: Edit `published.toml` only, then run the test and confirm it fails.** Run `mise run test-py -- tests/test_site_prep.py::test_pages_workflow_watches_every_published_source`. Expected: FAIL naming `docs/SPEC.md`. The new `test_site_pages.py` case already passes: it pins the `link_target` behaviour the docs rely on, which this task does not change.
- [ ] **Step 3: Add the `pages.yml` paths, then run the test and confirm it passes.**
- [ ] **Step 4: Run `mise run site` until it passes.** Fix each failure in the `docs/` page it names, keeping the page right on github.com:
  - For an anchor Starlight slugs differently, change the link to the anchor both renderers produce, or reword the heading.
  - For a KaTeX error, fix the formula.
  - For a `$` in prose, escape it as `\$`.
  
  Fix the `G07` formula even if the build does not flag it.
- [ ] **Step 5: Look at the built site** with `mise run site-preview`, the `site-dist` entry in `.claude/launch.json`. Check four things:
  - The sidebar order: How to read, Research notes, Project docs (Spec … Decisions), Glossary.
  - The Spec page's title is its own heading.
  - The ADR labels are numbered.
  - A research note's link to `docs/SPEC.md#…` stays on the site.
- [ ] **Step 6: Get a fresh review of the `docs/*.md` changes** (AGENTS.md § Committing item 5), then run `mise run check`.
- [ ] **Step 7: Commit, push and open PR 1.** Use `feat(site): publish the spec, architecture, development, harness, how-to and ADR pages (#588)`. Write the PR body with the `pr` skill. Its evidence is a sidebar screenshot before and after.

---

## PR 2: guides support and the home page

Branch: `claude/site-guides-home`, cut from `main` after PR 1 merges.

### Task 4: publish `site/guides/` with stubs and their rule test

**Files:**
- Create: `site/guides/films.md`, `drawing.md`, `island.md`, `reconstruction.md`, `process.md`
- Create: `tests/test_site_guides.py` (`pytestmark = pytest.mark.docs`)
- Modify: `site/published.toml` (a first section: `source = "site/guides"`, `dest = "guides"`, `label = "Guides"`), `python/scripts/formats_docs/catalog.py` (`LINK_SCAN_GLOBS` gains `"site/*.md"` and `"site/guides/*.md"`)

**Interfaces:**
- Consumes: `order` → `sidebar.order` (Task 2).
- Produces: guide pages at `/stunt-reel/guides/<name>/`. Each stub holds:
  - front matter `title:` (the spec's title for that guide) and `order:` (1 to 5, in the order films, drawing, island, reconstruction, process);
  - one plain line;
  - `## Read next`, whose list gives the first note from the spec's table for that guide. For the process guide, it links `docs/development.md`.

- [ ] **Step 1: Write the failing tests** in `tests/test_site_guides.py`. Each test runs over every `site/guides/*.md`, with mermaid fences removed first:
  - `test_the_five_guides_exist`: the stems of `site/guides/*.md` are exactly `{films, drawing, island, reconstruction, process}`.
  - `test_guides_have_a_title_and_distinct_orders`: `title` is a str; the `order` values are exactly `{1, …, 5}`, with films 1 and process 5.
  - `test_guides_hold_no_code`: no "`" anywhere, and no fence other than ` ```mermaid `.
  - `test_guides_hold_no_hex`: no match for `\b0x[0-9A-Fa-f]+\b|\b[0-9][0-9A-Fa-f]*h\b`.
  - `test_guides_stay_under_1000_words`: the body has fewer than 1,000 words (`len(body.split())`).
  - `test_guides_end_with_read_next`: the last `## ` heading is `## Read next`, and every non-blank line under it matches `^- \[[^\]]+\]\([^)]+\.md(#[^)]*)?\)`.
- [ ] **Step 2: Run and confirm failure.** Run `mise run test-py -- tests/test_site_guides.py`. Expected: `test_the_five_guides_exist` and the order test fail; the per-guide tests pass vacuously until the stubs exist.

  In `tests/test_site_prep.py`, add `test_prepare_publishes_guides_with_their_order`: a `site/guides` section holding `b.md` (`order: 1`) and `a.md` (`order: 2`) writes both pages, each with its `order` under `sidebar:`, and `sidebar.json` holds `{"label": "Guides", "items": [{"autogenerate": {"directory": "guides"}}]}` before Research notes.
- [ ] **Step 3: Write the five stubs, add the section, and add the globs.**
- [ ] **Step 4: Run and confirm pass.** Run `mise run test-py -- tests/test_site_guides.py tests/test_formats_catalog.py`, then `mise run site`. Expected: pass. The Guides group appears second in the sidebar, in card order.
- [ ] **Step 5: Commit.** Use `feat(site): publish site/guides with stubs and the guide rules as tests (#588)`.

### Task 5: home page cards and the AGENTS.md rule

**Files:**
- Modify: `site/index.md`, `site/astro.config.mjs` (`customCss` gains `"./src/styles/home.css"`), `AGENTS.md` (§ Committing item 5)
- Create: `site/src/styles/home.css`

**Interfaces:**
- Consumes: the guide pages (Task 4).

- [ ] **Step 1: Rewrite `site/index.md`.** Write it in this order:
  1. The opening text from Global Constraints. The pre-alpha caveat may follow it in one sentence.
  2. `## Where to start`.
  3. The six cards, in the spec's order. Each card has this shape, with the blank lines kept so the link stays Markdown:

     ```markdown
     <div class="sr-cards">
     <div class="sr-card">

     **[What's in a Stunt Island film?](guides/films.md)**

     One plain sentence of teaser.

     </div>
     … five more cards …
     </div>
     ```

     The "How do we know what we know?" card links `reading.md`.
  4. The current four links, unchanged.
- [ ] **Step 2: Write `home.css`.**
  - `.sr-cards` is a grid, `repeat(auto-fit, minmax(16rem, 1fr))`, with a gap.
  - `.sr-card` has a border and padding using Starlight's colour variables (`--sl-color-gray-5`, `--sl-color-text`), so it follows the theme. Set its margins to zero, overriding Starlight's flow spacing.
- [ ] **Step 3: Edit AGENTS.md.** In § Committing item 5, "changes `research/`, `NOTICE.md`, `docs/howto/` or `docs/*.md`" becomes "changes `research/`, `NOTICE.md`, `docs/howto/`, `docs/*.md`, `site/guides/` or `site/reading.md`".
- [ ] **Step 4: Verify.**
  - Run `mise run site`. Expected: pass; the link validator has read the card links.
  - Run `mise run test-py -- tests/test_formats_catalog.py`. Expected: pass; the repository link check now covers `site/index.md`.
  - Show both checks read the cards: change one card's link to `guides/nope.md`. Expected: `mise run site` and `tests/test_formats_catalog.py` both fail naming it. Revert.
  - In the preview, look at the home page in light and dark themes and at 375 px width. Expected: the cards fill one column on a phone and two or three on a desktop, and text stays readable in both themes.
- [ ] **Step 5: Run `mise run check`, then commit, push and open PR 2.** Use `feat(site): a home page that starts from a newcomer's questions (#588)`. The PR body carries home-page screenshots: desktop light, desktop dark, phone.

---

## PR 3: the guides

Branch: `claude/site-guides-content`, cut from `main` after PR 2 merges. It may split into one PR per guide if reviews run long. The user reviews the wording.

### Tasks 6 to 9: the four topic guides

One task per guide: films, drawing, island, reconstruction. Each replaces its stub in `site/guides/<name>.md`, keeping its `title:` and `order:`.

- [ ] **Step 1: Read the notes** that the spec's table lists for that guide, in order. Read `GLOSSARY.md` for the terms the guide will use.
- [ ] **Step 2: Write the guide** to the spec's "What it explains" line and its rules:
  - Explain each term where it is first used, linking the glossary where it helps.
  - Link the note that holds a number instead of quoting the number.
  - Use at most one Mermaid diagram, and only where a sequence or structure reads better drawn.
  
  End with `## Read next`, listing the spec's notes in order, one line each: the link and a few plain words on what the note adds.
- [ ] **Step 3: Verify.** Run `mise run test-py -- tests/test_site_guides.py tests/test_formats_catalog.py`, then `mise run site`. Expected: pass.
- [ ] **Step 4: Commit.** Use `docs(site): guide to <topic> (#588)`.

### Task 10: the process guide

`site/guides/process.md`, written to the spec's "The process guide" paragraph.

- [ ] **Step 1: Read the sources.** Read `docs/development.md`, `docs/harness.md`, `docs/adr/0041-dated-records-live-in-work-folders.md`, `work/README.md`, the `running-unattended` skill, and `docs/cloud-sessions.md`.
- [ ] **Step 2: Write the guide.**
  - Open with the testbed framing.
  - Follow one piece of work from issue to merge. A Mermaid flowchart fits here.
  - Describe each workflow in use, with its link: published `docs/` pages on the site; `docs/cloud-sessions.md` and skills by their repository paths, which the prep turns into github.com links and the repository link check verifies.
  - Name no vendor beyond what `docs/harness.md` names.
  
  `## Read next` lists `docs/development.md`, `docs/harness.md`, `docs/SPEC.md` and `docs/adr/0041-dated-records-live-in-work-folders.md`.
- [ ] **Step 3: Verify, then commit.** Verify as in Tasks 6 to 9, then commit with `docs(site): guide to how Stunt Reel is developed (#588)`.

### Task 11: "How we know what we know"

- [ ] **Step 1: Retitle and extend `site/reading.md`.**
  - Set `title: "How we know what we know"`.
  - Before `## Evidence tags`, add `## Where the evidence comes from`. It covers disassembly, emulator captures, the retail handbook (`../research/handbook.md`) and community research, and ends with links to `../research/playone-exe/static-tooling.md` and `../research/playone-exe/capture-dosbox-automation.md`.
  - The file name and URL stay.
  - In `site/index.md`, the first of the four links below the cards now reads "How we know what we know".
- [ ] **Step 2: Verify** with `mise run site`. The sidebar's first entry and the card now read "How we know what we know".
- [ ] **Step 3: Get a fresh review of PR 3's diff**, covering every guide and `reading.md`. The reviewer:
  - checks each claim against the note it links;
  - flags any claim broader than its note, and any figure;
  - confirms no hex, offset or code.
  
  Then run `mise run check`, commit with `docs(site): retitle the reading page and add where the evidence comes from (#588)`, push, and open PR 3. The finishing PR writes `outcome` in the work folder's README.
