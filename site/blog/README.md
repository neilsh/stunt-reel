# The blog

Each Markdown file here, except this README, is a post on the research site's blog, served at `/stunt-reel/blog/`.
[`starlight-blog`](https://github.com/HiDeoo/starlight-blog) builds the post list, tag pages and RSS feed.

## Writing a post

Name the file for its URL, for example `why-stunt-reel-exists.md`, and start it with front matter:

```yaml
---
title: "Why Stunt Reel exists"
date: 2026-11-23
authors: neil
tags: [introduction, agents]
excerpt: "One sentence for the post list."
---
```

`title` and `date` (written YYYY-MM-DD) are required; `mise run site-prep` refuses a post without them.
The authors are defined in `site/astro.config.mjs`.
Add `draft: true` to keep a post out of the deployed site while still seeing it under `mise run site-serve`.

Link to repository files by their relative path, as the guides do: `mise run site-prep` turns a link to a published file into a site link and any other into a GitHub link.
The front matter is copied as written, so it may use YAML lists.

## Planned posts

- **Architecture tour**: the crates and the Python package, the four seams, and how a film becomes a frame.
- **How I build with agents**: a day of work from issue to merge, the harnesses, and the rules that keep them honest.
- **An agent failure post-mortem**: one thing an agent got confidently wrong, how it was caught, and the rule that came out of it.
- **By hand vs with agents**: which work still goes better by hand, and why.
- **Decision log**: a tour of the decision records and the ones that changed the project most.
