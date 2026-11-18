# Journal: Markdown line breaks

## 2026-11-18: Blame across a sentence reflow with an ignored revision

- **Question**: if a commit that only splits paragraphs into one sentence per line is listed in `.git-blame-ignore-revs`, does `git blame` keep each line's earlier author?
- **Method**: git 2.43.0, in a scratch repository.
  File A held one paragraph on one line, three sentences written by Alice, then one number in the second sentence changed by Bob.
  File B held a paragraph hard-wrapped over three lines, all by Alice, then a word on the second line changed by Bob.
  A third commit split both into one sentence per line; that commit was listed in an ignore file, and `git blame --ignore-revs-file` ran with `blame.markIgnoredLines=true`.
- **Result**: in A, all three sentence lines were blamed on Bob, marked `?`.
  In B, the first sentence (wholly on Alice's first line) was blamed on Alice.
  The second sentence, which straddled Alice's first line and Bob's second, was blamed on Bob.
  The third sentence, which begins with Bob's changed word, was blamed on Alice: a wrong match.
- **Verdict**: adopted, with the limit stated.
  For a paragraph kept on one line, the ignored reflow loses nothing: blame never knew which sentence each commit wrote.
  For a hard-wrapped paragraph, git's fuzzy line matching guesses, and can guess wrong; `?` marks every guessed line.
  `git log -L` and `git log -S` do not read the ignore file.
- **Lives in**: the ADR this work adds.

## 2026-11-18: Open docs branches before the reflow

- **Question**: which branches hold evergreen Markdown changes not yet on `main`, which a reflow would conflict with?
- **Method**: on `origin/main` at `d4e01df`, for each of the 41 remote branches git did not count as merged, `git merge-tree --write-tree origin/main <branch>`; a branch whose merged tree equals `main`'s holds nothing new.
  Each remaining branch's pull request was looked up.
- **Result**: no pull request was open.
  34 branches were hundreds of commits off `main`'s history and conflicted with it: leftovers of squash-merged or closed pull requests.
  Six recent ones were finished: merged, superseded (#665 by #671, #694 by #692) or throwaway CI probes (#668 to #670).
  `neilsh/644-frustum-cull` only appeared to add a paragraph to `research/parity/lavapipe.md`; `main` already holds it, moved by the note's distillation (#677).
  One branch was live: `ccr-7c0ce54a-oy8ptz`, pushed that day with four commits after #706 and no pull request, adding a render-memory task, `docs/howto/measure-a-renders-memory.md`, and one line each to `docs/development.md` and `.agents/skills/working-in-an-environment/cloud.md` (`18f4abb`), both in the reflow's scope.
- **Verdict**: control.
  The reflow waits for that branch or for the owner's go-ahead (spec decision 6), and the survey is rerun just before it.
- **Lives in**: this journal only; it is a snapshot.

## 2026-11-18: Reflow dry run

- **Question**: does the reflow of every scope path keep each file's rendered HTML, links and code spans, and does the full gate pass on the result?
- **Method**: on a throwaway branch at `e51d232` (the guidance, ADR 0051 and the tier fix committed), `reflow.py write` on the 129 paths `scope` printed, then `reflow.py verify --base HEAD` on them, then `mise run check -- --full`.
  The branch was deleted afterwards.
- **Result**: 129 files changed, 6,477 lines added and 2,823 removed; the scope's lines went from 12,040 to 15,694.
  `AGENTS.md` went from 8,064 to 8,103 bytes, under its 8,192-byte cap.
  No file went over its doc-health budget that was not over already: `docs/development.md` (over by this work's guidance section) grew from 20,502 to 20,504 bytes and `docs/SPEC.md` from 20,495 to 20,578.
  Two failures:
  - `verify` failed `.agents/skills/running-unattended/pr-and-filing.md` on links, 13 before and 14 after.
    On the joined line, a ``` `` ` `` ``` span made the line-based code-span regex pair the wrong backticks and blank the `docs/harness.md` link; on its own line the sentence pairs them right, and the link checker sees the link.
    The HTML was identical.
    Fixed by failing `verify` only on a lost link or code span (`e51d232`).
  - In the full gate, `tests/test_prek_hooks.py::test_check_mode_leaves_the_file_alone` timed out waiting for prek while the Rust tests ran beside it.
    It runs in a temporary repository and reads none of the reflowed files; it passed alone, and `mise run test-py` on the reflowed tree then passed all 2,596 tests.
    Every Rust step passed.
- **Verdict**: adopted, with the fixes in the next entry: `verify` passed and the gate's readers held, but `verify` renders CommonMark and cannot see GitHub's alerts.
- **Lives in**: this journal; the ADR's Consequences name the tier fix.

## 2026-11-18: Fresh review of PR 1, and the dry run again

- **Question**: what does a fresh reviewer find in PR 1's branch (`d4e01df..6879987`), and does the reflow still verify once its findings are fixed?
- **Method**: a fresh reviewer read the diff and the code it cites, reran the dry run in a separate worktree, tried about 50 adversarial `reflow_text` inputs, and recomputed the quoted figures.
  After the fixes, the dry run was repeated at `50f3b74` as in the previous entry, followed by `mise run test-py`.
- **Result**: the reviewer's figures matched every quoted one it could recompute; the 158/103/12 wrap counts were not recomputed, their method being unrecorded.
  It found the reflow joining a GitHub alert's marker (`> [!WARNING]`) onto the next line in five files, `README.md`'s banner among them; GitHub renders an alert only while its marker stands alone, and CommonMark, which `verify` renders, shows no difference.
  It also found the join undoing a break an author had put before a sentence starting with a digit or a lower-case letter, as in this PR's ADR and journal.
  Both are fixed in `1027e31`, with a selftest case each; the ADR, `docs/development.md` and the spec were narrowed to what the checks show (`50f3b74`).
  The repeated dry run: 129 files, 6,477 lines added and 2,818 removed, `verify` passing (`pr-and-filing.md` still finds 14 links where the joined old text found 13), the five alert markers on their own lines, `AGENTS.md` at 8,103 bytes, and 2,596 Python tests passing.
- **Verdict**: adopted: PR 2 runs the script at `1027e31` or later.
  One split the reviewer flagged, inside a parenthetical in `research/formats/auxiliary/spr.md`, is left to PR 2's spot-check.
- **Lives in**: this journal; ADR 0051 states the alert rule.

## 2026-11-18: Blame across the merged reflow

- **Question**: with the reflow's squash commit (`edd2621`, #714) in `.git-blame-ignore-revs`, does `git blame` still credit the reflowed lines to the commits before it?
- **Method**: git 2.43.0 in this session's 52-commit shallow clone, `git blame -s --ignore-revs-file .git-blame-ignore-revs` with `blame.markIgnoredLines` and `blame.markUnblamableLines`, on `AGENTS.md` (one-line paragraphs before the reflow), `docs/harness.md` (hard-wrapped) and `research/parity/attribution.md` (one-line, with hand-moved breaks), compared with plain `git blame`.
- **Result**: without the ignore file, the reflow owned 22 of `AGENTS.md`'s 92 lines, 143 of `docs/harness.md`'s 260 and 139 of `attribution.md`'s 256.
  With it, the reflow owned none of `AGENTS.md`'s lines; 22 were passed to earlier commits and marked `?`.
  In `docs/harness.md` 141 were passed on and marked `?`, and 2 blank lines stayed on the reflow, marked `*` as unblamable; in `attribution.md` 138 were passed on and 1 blank line stayed.
  The clone's history starts at `2c60728` (2026-11-16), so most passed-on lines landed on that boundary commit; which earlier author each guessed line reaches was not checked, and the first entry's experiment says a hard-wrapped paragraph's guess can be wrong.
- **Verdict**: adopted: the ignore entry does what ADR 0051 says, apart from the guessing it already states.
- **Lives in**: ADR 0051's Consequences.

## 2026-11-18: The reflow's hand fixes

- **Question**: which line breaks did people move by hand after the script ran, and why, so the script's limits are on record?
- **Method**: two fresh reviewers read the reflowed diff of #714, the first 27 paragraphs, the second about 60 more in files the first had not read, each with mechanical scans of every added line; each bad split was fixed by moving a line break only, and `reflow.py verify` and the word diff were rerun after each round.
- **Result**: 60 breaks were moved; line numbers are at the commit each fixed.
  - At `58fe08a` (first review): a split inside a parenthetical (`research/formats/auxiliary/spr.md:77`), a split inside a quotation (`research/formats/res.md:170`), and 18 issue or picture links `([#N](…))` left alone on a line, in `terrain-shade.md`, `driving.md`, `attribution.md` (6), `col3-2-studio.md`, `film-segments.md`, `framing-and-actors.md` (3), `hero-aircraft-placement.md` (2) and `patch3.md` (3).
  - In `26c295f` (second review): 33 evidence-tier tags left on the line after their claim, joined back because [`distilling-notes`](../../../.agents/skills/distilling-notes/SKILL.md) keeps each tag on the claim it qualifies; 3 more lone citations; 3 issue citations that had landed at the start of the next sentence; and one split inside a score range written `0.6549 .. 0.7154`.
  - The first reviewer had judged the lone tier tags acceptable; the second, citing the skill, did not.
- **Verdict**: control: the script splits after any sentence end, so it cannot tell a trailing citation, tier tag or `..` range from a sentence.
  Authors placing breaks by hand under the guidance avoid all four.
- **Lives in**: this journal only.
