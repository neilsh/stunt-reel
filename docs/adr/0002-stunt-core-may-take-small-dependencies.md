# `stunt-core` may take small, pure-Rust dependencies

## Status

accepted

## Context

`[I7]` required a "zero-dependency" `stunt-core`. In practice the crate already allows optional `serde` and `bytemuck`, so the rule was stricter in wording than in practice. Hand-written code that established crates would cover cleanly has accumulated: 18 hand-written `Display`/`Error` impls and about 90 duplicated byte-cursor read sites across the VFS, FLM and SOD parsers, each rebuilding the same `UnexpectedEof { expected, actual }` error.

A spike that rewrote `parse_res` and `parse_all` with `binrw` and `winnow` passed every existing test but saved few lines. `binrw` added nine `syn`-based crates and a mapping layer for `VfsError`. FLM and SOD are a stateful stream interpreter and a bytecode VM, which a declarative parser framework does not fit.

## Decision

`stunt-core` may depend on small, pure-Rust crates that do no I/O and touch no windowing, GPU, audio or emulator code. Each addition is justified in the PR that adds it. The cleanroom half of `[I7]` (no proprietary assets in Git, offline tests) is unchanged.

First uses:

- `thiserror` for all error enums.
- One shared `ByteReader` in `stunt-core` with a common `Eof { expected, actual }` error and `From<Eof>` impls on `VfsError`, `FlmError` and `SodError`. The parsers stay hand-written.

## Considered Options

- **Keep core strictly dependency-free.** Rejected: it forces boilerplate that `thiserror` removes at no runtime cost.
- **Adopt a parser framework (`binrw`, `winnow`, `nom`).** Rejected: little benefit against the lenient, stateful parse policies, and `binrw` costs nine crates and a mapping layer.
- **Replace the hand-written quaternion math with `glam` in core.** Rejected: slerp has project-specific shortest-path and antipodal handling that parity depends on.

## Consequences

The `[I7]` heading in `docs/SPEC.md`, its entry in `python/stunt_reel/doc_anchors.py`, `contracts/mod.rs` and `AGENTS.md` still say "zero-dependency" and must be reworded together, because `tests/test_doc_invariants.py` checks the heading against the registry. `cargo deny` licence policy applies to every new crate.
