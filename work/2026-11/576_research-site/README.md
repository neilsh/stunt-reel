---
title: "Publish research/ as a GitHub Pages site"
started: 2026-11-15
issue: 576
outcome: "research/ and GLOSSARY.md publish as a Starlight site at neilsh.github.io/stunt-reel, built from main by .github/workflows/pages.yml with the content generated into gitignored folders, so there is no second copy to keep in sync; publishing docs/SPEC.md, a non-goal here, followed in #590"
---

# Publish research/ as a GitHub Pages site

## Question

How can modders and fans read the `research/` notes as a website, built from `main`, with no second copy to keep in sync?

## Links

- [Spec](spec.md) and [plan](plan.md).
- PR: [#578](https://github.com/neilsh/stunt-reel/pull/578).

## Owner step

Before the first merge, turn on Pages: Settings, Pages, Source "GitHub Actions". The deploy workflow cannot publish until then.
