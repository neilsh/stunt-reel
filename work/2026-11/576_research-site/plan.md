# Research site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish `research/` and `GLOSSARY.md` as a Starlight site on GitHub Pages, built from the repository on every push to `main`.

**Architecture:** A Python prep step (`stunt_reel.site_pages`, CLI `python/scripts/site_prep.py`) turns the published set listed in `site/published.toml` into Starlight content. It sets each page's title, description and source link and rewrites every relative link. Starlight in `site/`, with Bun pinned by mise, builds and link-checks the result. A Pages workflow builds it on PRs and deploys it from `main`.

**Tech Stack:** Python 3.15 (uv), Bun, Astro + `@astrojs/starlight`, `starlight-links-validator`, `astro-mermaid`, `remark-math` + `rehype-katex`, GitHub Actions Pages.

**Spec:** [`spec.md`](spec.md)

## Global Constraints

- Site URL `https://neilsh.github.io/stunt-reel/`: Astro `site: "https://neilsh.github.io"`, `base: "/stunt-reel"`, `trailingSlash: "always"`.
- Repository URL for source links: `https://github.com/neilsh/stunt-reel`; files link as `/blob/main/<path>`, directories as `/tree/main/<path>`.
- Every tool and package version is exact: Bun in `mise.toml` plus `mise.lock`, npm packages with `bun add --exact` plus `bun.lock`, and actions pinned by SHA with a `# vX.Y.Z` comment, as in `ci.yml`.
- `python/scripts/gate.py`, its tests and ADR 0038 are not changed. The local gate never builds the site.
- Generated and gitignored: `site/node_modules/`, `site/.astro/`, `site/src/content/docs/`, `site/src/generated/`, `site/public/media/` (`site/dist/` is already covered by the root `dist/` pattern).
- The prep step writes POSIX paths and URLs on every platform.
- Docstrings follow [docs/development.md § Docstrings](../../../docs/development.md#docstrings-and-doc-comments): the caller's contract, fewest words.

## Review Focus

1. **Uppercase file names.** Pages for `INDEX.md`, `README.md` and `MAP.md` get the URLs `page_url` predicts, since Starlight lowercases names and folds `index`. Checked in Task 4 Step 5 against `site/dist/`.
2. **Dollar signs.** A `$` that isn't math must not swallow text. The table ranges in `formats/all.md` (`$1..32767$`) are math by intent; 22 notes use `$…$`. Task 4 Steps 6 and 8 inspect that page.
3. **Link shapes.** Reference-style definitions and link text holding code must be rewritten, and links inside code must not. `MARKDOWN_LINK_REGEX` takes no nested brackets in link text; no note uses them. Task 1 tests.
4. **Fragments on rewritten links.** A fragment survives on a page, directory or blob link (`../../docs/SPEC.md#24-…`). Task 1 tests.
5. **Stale output.** A deleted note leaves no page behind on the next run, and a run on Windows writes POSIX paths. Task 3 tests.

## Execution

Run with `superpowers:subagent-driven-development`, under the repository's override in [docs/harness.md § Policy](../../../docs/harness.md#policy-any-agent): one fresh review of the finished branch, no review after each task. Each dispatch names its model explicitly.

| Dispatch | Tasks | Model | Why |
|---|---|---|---|
| A | 1–3, the Python prep step | Sonnet | Well specified, but written from prose with edge cases. One implementer, because the three tasks share one module and one test fixture, and a fresh context per task would re-read them twice. |
| B | 4, the Starlight build | Sonnet | Integration with packages whose APIs the plan can't fix exactly. If it reports BLOCKED on a link or build failure it can't explain, re-dispatch on Opus. |
| C | 4's browser look (Step 8) | Haiku | Browser UI, per `docs/harness.md`. If a subagent has no browser-pane tools, the controller does it (about five tool calls). |
| D | 5, the Pages workflow | Haiku | The plan holds the whole workflow; the work is looking up two SHAs and transcribing. |
| E | 6, prose and NOTICE | Sonnet | Short pages that summarise `docs/SPEC.md` and must not overclaim. |
| Final review | the branch | Opus | `docs/harness.md` sends the first review of a Sonnet-built branch to Opus. It also does the `AGENTS.md` § Committing item 5 check on `NOTICE.md`, `site/index.md`, `site/reading.md`, `docs/architecture-python.md` and the work README. |

`docs/harness.md` routes clear-spec work to dsh first, but dsh is an Orca worker, not a subagent this skill can dispatch; run this plan through Orca instead to use it for Dispatches A and D.

Implementers run scoped checks while iterating (`mise run test-py -- <file>`, `mise run check-py`) and `mise run check` once before their dispatch's last commit; a change to a non-Markdown file under `site/` makes that the full gate (`gate.py` classifies `.md` as docs first). They commit but never push. The controller pushes and opens the PR after the final review, and Task 5 is validated there, by the PR's checks.

---

### Task 1: Page URLs and link rewriting

**Files:**
- Create: `python/stunt_reel/site_pages.py`
- Test: `tests/test_site_pages.py`

**Interfaces:**
- Consumes: `stunt_reel.markdown_links.prose`, `MARKDOWN_LINK_REGEX`, `LINK_DEFINITION_REGEX`, `URL_SCHEME_REGEX`.
- Produces:
  - `BASE = "/stunt-reel"`, `REPO_URL = "https://github.com/neilsh/stunt-reel"`, `IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".gif", ".svg"})` (the spec names `.png`, the only kind committed today; the rest are the kinds a note could add)
  - `@dataclass(frozen=True) class Site: root: Path; pages: Mapping[str, str]; published_dirs: tuple[str, ...]` (`pages`: repo-relative POSIX path of each published `.md` → its path under the content root; `published_dirs`: the directory sources of the published set)
  - `page_url(content_path: str) -> str`
  - `link_target(target: str, source: str, site: Site, images: set[str]) -> str`
  - `rewrite_links(text: str, source: str, site: Site, images: set[str]) -> str`

- [ ] **Step 1: Write the failing tests**

Build a `Site` over a `tmp_path` tree holding `research/formats/INDEX.md`, `research/formats/sod.md`, `research/README.md`, `research/parity/error-examples/a.png`, `research/x.ksy`, `docs/SPEC.md`, `work/2026-11/1_a/images/b.png` and the empty directories `crates/core/` and `research/noindex/`. Its `pages` maps `research/**.md` to themselves and `GLOSSARY.md` to `glossary.md`, and `published_dirs=("research",)`.

```python
def test_page_url_lowercases_and_folds_index():
    assert page_url("research/formats/sod.md") == "/stunt-reel/research/formats/sod/"
    assert page_url("research/formats/INDEX.md") == "/stunt-reel/research/formats/"
    assert page_url("research/README.md") == "/stunt-reel/research/readme/"
    assert page_url("index.md") == "/stunt-reel/"

def test_page_url_rejects_unslugged_names():
    with pytest.raises(ValueError, match="a b.md"):
        page_url("research/a b.md")

@pytest.mark.parametrize(("source", "target", "expected"), [
    ("research/formats/sod.md", "INDEX.md#magic", "/stunt-reel/research/formats/#magic"),
    ("research/formats/sod.md", "../../GLOSSARY.md", "/stunt-reel/glossary/"),
    ("research/formats/sod.md", "../formats/", "/stunt-reel/research/formats/"),
    ("research/formats/sod.md", "../", "/stunt-reel/research/readme/"),
    ("research/formats/sod.md", "../noindex/", f"{REPO_URL}/tree/main/research/noindex"),
    ("research/formats/sod.md", "../x.ksy", f"{REPO_URL}/blob/main/research/x.ksy"),
    ("research/formats/sod.md", "../../docs/SPEC.md#24-evidentiary", f"{REPO_URL}/blob/main/docs/SPEC.md#24-evidentiary"),
    ("research/formats/sod.md", "../../crates/core/", f"{REPO_URL}/tree/main/crates/core"),
    ("research/formats/sod.md", "../../work/2026-11/1_a/images/b.png", f"{REPO_URL}/blob/main/work/2026-11/1_a/images/b.png"),
    ("research/formats/sod.md", "../parity/error-examples/a.png", "/stunt-reel/media/research/parity/error-examples/a.png"),
    ("research/formats/sod.md", "https://example.com/a.md", "https://example.com/a.md"),
    ("research/formats/sod.md", "#local", "#local"),
])
def test_link_target(site, source, target, expected): ...
    # and: the image case adds "research/parity/error-examples/a.png" to `images`; no other case adds anything

def test_link_target_refuses_escape(site):
    with pytest.raises(ValueError, match="research/formats/sod.md"):
        link_target("../../../../x.md", "research/formats/sod.md", site, set())

def test_rewrite_links_inline_reference_and_code(site):
    text = "See [`sod` v2](sod.md) and [spec].\n\n[spec]: ../../docs/SPEC.md#tiers\n\n`[no](sod.md)`\n```\n[no](sod.md)\n```\n"
    out = rewrite_links(text, "research/formats/sod.md", site, set())
    assert "[`sod` v2](/stunt-reel/research/formats/sod/)" in out
    assert f"[spec]: {REPO_URL}/blob/main/docs/SPEC.md#tiers" in out
    assert out.count("[no](sod.md)") == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `mise run test-py -- tests/test_site_pages.py`
Expected: FAIL, `ModuleNotFoundError: stunt_reel.site_pages`

- [ ] **Step 3: Implement in `python/stunt_reel/site_pages.py`**

- `page_url`: lowercase each segment and strip `.md`. Raise `ValueError` naming the path when a segment doesn't match `[A-Za-z0-9-]+`. Drop a final `index` segment. Return `f"{BASE}/{path}/"`, or `f"{BASE}/"` for the root.
- `link_target`: leave unchanged anything matching `URL_SCHEME_REGEX`, starting with `#` or `/`, or empty. Otherwise split off the fragment, `unquote` the path and resolve it against `source`'s directory with `posixpath.normpath`. A path that escapes the root raises `ValueError` naming source and target. Then classify in this order:
  1. a page in `pages`;
  2. a directory (`site.root / p` is a dir) → its `INDEX.md`, else its `README.md`, if published, else the tree URL;
  3. an image suffix inside a `published_dirs` entry → `f"{BASE}/media/{p}"`, added to `images`;
  4. anything else → the blob URL.

  Keep the fragment on every result.
- `rewrite_links`: find matches of both regexes in `prose(text)`, which blanks code but keeps offsets. Replace each `group(1)` span in the original text, last first.

- [ ] **Step 4: Run to verify they pass**

Run: `mise run test-py -- tests/test_site_pages.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/stunt_reel/site_pages.py tests/test_site_pages.py
git commit -m "feat(site): page URLs and link rewriting for the research site (#576)"
```

### Task 2: Page front matter

**Files:**
- Modify: `python/stunt_reel/site_pages.py`
- Test: `tests/test_site_pages.py`

**Interfaces:**
- Consumes: Task 1's `Site`, `rewrite_links`, `REPO_URL`; `stunt_reel.frontmatter.read_frontmatter`; `markdown_links.prose`.
- Produces: `page_text(text: str, source: str, site: Site, images: set[str]) -> str`, the content page written for repo file `source`.

- [ ] **Step 1: Write the failing tests**

```python
NOTE = '---\nsummary: "`.SOD` model: a **VM**."\n---\n# Spec: `.SOD` [format](x.md) **bytecode**\n\nBody [l](sod.md).\n'

def test_page_text_title_from_h1_and_description_from_summary(site):
    fields, body = _fields(page_text(NOTE, "research/formats/sod.md", site, set()))
    assert fields["title"] == "Spec: .SOD format bytecode"
    assert fields["description"] == "`.SOD` model: a **VM**."
    assert fields["editUrl"] == f"{REPO_URL}/blob/main/research/formats/sod.md"
    assert not body.lstrip().startswith("# ")
    assert "[l](/stunt-reel/research/formats/sod/)" in body

def test_page_text_sidebar_labels(site):
    # sidebar.label is the file stem; INDEX.md -> "Index", README.md -> "About this folder"

def test_page_text_without_frontmatter_drops_leading_comment(site):
    text = "<!-- Generated by mise run fix; do not edit. -->\n\n# Research map\n\n- x\n"
    fields, body = _fields(page_text(text, "research/MAP.md", site, set()))
    assert fields["title"] == "Research map"
    assert "description" not in fields
    assert "<!--" not in body

def test_page_text_keeps_a_handwritten_title(site):
    text = '---\ntitle: "How to read these notes"\n---\n\n# Evidence tags\n'
    fields, body = _fields(page_text(text, "site/reading.md", site, set()))
    assert fields["title"] == "How to read these notes"
    assert "# Evidence tags" in body
    assert fields["editUrl"] == f"{REPO_URL}/blob/main/site/reading.md"

def test_page_text_h1_inside_code_is_not_the_title(site):
    # a fenced "# not a title" before the real H1 is skipped
```

`read_frontmatter` raises on the `sidebar:` line, and PyYAML isn't a dependency. The tests use a helper `_fields(page) -> tuple[dict[str, object], str]` that reads each top-level `key: <json>` line between the `---` fences with `json.loads`, reads `sidebar:`'s indented `label:` line as `fields["sidebar.label"]`, and returns the body after the closing fence.

Sidebar labels are the file stem because the notes' titles are long (`` `PLAYONE.EXE`: SOD Display-List VM & `OP_TAP` Semantics ``) and the spec's sidebar follows the folder layout; "Index" and "About this folder" keep the uppercase files from reading as `INDEX` and `README`.

- [ ] **Step 2: Run to verify they fail**

Run: `mise run test-py -- tests/test_site_pages.py -k page_text`
Expected: FAIL, `ImportError: cannot import name 'page_text'`

- [ ] **Step 3: Implement `page_text`**

- **Title:** the source's front matter `title` if present (its body heading stays). Otherwise the first `# ` line outside code, found on `prose(text)`, which is removed from the body, with backticks and `**` stripped and `[text](url)` reduced to `text`. A note with neither raises `ValueError` naming `source`.
- **Description:** front matter `description`, else `summary`, else omitted.
- **Leading comment:** a single-line `<!-- … -->` before the H1 is dropped.
- **Output:** write the front matter as `key: <json.dumps(value, ensure_ascii=False)>` lines, which are valid YAML (`ensure_ascii=False` keeps non-ASCII text readable), plus `sidebar:\n  label: <json>`. The order is `title`, `description`, `editUrl`, `sidebar`. Then the body after `rewrite_links`.

- [ ] **Step 4: Run to verify they pass**

Run: `mise run test-py -- tests/test_site_pages.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/stunt_reel/site_pages.py tests/test_site_pages.py
git commit -m "feat(site): title, description and source link for each site page (#576)"
```

### Task 3: Prepare command

**Files:**
- Modify: `python/stunt_reel/site_pages.py`
- Create: `python/scripts/site_prep.py`, `site/published.toml`, and stubs `site/index.md` and `site/reading.md` holding only their `title:` front matter (Task 6 writes their text)
- Modify: `mise.toml` (task `site-prep`), `docs/architecture-python.md:23` (add `site_pages.py` and `site_prep.py` and "the research site" to the doc-tooling row)
- Test: `tests/test_site_prep.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `@dataclass(frozen=True) class Section: source: str; dest: str; label: str`
  - `load_sections(text: str) -> list[Section]`
  - `prepare(root: Path, site_dir: Path) -> tuple[int, int]`, which returns (pages written, images copied). It writes `site_dir/src/content/docs/**`, `site_dir/public/media/**` and `site_dir/src/generated/sidebar.json`.
  - CLI `python/scripts/site_prep.py [--root DIR]`; mise task `site-prep`.

`site/published.toml`:

```toml
# The repository paths the research site publishes; python/scripts/site_prep.py reads it.
# `source` is a repo-relative file or directory, `dest` its path under the site's content root.
[[section]]
source = "research"
dest = "research"
label = "Research notes"

[[section]]
source = "GLOSSARY.md"
dest = "glossary.md"
label = "Glossary"
```

- [ ] **Step 1: Write the failing tests** (`tests/test_site_prep.py`, using a `tmp_path` repo with `site/published.toml`, `site/index.md`, `site/reading.md`, two notes, `GLOSSARY.md` and one PNG that a note links)

```python
def test_load_sections_rejects_bad_paths():
    # missing key, absolute source, or ".." in source or dest -> ValueError naming the section

def test_prepare_writes_pages_media_and_sidebar(repo):
    pages, images = prepare(repo, repo / "site")
    assert (pages, images) == (5, 1)
    docs = repo / "site/src/content/docs"
    assert (docs / "research/formats/sod.md").is_file()
    assert (docs / "glossary.md").is_file() and (docs / "index.md").is_file()
    assert (repo / "site/public/media/research/parity/error-examples/a.png").is_file()
    assert json.loads((repo / "site/src/generated/sidebar.json").read_text()) == [
        {"slug": "reading"},
        {"label": "Research notes", "autogenerate": {"directory": "research"}},
        {"label": "Glossary", "slug": "glossary"},
    ]

def test_prepare_removes_stale_output(repo):
    prepare(repo, repo / "site"); (repo / "research/formats/sod.md").unlink(); prepare(repo, repo / "site")
    assert not (repo / "site/src/content/docs/research/formats/sod.md").exists()

def test_prepare_writes_posix_urls(repo):
    # every rewritten link in every written page contains no backslash

def test_cli_exits_1_naming_the_bad_note(repo, capsys):
    # a note with no H1 -> main(["--root", str(repo)]) == 1 and stderr names it
```

- [ ] **Step 2: Run to verify they fail**

Run: `mise run test-py -- tests/test_site_prep.py`
Expected: FAIL, `ImportError`

- [ ] **Step 3: Implement**

- `prepare` builds `Site`:
  - `pages`: every `.md` under each directory section (sorted `rglob`, POSIX relative paths) mapped under its `dest`, each file section mapped to its `dest`, plus `site/index.md` → `index.md` and `site/reading.md` → `reading.md`.
  - `published_dirs`: the directory sources.
- It deletes the three output locations, writes `page_text` for every page, copies each collected image to `public/media/<repo path>`, and writes the sidebar as in the test.
- `site_prep.py` follows `knowledge_map.py`: a module docstring with usage and exit status, `main(argv) -> int`, and `REPO_ROOT` from `__file__`. It prints `wrote N pages and M images to site/`, and on `ValueError`/`FrontmatterError` prints the message to stderr and returns 1.
- mise task:

```toml
[tasks.site-prep]
description = "Write the research site's Starlight content (site/src/content/docs, site/public/media, the sidebar) from the published set in site/published.toml; mise run site runs it first"
run = "uv run python python/scripts/site_prep.py"
```

- [ ] **Step 4: Run to verify they pass, then on the real tree**

Run: `mise run test-py -- tests/test_site_prep.py tests/test_site_pages.py`, then `mise run site-prep`
Expected: PASS, then `wrote 71 pages and 0 images to site/`. That is the 68 `.md` files under `research/`, plus `GLOSSARY.md`, plus the 2 hand-written pages. No note links an individual image yet.

- [ ] **Step 5: Commit**

```bash
git add python/stunt_reel/site_pages.py python/scripts/site_prep.py site/published.toml site/index.md site/reading.md tests/test_site_prep.py mise.toml docs/architecture-python.md
git commit -m "feat(site): prepare the research site's content from site/published.toml (#576)"
```

### Task 4: Starlight site

**Files:**
- Modify: `mise.toml` (`bun` pin; tasks `site`, `site-serve`), `mise.lock`, `.gitignore`
- Create: `site/package.json`, `site/bun.lock`, `site/astro.config.mjs`, `site/src/content.config.ts`, `site/src/content/i18n/en.json`

**Interfaces:**
- Consumes: Task 3's `site-prep` task, `site/src/generated/sidebar.json`, and the stub `site/index.md` and `site/reading.md`.
- Produces: `mise run site` → `site/dist/`, the input Task 5 uploads and Task 6 rebuilds; `mise run site-serve` for local preview.

- [ ] **Step 1: Pin Bun**

Add `bun = "<newest release from mise latest bun>"` to `[tools]` with a one-line comment ("the research site's build; site/package.json"). Then run `GITHUB_TOKEN=$(gh auth token) mise lock --platform linux-x64,windows-x64`.
Expected: `mise.lock` gains `bun` entries for both platforms. `ci.yml` names its tools in `install_args`, so the main gate still doesn't install Bun; only the Pages workflow does (the spec left this to the builder).

- [ ] **Step 2: Create the Bun project**

In `site/`, write `package.json` with `"private": true` and `"type": "module"`, plus the scripts `"build": "astro build"` and `"dev": "astro dev"`. Then run `bun add --exact astro @astrojs/starlight starlight-links-validator astro-mermaid mermaid remark-math rehype-katex katex`.
Expected: `package.json` holds exact versions only (no `^`), and `bun.lock` exists. `.github/renovate.jsonc` extends `config:recommended` and sets no `enabledManagers`, so Renovate's default `bun` manager covers both files; confirm no `packageRules` entry disables it. A bump that leaves `bun.lock` stale fails `bun install --frozen-lockfile` in CI.

- [ ] **Step 3: Write the config**

`site/astro.config.mjs`:

```js
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import starlightLinksValidator from "starlight-links-validator";
import mermaid from "astro-mermaid";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import sidebar from "./src/generated/sidebar.json" with { type: "json" };

export default defineConfig({
  site: "https://neilsh.github.io",
  base: "/stunt-reel",
  trailingSlash: "always",
  markdown: { remarkPlugins: [remarkMath], rehypePlugins: [rehypeKatex] },
  integrations: [
    mermaid(), // before starlight, as astro-mermaid requires
    starlight({
      title: "Stunt Reel research",
      social: [{ icon: "github", label: "GitHub", href: "https://github.com/neilsh/stunt-reel" }],
      customCss: ["katex/dist/katex.min.css"],
      sidebar,
      plugins: [starlightLinksValidator()],
    }),
  ],
});
```

- `content.config.ts` defines `docs` (`docsLoader()`/`docsSchema()`) and `i18n` (`i18nLoader()`/`i18nSchema()`).
- `en.json` is `{ "page.editLink": "View source on GitHub" }`.
- `.gitignore` gets the five generated paths from Global Constraints under a `# Research site (site/)` comment.
- If an installed package's current API differs from the above (option names, plugin order), follow its README and note the difference in the commit body.

- [ ] **Step 4: Add the tasks and build**

```toml
[tasks.site]
description = "Build the research site into site/dist: mise run site-prep, then Starlight, failing on a broken link or anchor; the Pages workflow deploys this build"
depends = ["site-prep"]
dir = "{{config_root}}/site"
run = ["bun install --frozen-lockfile", "bun run build"]

[tasks.site-serve]
description = "Preview the research site at http://localhost:4321/stunt-reel/, after mise run site-prep"
depends = ["site-prep"]
dir = "{{config_root}}/site"
run = ["bun install --frozen-lockfile", "bun run dev"]
```

The spec's `mise run site -- --serve` becomes a separate `site-serve` task: a mise `run` list can't branch on an argument without a wrapper script.

Run: `mise run site`
Expected: the build ends `Complete!`, and `starlight-links-validator` reports all links valid. A failure names a link: fix the prep step (Tasks 1–2, with a new test) or the config, never the note.

- [ ] **Step 5: Check URLs against the build** (Review Focus 1)

Run: `ls site/dist/research/formats/index.html site/dist/research/formats/sod/index.html site/dist/research/readme/index.html site/dist/research/map/index.html site/dist/glossary/index.html site/dist/reading/index.html site/dist/404.html site/dist/sitemap-index.xml`
Expected: all exist. If Starlight names a page differently, change `page_url` and its test to match, then rebuild.

- [ ] **Step 6: Check the risky pages in the HTML** (Review Focus 2)

Run against `site/dist/research/formats/all/index.html`: `grep -c 'class="katex"'` (expect ≥ 1), `grep -c '\$1\.\.32767\$'` (expect 0: the range was typeset, not left raw) and `grep -c 'blob/main/research/formats/all.md'` (expect ≥ 1: the "View source on GitHub" link). Then `grep -rl mermaid site/dist/research --include=index.html | wc -l`.
Expected: the counts above, and 6 pages carrying astro-mermaid's diagram markup, one per note with a Mermaid fence.

- [ ] **Step 7: Commit**

```bash
git add mise.toml mise.lock .gitignore site/package.json site/bun.lock site/astro.config.mjs site/src/content.config.ts site/src/content/i18n/en.json
git commit -m "feat(site): Starlight build of the research site (#576)"
```

- [ ] **Step 8: Browser look** (Dispatch C, after the commit)

Start `mise run site-serve` in the background, open `http://localhost:4321/stunt-reel/research/formats/all/` and `…/research/playone-exe/sod-vm/` in the browser pane, and take a screenshot of each.
Expected: the table's math is typeset, no text vanished after a `$` or a raw `<`, and the Mermaid diagram is drawn rather than shown as source. Report any page that fails; Dispatch B's implementer fixes it.

### Task 5: Pages workflow

**Files:**
- Create: `.github/workflows/pages.yml`

**Interfaces:**
- Consumes: `mise run site` → `site/dist/`.

- [ ] **Step 1: Write the workflow**

```yaml
name: Pages
on:
  push:
    branches: [main]
    paths: &paths
      - "research/**"
      - "GLOSSARY.md"
      - "site/**"
      - "python/stunt_reel/site_pages.py"
      - "python/stunt_reel/frontmatter.py"
      - "python/stunt_reel/markdown_links.py"
      - "python/scripts/site_prep.py"
      - "pyproject.toml"
      - "uv.lock"
      - "mise.toml"
      - "mise.lock"
      - ".github/workflows/pages.yml"
  pull_request:
    paths: *paths
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: pages-${{ github.ref }}
  # A PR's stale build is cancelled; a deploy from main runs to completion.
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: jdx/mise-action@6be3c7ed4c21d4f76b208d351d95aac273ebb76d # v5.2.4
        with:
          install_args: bun python uv
      - run: mise run site
      - if: github.event_name != 'pull_request'
        uses: actions/upload-pages-artifact@<sha> # vX
        with:
          path: site/dist
  deploy:
    if: github.event_name != 'pull_request' && github.ref == 'refs/heads/main'
    needs: build
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@<sha> # vX
```

Look up each `<sha>` from the action's newest release tag (`gh api repos/actions/<name>/git/ref/tags/<tag>`; dereference an annotated tag to its commit). If GitHub rejects YAML anchors in `on.paths`, repeat the list instead.

The spec names `actions/configure-pages` too. It is left out: Astro's own Pages workflow doesn't use it, `astro.config.mjs` already sets `site` and `base`, and it would need a `pages` permission in the build job. The prep step's imports (`frontmatter.py`, `markdown_links.py`) and the Python lock are in `paths`, because a change to them can break the build.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/pages.yml
git commit -m "ci(site): build the research site on PRs and deploy it to Pages from main (#576)"
```

The repository has no workflow linter, so the PR is the test: once the controller opens it, `gh pr checks` shows `Pages / build` passing and no deploy job. The first deploy, on merge, needs the owner step (Pages source set to "GitHub Actions") done first.

### Task 6: Landing page, reading guide, NOTICE.md and handoff

**Files:**
- Modify: `site/index.md`, `site/reading.md` (Task 3's stubs), `NOTICE.md` § Illustrative comparison images, `work/2026-11/576_research-site/README.md`

**Interfaces:**
- Consumes: `mise run site` (Task 4), which rewrites the pages' links like any note's and fails on a broken one.

- [ ] **Step 1: Write the two pages**

- **`site/index.md`:** front matter `title: "Stunt Island research notes"`. One paragraph says what Stunt Reel is (it analyses, documents and reconstructs *Stunt Island*, 1992) and that these pages are its research notes. Links: "How to read these notes" (`reading.md`), the full note list (`../research/MAP.md`), the glossary (`../GLOSSARY.md`) and the repository.
- **`site/reading.md`:** front matter `title: "How to read these notes"`. Four short sections:
  - **Evidence tags:** one line each for `[Established]`, `[Supported Inference]`, `[Bounded Observation]`, `[Hypothesis]` and `[Unknown]`, linking `../docs/SPEC.md#24-evidentiary-tiers--contract-anchor-system` for the definitions. Each line paraphrases SPEC § 2.4 and claims no more than it does.
  - **Anchors:** `[FMT-*]` a format fact, `[MEM-*]` a runtime memory fact, `[I1]`–`[I8]` an architectural invariant, linking SPEC § 2.
  - **Links to GitHub:** work journals, design docs and code open on github.com.
  - **Licence:** the notes are CC BY 4.0 except quoted third-party material, the Stunt Island master palette and the `.SOD` scale table; see `../NOTICE.md` and `../research/README.md`.

  Write the links relative to `site/`, so the prep step rewrites them like any note's.

- [ ] **Step 2: Rebuild**

Run: `mise run site`
Expected: `Complete!` with all links valid, the two pages' links included.

- [ ] **Step 3: Add the three bullets** to `NOTICE.md`'s bullet list, between "holds nothing extracted…" and "lives under…", keeping its wrapping. That position keeps the PR paragraph's "same first two limits" pointing at the size and extraction bullets, and the list's last bullet keeps its period:

```markdown
- shows a captured frame only inside a comparison, beside this project's render of the same
  moment, never on its own;
- may be a comparison sheet: one captured screen with our render, their difference and enlarged
  crops of that same screen; the 320x200 limit above applies to the captured content, not to
  the sheet;
```

And after the list, before the PR-description paragraph:

```markdown
The project's research site, which GitHub Pages builds from this repository, may serve a
committed image that a published page cites, under the same rules. It serves no image the
repository could not hold.
```

- [ ] **Step 4: Write the handoff** in the work folder README: the question (one line from the spec's Intent), links to the spec and the plan, and the owner step to turn on Pages with the "GitHub Actions" source. The controller adds the PR link once it opens.

- [ ] **Step 5: Gate and commit**

Run: `mise run check`
Expected: PASS with no warnings.

```bash
git add site/index.md site/reading.md NOTICE.md work/2026-11/576_research-site/README.md
git commit -m "docs(site): landing page and reading guide; comparison-only screenshots in NOTICE (#576)"
```

The final review checks these pages and `NOTICE.md` under `AGENTS.md` § Committing item 5 (see Execution). The finishing PR writes the README's `outcome` and closes #576 once the first deploy is live.
