# Spec: publish `research/` as a GitHub Pages site

Issue [#576](https://github.com/neilsh/stunt-reel/issues/576).

## Intent

Modders and fans of *Stunt Island* who won't browse the repository should be able to read the research notes as a website, with search and navigation. The repository stays the only copy of what the site shows: nobody edits or syncs a second copy, and the site rebuilds itself from `main`. More sections (`GLOSSARY.md`, `docs/howto/`, pages written for the site) may be added later.

## Goals

- Every note under `research/` becomes a page at `https://neilsh.github.io/stunt-reel/`, with full-text search and a sidebar that follows the folder layout.
- Mermaid diagrams render, and so does the LaTeX math (`$…$`) that about 20 notes use (for example `$\text{offsets}[i] \le \text{file\_len}$`); without math support it shows as raw text and its underscores turn into italics.
- The site deploys from CI on each push to `main` that touches the published set or the site's own files.
- Links between published pages work on the site, anchors included. Links to anything outside the published set, and to non-Markdown files inside it, open on github.com.
- Adding a section later is a new entry in one list, with no change to the prep script.
- A reader new to the notes can decode them: a "How to read these notes" page and the glossary are one click from the landing page.
- Every page links to its source on github.com.

## Non-goals

- Polish beyond Starlight's defaults: no custom theme, no rendering of `.ksy` schemas.
- Publishing anything outside `research/` and `GLOSSARY.md` in this work. Publishing `docs/SPEC.md`, which would turn the `[I1]`–`[I8]` links into site links, is a follow-up.
- A gallery of the error-example sheets, generated from `error-categories.toml`: a follow-up, and the first thing that would put screenshots on the site.
- Last-updated dates (they need full git history in CI) and keeping code blocks out of search (wait and see whether they clutter results).
- Versioned docs or previews of each PR.

## Anti-goals

- A second copy of any note in git, or a step someone must remember to run by hand.
- Unpinned tool versions: the build must not change because a package released that day.
- Making the local `mise run check` slower, or needing Bun, for changes that touch only `research/` or the prep script.
- Hosting a game-derived image on the site that [`NOTICE.md`](../../../NOTICE.md) would not allow in the repository.

## Approaches considered

1. **Starlight (Astro), with a prep script. Chosen.** It is actively maintained, built for docs readers (Pagefind search, sidebar from folders), and parses plain `.md` without the MDX parser, so raw `<` in byte-layout prose is safe.
2. **Material for MkDocs, or its successor Zensical.** It would fit the Python toolchain. Material entered maintenance mode in November 2025 with fixes promised for about a year, and Zensical's plugin and hook support was still partial in 2026.
3. **Quartz.** It gives backlinks and a graph view, but you install it by copying its whole repository into yours, so every upgrade is manual, and it looks like a notebook rather than a reference manual.

Docsify (client-side rendering, poor search-engine indexing), Jekyll (Pages can't publish from `research/`; no Mermaid), and Docusaurus or VitePress (their MDX and Vue template parsers choke on raw `<` and `{{`) were dropped.

## Design

### Toolchain and files

- `mise.toml` pins Bun at an exact version beside Rust and Python, and `mise.lock` is regenerated as the `mise.toml` header describes. `bunx` stays available for one-off commands.
- `site/` is tracked and holds `package.json`, `bun.lock`, `astro.config.mjs`, `published.toml`, `index.md` (the landing page) and `reading.md` (How to read these notes).
- Gitignored: `site/node_modules/`, `site/.astro/`, `site/src/content/docs/` (generated, recreated on every run) and `site/dist/` (already caught by the root `dist/` pattern, which is fine).
- Renovate (`.github/renovate.jsonc`, not Dependabot) proposes bumps to `site/package.json` and `bun.lock`. Its bun manager must be enabled, and a bump that leaves `bun.lock` stale must fail.

### Published set

`site/published.toml` lists each repository path and the sidebar section it becomes; it starts with `research/` and `GLOSSARY.md`. The prep script reads it, and the Astro config reads the same file (or a JSON sidebar the prep script writes) so the list exists once.

### Prep script

The module goes in `python/stunt_reel/`, the CLI in `python/scripts/` (as `knowledge_map.py` does over `research_notes.py`), and a row goes in [`docs/architecture-python.md`](../../../docs/architecture-python.md). It reuses `frontmatter.read_frontmatter`, the `markdown_links` parser and `research_notes.note_paths` rather than new parsers.

Each run it deletes and recreates `site/src/content/docs/`, copies `site/index.md` (the home page) and `site/reading.md` there, then copies each `.md` file in the published set, and:

- sets `editUrl` to the source file's `https://github.com/neilsh/stunt-reel/blob/main/<path>`, with Starlight's edit-link label changed to "View source on GitHub". Starlight's global `editLink.baseUrl` can't do this, because generated paths differ from repository paths. The two hand-written pages point at their `site/` sources.

- sets `title` from the first `#` heading and removes that heading from the body. All 68 notes have one, and no link targets a note's H1.
- sets `description` from `summary:`. `research/README.md` and `MAP.md` have no front matter, so they get no description. `MAP.md`'s leading "generated" HTML comment is dropped.
- rewrites every relative link, keeping any `#anchor`:

| Link target | Becomes |
|---|---|
| `.md` file in the published set | its site page URL |
| directory in the published set | its `INDEX.md` or `README.md` page if one exists, else `https://github.com/neilsh/stunt-reel/tree/main/<path>` |
| image in the published set (`.png`) that the page links or embeds | the copied image's site URL |
| any other file in the published set (`.ksy`, `.toml`) | `https://github.com/neilsh/stunt-reel/blob/main/<path>` |
| file outside the published set | `…/blob/main/<path>` |
| directory outside the published set | `…/tree/main/<path>` |
| absolute URL | unchanged |

Links inside code spans and fences are left alone. An image in the published set is copied as a static file only when a published page links or embeds it. Today none does: no note links an individual sheet in `research/parity/error-examples/`, only the folder, and `error-categories.toml` names them. So the first build copies no image. Images outside the set, such as those in work folders, stay on github.com through the outside-file rule.

### Screenshots and `NOTICE.md`

The same PR amends `NOTICE.md` § Illustrative comparison images with three new bullets. Today that section limits where committed images live (`research/` or `work/`) and says nothing about a website. Its only hosting sentence is about images attached to a PR description.

- **Comparison only.** The opening sentence already describes each image as a captured frame set beside this project's render of the same moment. The new bullet makes that a rule for every image: a captured frame appears only inside a comparison, alongside our render of the same moment, never on its own.
- **Comparison sheets.** A sheet may show one captured screen with our render, their difference and enlarged crops of that same screen. The existing "a single 320x200 screen, or a crop or enlargement of one" limit applies to the captured content, not to the sheet's total size. All 15 error-example sheets have this layout (1288×1020: capture, render, luma difference, a 2× close-up of both).
- **The site.** The project's Pages site, built from the repository, may serve a committed image that a published page cites, under the same rules. It serves no image the repository could not hold.

### Landing page

`site/index.md` is the front door. It says what the project is and links the repository, `MAP.md` (the full note list), the glossary and the reading guide.

`site/reading.md`, "How to read these notes", is a short legend for a newcomer:
- **Evidence tags:** what `[Bounded Observation]`, `[Supported Inference]` and `[Hypothesis]` mean, in a sentence each, linking `docs/SPEC.md` for the full definitions rather than restating them.
- **Anchors:** what `[FMT-*]`, `[MEM-*]` and `[I*]` anchors are.
- **GitHub links:** why links to `work/`, `docs/` and code open on github.com.

The legend is the one piece of hand-written prose that can drift from its sources. It stays short and points to the sources for anything beyond one line. It states that the notes are CC BY 4.0 except quoted third-party material, the master palette and the `.SOD` scale table, and links `NOTICE.md` and `research/README.md` for the terms.

### Tasks, gate and CI

- `mise run site` runs `bun install --frozen-lockfile`, the prep script and `bun run build`. `mise run site -- --serve` previews locally.
- The local gate ([ADR 0038](../../../docs/adr/0038-the-local-gate-runs-what-a-change-touches.md), `python/scripts/gate.py`) is unchanged and never builds the site:
  - A change that touches only `research/` stays "docs" and runs only the docs tests, which already check its source links.
  - The prep script's Python changes fall in "python".
  - `site/**` falls in "other" and runs the full gate. That is slow but rare, and it avoids editing `gate.py`, its tests and ADR 0038 for the first cut. Add a `site` category later if site edits become frequent.
- A Pages workflow builds the site on pull requests that touch the published set, `site/`, or the prep script. On push to `main` it deploys with `actions/configure-pages`, `actions/upload-pages-artifact` and `actions/deploy-pages`, pinned by SHA like `ci.yml`'s actions. It needs `pages: write` and `id-token: write` permissions. These are GitHub-owned actions, which the repository's allowed-actions policy already admits.
- The site build validates links and anchors, failing on a missing page or fragment, so a heading slug that differs between GitHub and Starlight is caught.
- The site is served under `/stunt-reel/`. `astro.config.mjs` sets `site` and `base`, which also gives a sitemap and a 404 page. Links the prep script writes must work under that base: the likeliest first-build bug, so the link check runs against the built site.

### Tests

- The prep script has unit tests on synthetic notes: one case per row of the link table, plus title and description extraction, the files without front matter, image copying, and links inside code spans.
- The CI build over the real `research/` is the integration test. It covers the 6 files with Mermaid fences, the notes with math, and the notes with raw `<` or HTML in prose.

## Left to the builder

- The Mermaid integration: rendered at build time or in the browser.
- The math integration (for example `remark-math` with `rehype-katex`), pinned like the rest.
- Confirming that `mise.lock` gets Bun for both linux-x64 and windows-x64, and that Renovate's default managers pick up `bun.lock` (the config lists none explicitly).
- The link checker: `starlight-links-validator`, or the prep script's own check, as long as it validates fragments.
- The page URL scheme Starlight gives `INDEX.md` and `README.md`, the base path `/stunt-reel/`, and the trailing-slash setting.
- Whether the main CI gate installs Bun, or only the Pages workflow does.

## Owner steps

- Turn on Pages with "GitHub Actions" as the source in the repository settings.
