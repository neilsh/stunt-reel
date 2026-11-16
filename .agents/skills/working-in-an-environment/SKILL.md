---
name: working-in-an-environment
description: "Use at the start of a cloud session (`CLAUDE_CODE_REMOTE=true`), when a `gh` command fails on GraphQL, or before work that needs a GPU, DOSBox, Orca or a data-root file, to tell whether this environment has it."
---

# Working in an environment

Stunt-reel runs in two environments. Each has a file stating what it has, what it lacks, and what to do instead:

| Environment | How to tell | File |
|---|---|---|
| `cloud` | `CLAUDE_CODE_REMOTE=true` | [`cloud.md`](cloud.md) |
| `local-windows` | otherwise, on Windows | [`local-windows.md`](local-windows.md) |

Any other machine has no file yet: say so, and work from `local-windows.md` only where the resource it names is there.

The SessionStart hook prints `environment: <name>` at startup, resume, clear and compaction, and in a cloud session adds the file to read. A subagent sees neither the hook nor this skill, so a brief for a subagent in a cloud session tells it to read `cloud.md` first.
