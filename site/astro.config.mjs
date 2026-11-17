import { readFileSync } from "node:fs";
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import starlightLinksValidator from "starlight-links-validator";
import mermaid from "astro-mermaid";
import { unified } from "@astrojs/markdown-remark";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeEvidenceTags from "./src/plugins/rehype-evidence-tags.mjs";
import rehypeHeadingNumbers from "./src/plugins/rehype-heading-numbers.mjs";
import sidebar from "./src/generated/sidebar.json" with { type: "json" };
import tiers from "./src/generated/tiers.json" with { type: "json" };

const base = "/stunt-reel";

// The badges link to the heading of site/reading.md that explains the tiers. The links validator
// does not see a badge's link (the plugin adds it after the Markdown is parsed), so renaming the
// heading would break every badge silently; fail the build instead.
const tiersAnchor = "evidence-tags";
const readingHeadings = readFileSync(new URL("./reading.md", import.meta.url), "utf8")
  .split("\n")
  .filter((line) => /^#{1,6} /.test(line))
  .map((line) => line.replace(/^#+ /, "").toLowerCase().replace(/[^a-z0-9]+/g, "-"));
if (!readingHeadings.includes(tiersAnchor)) {
  throw new Error(`site/reading.md has no heading for #${tiersAnchor}, which the tier badges link to`);
}

// rehype-katex renders a bad formula as a red span and only records a message, so the build
// would pass with the page broken; throw instead.
function failOnKatexError() {
  return (_tree, file) => {
    const bad = file.messages.filter((m) => m.source === "rehype-katex");
    if (bad.length > 0) {
      throw new Error(`${file.path}: ${bad.map((m) => m.reason).join("; ")}`);
    }
  };
}

export default defineConfig({
  site: "https://neilsh.github.io",
  base,
  trailingSlash: "always",
  markdown: {
    processor: unified({
      remarkPlugins: [remarkMath],
      rehypePlugins: [
        rehypeKatex,
        failOnKatexError,
        // The page the badges link to explains the tiers (site/reading.md, "Evidence tags").
        [rehypeEvidenceTags, { tiers, href: `${base}/reading/#${tiersAnchor}` }],
        // Mutes a heading's leading spec number; Astro assigns the ids afterwards, from the text.
        rehypeHeadingNumbers,
      ],
    }),
  },
  integrations: [
    mermaid(), // before starlight, as astro-mermaid requires
    starlight({
      title: "Stunt Reel research",
      social: [{ icon: "github", label: "GitHub", href: "https://github.com/neilsh/stunt-reel" }],
      // The stylesheet of the one katex package.json's `overrides` forces on rehype-katex; drop
      // the override once remarkjs/remark-math#122 ships.
      customCss: [
        "katex/dist/katex.min.css",
        "./src/styles/home.css",
        "./src/styles/tiers.css",
        "./src/styles/headings.css",
      ],
      components: { PageTitle: "./src/components/PageTitle.astro" },
      sidebar,
      plugins: [starlightLinksValidator()],
    }),
  ],
});
