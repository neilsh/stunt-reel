// Wraps the spec-style number that opens a heading ("1.1" in "1.1 Origin: SD.EXE") in a span the
// stylesheet mutes (site/src/styles/headings.css, `.sr-secno`). The text stays: notes cite "§ 1.1",
// and Astro derives each heading's id and its contents-list entry from the heading's text nodes,
// which this leaves as they were, so every `#11-origin-sdexe` anchor still resolves.

const HEADING = new Set(["h1", "h2", "h3", "h4", "h5", "h6"]);
// "3", "3.2", "2.1.4" or "1." (a number or dotted number, then whitespace).
const NUMBER = /^(\d+(?:\.\d+)*\.?)(?=\s)/;

function walk(node) {
  for (const child of node.children ?? []) {
    if (child.type !== "element") continue;
    if (HEADING.has(child.tagName)) {
      const first = child.children?.[0];
      const match = first?.type === "text" ? NUMBER.exec(first.value) : null;
      if (match) {
        child.children.splice(
          0,
          1,
          {
            type: "element",
            tagName: "span",
            properties: { className: ["sr-secno"] },
            children: [{ type: "text", value: match[1] }],
          },
          { type: "text", value: first.value.slice(match[1].length) },
        );
      }
    } else {
      walk(child);
    }
  }
}

export default function rehypeHeadingNumbers() {
  return (tree) => walk(tree);
}
