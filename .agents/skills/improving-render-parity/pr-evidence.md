# Evidence for a rendering PR

Part of the [`improving-render-parity`](SKILL.md) skill.

A PR that changes rendered output — anything that moves a pixel `stuntreel` draws, from `crates/stunt-render/`, the SOD VM, the world builder, the palette or the timeline — shows it: one picture per film it moves, the capture beside the render before and after, in the PR body's **Evidence** section with that film's `mise run parity` line before and after.

```
- [ ] 1. Pick the ticks where the change shows most (the frames the parity score moved, or the ones the PR is about); CTRY and INTRO at least, plus any batch film the PR targets
- [ ] 2. Add --crop x0,y0,x1,y1 --scale 3 to every frame run below when the whole frame hides the change
- [ ] 3. Render before and after, and copy the PNGs from build/scratch/frame/<film>/ (the next run replaces them):
       behind a DBG_* switch, one picture holds both: mise run frame -- --film <film> --ticks <t,t> --var DBG_X=0,1, copied to build/scratch/pr/; render every film's pictures this way while the switch still exists, and remove it only after step 4
       otherwise two pictures: mise run frame on the base commit (git switch --detach <base>) copied to build/scratch/pr/before/, then on the PR head copied to build/scratch/pr/after/
- [ ] 4. Score before and after on the same films: behind a DBG_* switch, mise run sweep -- --var DBG_X=0,1 prints both in one table; otherwise mise run parity on the base commit and on the PR head, keeping each [parity] line
- [ ] 5. Write the body to build/scratch/pr/body.md: under ## Evidence, each film's two scores from step 4, then its pictures, referenced by path relative to that file:
       DBG: ![INTRO tick 48: capture, before, after](./intro_48.png)
       otherwise: ![INTRO tick 48 before](./before/intro_48.png) ![INTRO tick 48 after](./after/intro_48.png)
- [ ] 6. gh pr create (or gh pr edit <n>) --body-file build/scratch/pr/body.md, then one --attach per picture the body references:
       DBG: --attach build/scratch/pr/intro_48.png
       otherwise: --attach build/scratch/pr/before/intro_48.png --attach build/scratch/pr/after/intro_48.png
- [ ] 7. A non-zero exit that still printed the PR URL means the PR exists but some uploads failed: re-run as gh pr edit <n> with the same --body-file and --attach flags until it exits 0 (no URL printed means nothing was created). Then confirm gh pr view <n> --json body --jq .body holds no ](./ reference
```

`gh` uploads each `--attach` file and rewrites the body's reference to its hosted URL, so nothing is committed; attached pictures follow the limits of [`NOTICE.md`](../../../NOTICE.md)'s comparison-image rule (single screens or crops of one, never a run of frames or a video). A change meant to leave every pixel alone shows that instead: the `mise run parity` lines before and after, identical. Where the session has no data root, the PR says so under **Evidence** and the reviewer renders the picture. **Evidence** names the commit each run used; when the PR head moves after a run, it says what changed since.
