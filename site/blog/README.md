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

When you revise a published post, add `lastUpdated: YYYY-MM-DD` with the day of the revision, and move it on each later revision.
The post then shows "Last update" after its publish date, and its search-engine metadata carries the new date as `dateModified`; the RSS feed keeps the publish date.
A post whose `lastUpdated` equals its `date` shows only the one.
Leave `date` as it was: it is the publish date, and the URL comes from the file name, not the date, so it never changes.
The authors are defined in `site/astro.config.mjs`.
Add `draft: true` to keep a post out of the deployed site while still seeing it under `mise run site-serve`.

Link to repository files by their relative path, as the guides do: `mise run site-prep` turns a link to a published file into a site link and any other into a GitHub link.
The front matter is copied as written, so it may use YAML lists.

A post may show images from a work folder, which `mise run site-prep` publishes beside it, and a short clip of our own render under the limits in [`NOTICE.md`](../../NOTICE.md#a-rendered-clip-on-the-blog).
Clips go in `site/public/blog/` and are embedded with a `<video>` tag whose `src` starts with `/stunt-reel/blog/`.
`ctry-flight.mp4`, in the first post, was rendered with:

```bash
mkdir -p build
stuntreel --headless "<data root>/corpus/stisldem/VAULT/CTRY.FLM" --all "<data root>/corpus/stisldem/VAULT/CTRY.ALL" \
    --sidata "<data root>/corpus/siarchive/Developer/FreeFlight/SIDATA" \
    --video build/ctry-flight.mkv --tick-range 200..=800 --width 960 --height 720
ffmpeg -i build/ctry-flight.mkv -c:v libx264 -crf 30 -preset slow -pix_fmt yuv420p \
    -movflags +faststart -an -map_metadata -1 site/public/blog/ctry-flight.mp4
```

## Planned posts

- **Architecture tour**: the crates and the Python package, the four seams, and how a film becomes a frame.
- **How I build with agents**: a day of work from issue to merge, the harnesses, and the rules that keep them honest.
- **An agent failure post-mortem**: one thing an agent got confidently wrong, how it was caught, and the rule that came out of it.
- **By hand vs with agents**: which work still goes better by hand, and why.
- **Decision log**: a tour of the decision records and the ones that changed the project most.
