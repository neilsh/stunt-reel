import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import starlightLinksValidator from "starlight-links-validator";
import mermaid from "astro-mermaid";
import { unified } from "@astrojs/markdown-remark";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import sidebar from "./src/generated/sidebar.json" with { type: "json" };

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
  base: "/stunt-reel",
  trailingSlash: "always",
  markdown: {
    processor: unified({
      remarkPlugins: [remarkMath],
      rehypePlugins: [rehypeKatex, failOnKatexError],
    }),
  },
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
