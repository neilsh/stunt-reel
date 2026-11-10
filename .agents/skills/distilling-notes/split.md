# Splitting a distilled note

Part of the [`distilling-notes`](SKILL.md) skill, its step 7. A note that is over 20 KB and already has a `work/*/distill-<stem>*` folder was distilled before; what keeps it over budget is reference, not narrative, so it is split by subject instead of distilled again.

1. **One PR, one note.** Branch `claude/split-<stem>`; title `docs(split): <path>`. No work folder: the split moves text, it records nothing new.
2. **Move whole sections, unchanged,** into sibling notes in the note's directory, one subject each, each with its own `summary:` and under 20 KB. The original keeps the subject its title names, plus one line naming where each moved subject went.
3. **Rewrite every citation of a moved section** in the same PR: links and section numbers in notes, ADRs, `docs/ARCHITECTURE.md` and code comments. `rg -n --no-ignore-dot '<file name>'` finds them. Text a test reads by path moves only with the code (SKILL.md).
4. **Land it.** `mise run fix` lists the new notes in `research/MAP.md`; `mise run check` must pass. Done when no note of the split is over 20 KB and no citation still names a moved section in the original.
