---
title: "Props never take their BZLT distance branch, and four SOD gates are ignored"
started: 2026-11-12
issue: 235
outcome: "Implemented from the handlers, with no render change: BZLT (a new per-frame BeyondDepth gate), BVIS, REJVEC and REJ2D, the section end counted from the size word, and an outer gate restored after a nested section. No census walk reaches the four gates, and no drawing opcode starts at a corrected section end. All seven reference films score as before. INTRO's round-bush conifers went with #399; the sparser conifer field is #426."
---

# Props never take their BZLT distance branch, and four SOD gates are ignored

## Handoff

Done, in the [journal](journal.md) and [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 8.6. `vm.rs` decodes `BZLT` into `VisibilityCondition::BeyondDepth`, which `stunt-render` tests per frame through `CameraTransform::view_depth_exceeds`. It decodes `BVIS`, `REJVEC` and `REJ2D` into facing gates. Sections now end `size` bytes from the size word, and an outer gate is restored after a nested section ends. The census reaches none of the four gates and nests no section, so no score moves. After merging #420 the seven films score exactly its pinned values, and `references.toml` only repins the `crates` tree. Left open (`sod-vm.md` section 10): a polygon in a nested section takes only the inner gate; a flag a shape never set is drawn; `REJ2D` with a point behind the eye; no live trace of `BZLT`. The INTRO conifer density is [#426](https://github.com/neilsh/stunt-reel/issues/426).
