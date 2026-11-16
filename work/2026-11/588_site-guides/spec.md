# Spec: guides for new readers, and project docs on the research site

Issue [#588](https://github.com/neilsh/stunt-reel/issues/588). Builds on the site from [#576](../576_research-site/spec.md).

## Intent

The research site (<https://neilsh.github.io/stunt-reel/>) publishes `research/` and the glossary. A new reader finds it hard to get into: the home page is four links, the sidebar shows file names (`anchorpt`, `map`), and the notes are written for people working in the repo (a note on the `.FLM` format opens with a table of magic bytes and evidence tags). The project's process is on github.com only.

This work gives a newcomer a way in: a home page that starts from the questions a newcomer asks, short plain-language guides that answer each one and then point into the notes, and the project's own docs on the site, so a guide on how Stunt Reel is developed can link to them there.

## Goals

- The home page says in plain words what *Stunt Island* and Stunt Reel are, then offers six question cards, each leading to a guide.
- Five new guides and one reworked page answer those questions for a reader who reads no hex, and each ends with the notes to read next, in order.
- `docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/development.md`, `docs/harness.md`, `docs/adr/` and `docs/howto/` are pages on the site; research notes' links to them stay on the site.
- The sidebar shows each page's title, not its file name, and groups pages as below.

## Non-goals

- Showing each note's `summary:` on its page, styling evidence tags (`[Established]`) as badges, and dropping spec-style numbering ("1.1 Origin") from note headings. They are [#589](https://github.com/neilsh/stunt-reel/issues/589).
- Rewriting the research notes for newcomers; the guides do that job and the notes stay as they are.
- Publishing the rest of `docs/`: `harness-setup.md`, `cloud-sessions.md`, `toolchain.md`, `agents/`, `quality-gate.md` and `architecture-python.md` stay on github.com.
- A custom theme or new dependencies.

## Anti-goals

- A guide that restates a measured figure (an offset, a score, a count) so that it can drift from the note that owns it.
- Hex, offsets or code in a guide's body: if a guide needs them to make its point, it is pitched at the wrong reader.
- A game-derived image on the site that [`NOTICE.md`](../../../NOTICE.md) does not already allow in `research/`.
- Hand-maintained lists of notes that nothing checks: every link a guide or card makes is checked, a link to a site page by the site build and a link that opens on github.com by the repository's link check (see [Checking links](#checking-links)).

## Approaches considered

For the home page, three shapes were mocked up: a diagram of how the areas fit (tools, game files, the original player, our renderer against it), question cards each naming notes to read, and one card per research folder. The user picked **question cards**: they give a newcomer a reading order in their own words, where the diagram lands them on a whole area and the folder cards repeat the sidebar.

For where the plain-language answers live, three places were considered:

1. **Site-only pages under `site/guides/` (chosen).** Like the existing hand-written `site/reading.md`, outside `research/`. They do not have to follow `research/`'s rule that each fact has one home, or its note shape (`Ruled out`, `Open questions`, provenance lines).
2. **A `research/guides/` folder.** It would bend the one-home rule and need an exception in `research/README.md`.
3. **Plain openings on existing overview notes** (`formats/INDEX.md`, `parity/method.md`). Cheapest, but those are routers for repo workers, and a newcomer's first page would still be a table.

For the development-process guide, the user chose to **publish part of `docs/` on the site** over linking out to github.com.

## Design

### Readers

Guides are written for a reader curious about how *Stunt Island* works who reads no assembly and no hex. Modders and reverse engineers are served by the notes each guide links to at its end.

### Home page (`site/index.md`)

Opening, replacing the current "analyses, documents and reconstructs" sentence:

> *Stunt Island* (1992) is a game for staging and filming stunts. Stunt Reel is a new film player, written from scratch, that plays the game's films at modern resolutions. To build it, we study how the original player behaves and check our frames against its own.

The existing pre-alpha caveat from the repository README may follow in one sentence. Then a "Where to start" grid of six cards. Each card is a question, one plain sentence of teaser, and a link to its page; no card lists notes.

| Card question | Page |
|---|---|
| What's in a Stunt Island film? | `guides/films` |
| How does the game draw a frame? | `guides/drawing` |
| How is the island built? | `guides/island` |
| How close is the reconstruction? | `guides/reconstruction` |
| How do we know what we know? | `reading` |
| How is Stunt Reel developed? | `guides/process` |

The current links (how to read, the full list of notes, the glossary, the repository) stay below the grid.

### Guides

Each guide sits in `site/guides/` and is published at `/guides/<name>/`. The file names above are the builder's call; the titles and what each covers are fixed here.

| Guide | What it explains | Notes it ends with, in reading order |
|---|---|---|
| **What's in a film** | A film is a recorded timeline of where every actor and the camera are, step by step; it comes as a `.FLM` beside a `.ALL` holding the models, sounds and palettes it uses. | `formats/flm`, `formats/all`, `formats/concepts/timeline-and-ticks`, `formats/res` |
| **How the game draws a frame** | Models are small programs that draw themselves (`.SOD`); the original paints back to front; colour comes from palette ramps. | `formats/sod`, `playone-exe/sod-vm`, `formats/concepts/palette-and-shading`, `parity/render-model` |
| **The island** | The ground is flat coloured patches over anchor points, compiled into a scenery tree; distance decides how much detail is drawn. | `formats/auxiliary/map`, `formats/auxiliary/anchorpt`, `formats/auxiliary/scenery`, `playone-exe/world-scene`, `playone-exe/lod` |
| **How close is the reconstruction** | We play the same film in the original and in ours and score the frames; where the remaining differences are, and what the scores cannot show. | `parity/method`, `parity/attribution`, `parity/evidence-limits`, `parity/batch` |
| **How Stunt Reel is developed** | See below. | Links into the published `docs/` pages |

**"How to read these notes" becomes "How we know what we know".** `site/reading.md` keeps its file name and its URL (`/reading/`). It gains, before the evidence tags, a short section on where the evidence comes from: disassembly, emulator captures, the retail handbook (`research/handbook.md`) and community research, ending with `playone-exe/static-tooling` and `playone-exe/capture-dosbox-automation`.

**The process guide** opens by saying Stunt Reel is partly a testbed for agentic workflows: the reverse engineering is real, and so is the experiment in how AI agents can do it reliably. It then follows one piece of work from issue to merge (issue, work folder and journal, finding recorded in `research/`, quality gate, fresh review, PR) and describes the workflows in use today, each linked to its page in the published docs or its decision record: skills and the fresh-review rule, work folders and journals ([ADR 0041](../../../docs/adr/0041-dated-records-live-in-work-folders.md)), the quality gate, unattended queue runs, orchestrated workers in separate worktrees, and cloud sessions. It describes what is in use, not a comparison of tools, and names no vendor beyond what `docs/harness.md` names. Where the detail lives only in an unpublished page (`docs/cloud-sessions.md`, a skill), it links to github.com.

### Rules for guides

- Plain words, no hex, offsets or code in the body. Terms a reader will meet in the notes are explained where first used and may link to the glossary.
- No measured figures: a guide links to the note that holds a number rather than quoting it.
- Under about 1,000 words each.
- Mermaid diagrams are welcome (the site renders them). Game imagery only where `research/` already publishes it (`research/parity/error-examples/`); no new game frames.
- A change under `site/guides/` or to `site/reading.md` gets the same fresh-review pass as a change to `research/`: [AGENTS.md § Committing](../../../AGENTS.md#committing) item 5 gains `site/guides/`.

### Published docs

`site/published.toml` gains sections for `docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/development.md`, `docs/harness.md`, `docs/adr/` and `docs/howto/`, published under `docs/` on the site, and `.github/workflows/pages.yml` gains their paths (the comment at the top of `published.toml` requires it). A research note's link to `docs/SPEC.md#…` then stays on the site, as do links among these pages; links from them to anything unpublished (code, `work/`, `AGENTS.md`, the other `docs/` pages) open on github.com, as links do today.

A file section's page keeps its own `# ` title on the page; its `label` is only its sidebar label. Today a file section's label also replaces its page title (`titles` in `site_pages.prepare`), which would retitle `SPEC.md` "Spec".

### Sidebar

In this order:

1. How we know what we know (`reading`)
2. **Guides**: the five guides, in the cards' order (films, drawing, island, reconstruction, process), not by file name. *Author's call.*
3. **Research notes**: as today
4. **Project docs**: Spec, Architecture, Development, Agents (`harness.md`), How-to (`docs/howto/`), Decisions (`docs/adr/`)
5. Glossary

Where a sidebar label comes from:

- **A file section** (Spec, Architecture, Development, Agents, the Glossary): its `label` in `published.toml`, as today. The page itself keeps its own title (see [Published docs](#published-docs)).
- **A page inside a folder section** (a research note, a guide, a how-to, an ADR): its title, the front matter `title:` when there is one, else its `# ` heading. Today such a page with no `title:` is labelled with its file stem (`site_pages.page_text`), and no research note has a `title:`.
- **An ADR**: its number, then its title ("0041 Dated records live in work folders"), since ADRs are cited by number and their headings carry none. *Author's call.*
- `INDEX.md` and `README.md` keep their fixed labels.

`published.toml` needs a way to nest sections under one sidebar group ("Project docs"); the shape of that is the builder's call, as long as adding a section stays one entry in that file.

### Checking links

The site build checks links between site pages and their anchors (`starlight-links-validator`). It does not check a link that the prep turns into a github.com URL: `link_target` builds the URL for any unpublished path without checking that the file exists. Today the repository's link check (`LINK_SCAN_GLOBS` in `python/scripts/formats_docs/catalog.py`, run by `mise run check`) covers that for `research/`; it gains `site/**/*.md`, so a guide's link to `docs/cloud-sessions.md` or a skill fails the gate when the target is missing. *Author's call.*

A home-page card's link must be one of those two checks reaches. Plain HTML in Markdown passes through `rewrite_links` untouched, so if the cards are HTML, the builder shows that the link validator reads their `href`s or adds a test that each card's target is a published page.

## Delivery

Three PRs, in order, each passing `mise run site`:

1. **Publish the docs.** The `published.toml` and workflow changes, the sidebar group, file-section titles kept, ADR labels, and any fixes to `docs/` pages the site build needs (see below), including the broken formula in `docs/SPEC.md` (the `G07` row of § Verification, where a tab has replaced the `\t` of `\text`). Changes to `docs/*.md` get the fresh review AGENTS.md requires.
2. **Guides support, titles and home page.** Publish `site/guides/`, the Guides sidebar group and order, sidebar labels from titles, `site/**/*.md` in the link check, the new home page with its six cards, and the AGENTS.md rule. The cards may link to guide pages that are stubs (a title and one line) until PR 3.
3. **The guides.** The five guides and the reworked `reading.md`, with a fresh review. It may split into one PR per guide if reviews run long.

## Tests

`tests/test_site_pages.py` and `tests/test_site_prep.py` cover the prep changes on synthetic input: a page with no `title:` is labelled with its heading; a file section's page keeps its own title while its sidebar label stays the `published.toml` label; an ADR's label starts with its number; `site/guides/` pages are published and appear in the Guides group in the cards' order; grouped sections nest under their group in `sidebar.json`, in the order above. Links are checked as [Checking links](#checking-links) says.

## Left to the builder

- Guide file names, card teasers and guides' wording, within the rules above; the user reviews wording in PR 3.
- How the cards are drawn: Starlight's `CardGrid` and `LinkCard` need the home page to be MDX, which the prep script does not handle today; plain HTML in Markdown is the fallback. Either must read in light and dark themes and at phone width.
- How `published.toml` expresses a group.
- Fixes the docs pages need to build. Two known risks: `starlight-links-validator` checks every anchor, and a heading Starlight slugs differently from GitHub breaks a link; and `remark-math` reads a `$` in prose as math, which `failOnKatexError` turns into a build failure. `docs/SPEC.md` uses `$…$` and `$$…$$` as intended math throughout, so it goes through KaTeX; the other `$` found in the published pages (`harness.md`, ADRs 0009, 0013 and 0026, `howto/run-the-gpu-tests.md`) are in code spans or fences, which are safe. A docs fix must keep the page reading correctly on github.com.
- Long titles in the sidebar (some notes are titled "Specification: MAP.BIN Terrain Patches and the SD.EXE Scenery Build"): shortening them belongs to #589, unless the sidebar becomes unusable, in which case raise it.
