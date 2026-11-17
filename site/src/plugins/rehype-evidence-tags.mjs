// Renders an evidence tag written as inline code (`[Established]`) as a labelled badge whose
// hover text is the tier's meaning from docs/SPEC.md. The tiers come from the generated
// tiers.json (python/stunt_reel/site_pages.py reads them from SPEC section 2.4), so this file
// names no tier. Outside a heading or a link the badge links to `href`, the page that explains
// the tiers.

const HEADING = new Set(["h1", "h2", "h3", "h4", "h5", "h6"]);

function text(node) {
  if (node.type === "text") return node.value;
  return (node.children ?? []).map(text).join("");
}

function slug(name) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

export default function rehypeEvidenceTags({ tiers = [], href }) {
  const meanings = new Map(tiers.map((t) => [`[${t.name}]`, t.meaning]));

  function badge(tag, plain) {
    const name = tag.slice(1, -1);
    const properties = {
      className: ["sr-tier", `sr-tier-${slug(name)}`],
      title: `${name}: ${meanings.get(tag)}`,
    };
    return {
      type: "element",
      tagName: plain ? "span" : "a",
      properties: plain ? properties : { ...properties, href },
      children: [{ type: "text", value: name }],
    };
  }

  function walk(node, inPlain, inPre) {
    const children = node.children;
    if (!children) return;
    const element = node.type === "element";
    // A badge in a heading or a link stays a span: a link may not hold a link.
    const plain = inPlain || (element && (HEADING.has(node.tagName) || node.tagName === "a"));
    const pre = inPre || (element && node.tagName === "pre");
    for (let i = 0; i < children.length; i++) {
      const child = children[i];
      if (!pre && child.type === "element" && child.tagName === "code") {
        const tag = text(child);
        if (meanings.has(tag)) {
          children[i] = badge(tag, plain);
          continue;
        }
      }
      walk(child, plain, pre);
    }
  }

  return (tree) => {
    if (meanings.size > 0) walk(tree, false, false);
  };
}
