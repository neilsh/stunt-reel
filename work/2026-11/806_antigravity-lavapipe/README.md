---
title: "cloud-antigravity: the canonical Ubuntu lavapipe cannot load on Debian 12"
started: 2026-11-23
issue: 806
outcome: ""
---

# cloud-antigravity: the canonical Ubuntu lavapipe cannot load on Debian 12

#806 would replace the bookworm-backports lavapipe that `.claude/cloud-setup.sh --antigravity` unpacks with the canonical Ubuntu 24.04 package that CI and the Claude cloud install.
That package cannot run on the current Antigravity image, a Debian 12 VM: its driver and its LLVM 20.1.2 library import `GLIBC_2.38` symbols, and Debian 12's glibc is 2.36 ([journal](journal.md#2026-11-23-the-canonical-ubuntu-lavapipe-cannot-load-on-debian-12)).

## Handoff

The setup script is unchanged: installing the Ubuntu `.deb`s on this image would leave the renderer without a Vulkan adapter, rather than make it comparable.
What remains is the owner's choice between:

- an Antigravity base image with glibc 2.38 or newer (Ubuntu 24.04 or later), where the canonical package can be installed or unpacked; and
- a lavapipe built on bookworm against LLVM 20.1.2, hosted as a pinned artifact and fetched by `.claude/cloud-setup.sh` (the [#877](https://github.com/neilsh/stunt-reel/issues/877) plan, which used LLVM 21.1.7).

Either route can only be verified on an Antigravity VM: `mise run parity` must report `llvmpipe (LLVM 20.1.2, 256 bits)` and compare on all seven films, and `mise run parity-residue -- --against-hashes` must show the canonical build's planes.
Until then, a check that needs `expected.lavapipe` stays on the Claude cloud or local-windows (WSL), as [`cloud-antigravity.md` § Rendering](../../../.agents/skills/working-in-an-environment/cloud-antigravity.md#rendering) says.
