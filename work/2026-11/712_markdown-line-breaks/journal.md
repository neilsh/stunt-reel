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
