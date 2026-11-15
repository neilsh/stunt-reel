# Spike: the research site's math renderer

Issue [#576](https://github.com/neilsh/stunt-reel/issues/576). Should `site/` keep `remark-math` + `rehype-katex`, and if not, what should replace it? Checked 2026-11-15 against `6f3f4ecf` (PR [#578](https://github.com/neilsh/stunt-reel/pull/578)'s branch).

## Recommendation

**Keep `rehype-katex` 7.0.1 and `remark-math` 6.0.0. Force a single KaTeX 0.18.11 through a Bun override.**

```diff
   "dependencies": {
-    "katex": "0.16.47",
+    "katex": "0.18.11",
     ...
-  }
+  },
+  "overrides": { "katex": "0.18.11" }
```

In `.github/renovate.jsonc`, the `katex` rule changes from `allowedVersions: "<0.17.0"` to `"<0.19.0"`, and its comment changes with it. The override and the stylesheet pin then move together.

Why this version:

- **0.18.11 clears the advisory.** It is past [GHSA-238p-pmpm-9mq7](https://github.com/advisories/GHSA-238p-pmpm-9mq7), which affects KaTeX below 0.18.2 (low severity, published 2026-10-05).
- **It is the one version every consumer accepts.** It falls inside the `katex: ^0.18.0` range of `mermaid` 12.3.0. 0.19.1 renders our pages identically, but it would put mermaid outside its declared range.
- **The tree drops from two KaTeX copies to one.** Today it holds 0.16.47 (`rehype-katex`, `micromark-extension-math`, our stylesheet pin) and 0.18.10 (`mermaid/katex`). Both are below 0.18.2.

Remove the override once [remarkjs/remark-math#122](https://github.com/remarkjs/remark-math/pull/122) ships. That PR widens `rehype-katex` to `katex ^0.19.0`. When it does, move to 0.19.x if mermaid has followed by then.

If a future KaTeX ever breaks `rehype-katex` and nobody releases a fix, fall back to MathJax 4 through the local plugin under [Prototype C](#prototype-c-mathjax-4-through-a-local-plugin), in CHTML. It draws these notes about as well as KaTeX does, bold subscripts included, which Temml ([Prototype B](#prototype-b-temml-through-a-local-plugin)) does not. It is not the choice today: it adds 17 packages and 98 MB of install, and pages grow by 1.2–1.3× (CHTML) or 1.3–1.6× (SVG), with nothing to show for it on these notes.

## What "unmaintained" means here

Primary sources: the npm registry, [remarkjs/remark-math](https://github.com/remarkjs/remark-math) and the [KaTeX releases](https://github.com/KaTeX/KaTeX/releases).

- **Dormant, not abandoned.** The repository is not archived. Its last push was 2025-02-20 (`rehype-mathjax` 7.1.0). `rehype-katex` 7.0.1 dates from 2024-08-19, and `remark-math` 6.0.0 from 2023-09-19. Nine issues are open. Three PRs from 2026 (#117–#119) wait to move `rehype-mathjax` to MathJax 4. #122, the KaTeX bump, has had no maintainer response since 2026-10-14.
- **The KaTeX range is what lags.** `rehype-katex` and `micromark-extension-math` 3.1.0 both declare `katex: ^0.16.0`. KaTeX itself is active: 0.17.0 on 2026-05-22, 0.18.0 on 2026-07-17, 0.19.1 on 2026-10-23. A consumer gets the advisory fix only through an override. Issue #121 says so, and commenters on #122 report the npm and pnpm overrides working.
- **The lag is what caused CodeRabbit's skew.** `mermaid` pulls a newer KaTeX, so two copies coexisted, and `rehype-katex` rendered with the older one. KaTeX 0.18 then prefixed its internal classes ([#4229](https://github.com/KaTeX/KaTeX/issues/4229): `base` became `katex-base`, and so on), so the markup and stylesheet versions must match.
- **No API breaks for us between 0.16 and 0.19.** 0.17 changed only the internal `__defineFunction`. 0.18 prefixed the classes. 0.19 routes missing-glyph warnings through `strict`. `rehype-katex` calls only `renderToString`, and our build logs no KaTeX warning under any of the three versions.

## Options compared

| Option | Maintenance | Output and quality | CSS and fonts | Bad formula fails build? | New packages |
|---|---|---|---|---|---|
| **`rehype-katex` + KaTeX override** (recommended) | KaTeX active. Plugin dormant, but small (143 lines) and stable | Identical to today: build-time HTML plus hidden MathML | KaTeX CSS (25 KB) + KaTeX fonts, fetched per glyph set used | Yes, with the existing `failOnKatexError` | 0 |
| Temml through a local plugin (prototyped) | `temml` 0.14.0, 2026-10-08, zero dependencies, 360★ | Build-time MathML Core. Our HTML is ~half the size. Rendering is visibly weaker in Chromium (below) | `Temml-Local.css` 9 KB + a math font (STIX Two Math, 403 KB woff2) + a Starlight margin fix | Yes, with `throwOnError` in our plugin | 2 (`temml`, `@fontsource/stix-two-math`) |
| `@daiji256/rehype-mathml` 1.3.0 (Temml) | One maintainer, 10★, updated 2026-10 | As Temml | As Temml | **No.** It catches every Temml error and emits a red span with no vfile message, so we would need our own check | 2+ |
| MathJax 4 through a local plugin (prototyped) | `@mathjax/src` 4.1.3, 2026-07-03, the fourth 4.1.x release since 2025-12-15. Apache-2.0 | Build-time SVG (or CHTML) plus hidden MathML. Quality on a par with KaTeX; SVG strokes are thinner and both outputs are smaller (below). Pages 1.2–1.6× KaTeX's | SVG: 6.5 KB CSS, no fonts. CHTML: a per-page `<style>` (14–25 KB) + up to 1.8 MB of woff2, fetched per glyph set used. Either needs `not-content` on the container and the `textmacros` package | Yes, with a throwing `formatError` | 17 (`@mathjax/src`, its font, `speech-rule-engine`, `mj-context-menu`, `rimraf`, `glob` and their dependencies) |
| `rehype-mathjax` 7.1.0 | Same dormant repo. Depends on `mathjax-full` 3.2.2, which npm marks deprecated in favour of `@mathjax/src` 4; the v4 PRs are unmerged | SVG or CHTML; heavier pages | MathJax CHTML fonts or inline SVG paths | With a check like ours: since 7.1.0 it records MathJax exceptions as vfile messages | 1 + `mathjax-full` tree |
| KaTeX from our own rehype plugin | KaTeX only | Same as `rehype-katex` | Same | Yes | 0, but we maintain ~30 lines that duplicate `rehype-katex` |
| `starlight-katex` 0.0.4 | Last release 2024-10-25 | Wraps `rehype-katex` with `katex ^0.16.11`, so it has the same lag | Same | With our check | 1 + its dependencies |

No Astro- or Starlight-maintained math integration turned up. `starlight-katex` is a third-party wrapper.

## Prototypes

Each variant was built with `mise run site` (`bun run build` for the variants) and served locally. The comparison covered three pages in the browser pane, in its dark theme at 1024 px.

### Prototype A: KaTeX override

Both 0.19.1 and 0.18.11 were built with the override above.

- **Markup is unchanged.** On all 21 pages that contain math, the HTML is byte-identical to today's, apart from the `katex-` class prefix and asset hashes. The check script normalises both and compares whole files.
- **Screenshots show no visible difference.**
- **A bad formula still fails the build.** Both `$\frac{1}{$` and an unknown `$\foo{1}$` exit with code 1.
- **`bun.lock` holds one `katex`.**
- **`micromark-extension-math` is not affected.** Its KaTeX import is only in `lib/html.js`, its micromark HTML extension, which `remark-math` never imports. `remark-math` uses only the `math` syntax extension.
- **Mermaid's client bundle** loads KaTeX only for `$$` inside diagram labels, which no mermaid block under `research/` contains.

### Prototype B: Temml through a local plugin

A ~25-line rehype plugin replaced `rehypeKatex` and `failOnKatexError`. It finds `remark-math`'s `math-inline` and `math-display` code nodes and calls `temml.renderToString(tex, {displayMode, throwOnError: true})`. It emits the result as a raw node and rethrows with the file path. `customCss` became `temml/dist/Temml-Local.css` plus a small `math.css`.

What it took to look right:

- **A math font, declared by hand.** `@fontsource/stix-two-math`'s own CSS gives the font a Latin-only `unicode-range`. Operators such as ∑, ≤ and ≈ would then fall back to another font. The woff2 file holds the full font (4605 code points and a `MATH` table), so `math.css` declares its own `@font-face` with no range.
- **A margin reset.** Starlight's `.sl-markdown-content :not(…) + :not(…) { margin-top: 1rem }` lands on MathML sibling elements (`<mo>` measured 16 px). Without a reset, every sub- and superscript separates from its base. The prototype's `.sl-markdown-content.sl-markdown-content math * { margin-top: 0 }` fixes it.

What remained after that:

- **Formulas render smaller than KaTeX's**, which sets `.katex` at 1.21 em.
- **Subscripts on bold letters sit low** ($\mathbf{q}_t$, $\mathbf{v}_\text{raw}$). The likely cause is Chromium's MathML layout dropping a subscript below the descender of its base glyph, where TeX would not.

It does pass the build-failure check, and `coordinates-and-units` shrinks from 307 KB to 146 KB of HTML.

<details><summary>The prototype plugin (in <code>site/astro.config.mjs</code>, used as <code>rehypePlugins: [rehypeTemml]</code>)</summary>

```js
import temml from "temml";

// remark-math leaves math as <code class="math-inline"> and <pre><code class="math-display">;
// render each to MathML with Temml at build time, throwing on a bad formula so the build fails.
function text(node) {
  return node.type === "text" ? node.value : (node.children ?? []).map(text).join("");
}
function rehypeTemml() {
  return (tree, file) => {
    const walk = (parent) => {
      parent.children?.forEach((node, i) => {
        if (node.type !== "element") return;
        const code = node.tagName === "pre" ? node.children.find((c) => c.tagName === "code") : node;
        const cls = code?.properties?.className ?? [];
        const display = cls.includes("math-display");
        if (!display && !cls.includes("math-inline")) return walk(node);
        const tex = text(code);
        try {
          const value = temml.renderToString(tex, { displayMode: display, throwOnError: true });
          parent.children[i] = { type: "raw", value };
        } catch (err) {
          throw new Error(`${file.path}: ${err.message}`);
        }
      });
    };
    walk(tree);
  };
}
```

</details>

### Prototype C: MathJax 4 through a local plugin

`rehype-mathjax` is from the dormant repo and still on the deprecated `mathjax-full` 3, so the prototype calls MathJax 4 directly. It is a ~60-line local plugin in place of `rehypeKatex` and `failOnKatexError`. It walks the same `math-inline` and `math-display` nodes as Prototype B. It converts each node through one shared MathJax document (`liteAdaptor`, TeX input, the assistive-MathML handler), awaiting `handleRetriesFor` so that the font's glyph ranges load on demand. It emits the container as a raw node. The only new dependency is `@mathjax/src` 4.1.3, pinned exactly; it brings `@mathjax/mathjax-newcm-font` 4.1.3 with it.

Two outputs were built:

- **SVG** draws each glyph as a path, so it needs no font files. It has three font-cache modes. `local`, the default, repeats each formula's glyph paths inside that formula. `global` refers to one shared `<defs>`, which MathJax expects to put once in a live page. The plugin builds one `<defs>` per page instead: it clears the cache before the page and appends the hidden cache `<svg>` after it. `global` is the variant shown below. `local` makes `coordinates-and-units` 822 KB, 2.7× KaTeX.
- **CHTML** uses web fonts like KaTeX does. With `adaptiveCSS`, the stylesheet holds only the glyphs and node kinds used, so the plugin resets the output per page and appends that page's `<style>`. The 30 woff2 files (1.8 MB) are served from `public/`, and a page fetches only those it uses.

What it took to look right:

- **`not-content` on each `mjx-container`.** Starlight's `.sl-markdown-content :is(img, …, svg, iframe) { display: block }` puts every inline SVG formula on a line of its own. Its sibling `margin-top: 1rem` lands inside CHTML's `mjx-*` elements, as it did inside Temml's MathML. Both rules exclude `.not-content` descendants, so one class fixes both, with no CSS of our own.
- **The `textmacros` TeX package.** Without it, `\text{tick\_duration}` renders the backslash; KaTeX accepts `\_` in `\text`. With `base`, `ams` and `newcommand` as well, every formula on the site parses.

Results:

- **Bold subscripts sit where KaTeX puts them** ($\mathbf{q}_t$, $\mathbf{q}_{t+1}$) in both outputs. MathJax positions them itself, where Temml leaves that to Chromium's MathML layout.
- **Formulas render smaller than KaTeX's.** KaTeX scales to 1.21 em; MathJax's SVG uses 1 em and CHTML matches the surrounding x-height. SVG's New Computer Modern strokes are thin and look grey on the dark theme at 1× DPR. CHTML's are closer in weight to KaTeX's.
- **A bad formula fails the build.** `formatError` rethrows instead of drawing an `merror`, and the plugin adds the path and the TeX source. `$\frac{1}{$` fails with `Missing close brace`, and `$\foo{1}$` with `Undefined control sequence \foo`; both exit with code 1.
- **Build time is no slower in single runs.** Astro reports 72 pages in 6.1–6.6 s, against 7.0 s for KaTeX. `mise run site` takes 9 s.

HTML per page, raw and gzipped:

| Page | KaTeX | MathJax SVG (`global`) | MathJax CHTML |
|---|---|---|---|
| `coordinates-and-units` | 307 KB / 31 KB | 493 KB / 67 KB | 370 KB / 40 KB |
| `all` | 111 KB / 18 KB | 149 KB / 27 KB | 137 KB / 22 KB |
| `timeline-and-ticks` | 150 KB / 21 KB | 222 KB / 38 KB | 187 KB / 26 KB |

Of `coordinates-and-units`, the hidden MathML is 45 KB under KaTeX and 59 KB under MathJax. The SVG page's `<defs>` is 55 KB, and the CHTML page's `<style>` is 25 KB. The site stylesheet loses KaTeX's 25 KB and gains MathJax's 6.5 KB (SVG) or nothing (CHTML).

Install: `node_modules` grows from 373 MB to 471 MB. `@mathjax/mathjax-newcm-font` is 49 MB, `@mathjax/src` 37 MB and `speech-rule-engine` 7.6 MB. `speech-rule-engine` and `mj-context-menu` are hard dependencies even though a build-time renderer uses neither, and they bring `rimraf` and `glob` with them.

<details><summary>The prototype plugin (in <code>site/astro.config.mjs</code>, used as <code>rehypePlugins: [rehypeMathjax]</code> with <code>customCss: ["./src/mathjax.css"]</code>)</summary>

```js
import { writeFileSync } from "node:fs";
import { mathjax } from "@mathjax/src/js/mathjax.js";
import { TeX } from "@mathjax/src/js/input/tex.js";
import { SVG } from "@mathjax/src/js/output/svg.js";
import { CHTML } from "@mathjax/src/js/output/chtml.js";
import { liteAdaptor } from "@mathjax/src/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "@mathjax/src/js/handlers/html.js";
import { AssistiveMmlHandler } from "@mathjax/src/js/a11y/assistive-mml.js";
import "@mathjax/src/js/util/asyncLoad/esm.js";
import "@mathjax/src/js/input/tex/base/BaseConfiguration.js";
import "@mathjax/src/js/input/tex/ams/AmsConfiguration.js";
import "@mathjax/src/js/input/tex/newcommand/NewcommandConfiguration.js";
import "@mathjax/src/js/input/tex/textmacros/TextMacrosConfiguration.js";
import { MathJaxNewcmFont as SvgFont } from "@mathjax/mathjax-newcm-font/js/svg.js";
import { MathJaxNewcmFont as ChtmlFont } from "@mathjax/mathjax-newcm-font/js/chtml.js";

// remark-math leaves math as <code class="math-inline"> and <pre><code class="math-display">;
// render each with MathJax 4 at build time (SVG, or CHTML when MJ_OUT=chtml), throwing on a
// bad formula so the build fails. One MathJax document serves every page.
// CHTML also needs node_modules/@mathjax/mathjax-newcm-font/chtml/woff2 copied to public/mathjax-woff2.
const CHTML_OUT = process.env.MJ_OUT === "chtml";
const adaptor = liteAdaptor();
AssistiveMmlHandler(RegisterHTMLHandler(adaptor));
const tex = new TeX({
  packages: ["base", "ams", "newcommand", "textmacros"], // textmacros: \_ inside \text{}
  formatError: (_jax, err) => {
    throw err;
  },
});
const output = CHTML_OUT
  ? new CHTML({ fontData: ChtmlFont, fontURL: "/stunt-reel/mathjax-woff2" })
  : new SVG({ fontData: SvgFont, fontCache: process.env.MJ_CACHE ?? "global" });
const doc = mathjax.document("", { InputJax: tex, OutputJax: output });

function text(node) {
  return node.type === "text" ? node.value : (node.children ?? []).map(text).join("");
}
function rehypeMathjax() {
  return async (tree, file) => {
    const jobs = [];
    const walk = (parent) => {
      parent.children?.forEach((node, i) => {
        if (node.type !== "element") return;
        const code = node.tagName === "pre" ? node.children.find((c) => c.tagName === "code") : node;
        const cls = code?.properties?.className ?? [];
        const display = cls.includes("math-display");
        if (!display && !cls.includes("math-inline")) return walk(node);
        jobs.push([parent, i, text(code), display]);
      });
    };
    walk(tree);
    // With fontCache "global", each page gets its own hidden <defs> of the glyphs it used.
    const global = !CHTML_OUT && output.options.fontCache === "global";
    if (global && jobs.length) output.fontCache.clearCache();
    if (CHTML_OUT && jobs.length) output.reset();
    for (const [parent, i, src, display] of jobs) {
      try {
        const node = await mathjax.handleRetriesFor(() => doc.convert(src, { display }));
        // Opt out of Starlight's content CSS (block-level svg, 1rem sibling margins).
        adaptor.addClass(node, "not-content");
        parent.children[i] = { type: "raw", value: adaptor.outerHTML(node) };
      } catch (err) {
        throw new Error(`${file.path}: ${src}: ${err.message}`);
      }
    }
    if (global && jobs.length) {
      const defs = adaptor.outerHTML(output.pageElements(doc) ?? output.fontCache.getCache());
      tree.children.push({ type: "raw", value: defs });
    }
    // CHTML: a per-page <style> holding only the glyph and node rules this page used.
    if (CHTML_OUT && jobs.length) {
      tree.children.push({ type: "raw", value: `<style>${mathCss()}</style>` });
    }
  };
}
// The output jax's stylesheet (mjx-container layout and, for CHTML, the glyph classes it used).
const mathCss = () => adaptor.textContent(output.styleSheet(doc));
writeFileSync("src/mathjax.css", CHTML_OUT ? "" : mathCss());
```

</details>

### Screenshots

Each image shows, left to right, KaTeX 0.16.47 (today), KaTeX 0.19.1 (override) and Temml 0.14.0.

`research/formats/concepts/coordinates-and-units/`:

![coordinates-and-units under the three renderers](images/math-coordinates-and-units.png)

`research/formats/all/`:

![all under the three renderers](images/math-all.png)

`research/formats/concepts/timeline-and-ticks/` (note the low subscripts on bold **q** under Temml):

![timeline-and-ticks under the three renderers](images/math-timeline-and-ticks.png)

The MathJax images show, left to right, KaTeX 0.16.47 (today; the 0.18.11 override renders identically), MathJax 4.1.3 SVG with the per-page `global` cache, and MathJax 4.1.3 CHTML. They were captured with headless Chrome at 600 px, dark theme, 1× DPR, so their scale differs from the images above.

`research/formats/concepts/coordinates-and-units/`:

![coordinates-and-units under KaTeX and MathJax 4](images/math-mathjax-coordinates-and-units.png)

`research/formats/all/`:

![all under KaTeX and MathJax 4](images/math-mathjax-all.png)

`research/formats/concepts/timeline-and-ticks/` (the bold **q** subscripts in the slerp formula sit at the same height under all three):

![timeline-and-ticks under KaTeX and MathJax 4](images/math-mathjax-timeline-and-ticks.png)

## Not checked

- Firefox and Safari. Temml's look depends on each engine's MathML layout. Only Chromium (the browser pane) was viewed.
- Light theme and phone width.
- Whether GitHub's own MathJax rendering of these notes matches Prototype C's; GitHub's MathJax version and configuration were not checked.
- MathJax's SVG output at 2× DPR, where its thin strokes may matter less.
- Whether Renovate opens one PR or two for a package named in both `dependencies` and `overrides`. The "research site" group should put them in the same PR.
