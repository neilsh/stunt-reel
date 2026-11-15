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
