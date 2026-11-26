# Journal: distilling `lavapipe-render-time.md`, second pass

Superseded results and restatements cut from [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) as of commit `46e5b20c`, and the pre-distillation `summary:` as it stood on `main` at `ef237840`, moved here verbatim.
Only relative link paths and list indentation changed; a section number in the moved text names a section of the note as it stood at `46e5b20c` (`git show 46e5b20c:research/parity/lavapipe-render-time.md`).

## 2026-11-16: LOCATION's peak memory on Windows before the world mesh was freed

On Windows (2026-11-16, [#645](https://github.com/neilsh/stunt-reel/issues/645)) LOCATION ticks 12-120 peaked at 982 MB working set and 1,078 MB private on mesa-dist-win 25.2.8, and 942 MB and 1,443 MB on the RTX 4070.

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), § 7, superseded by the figures after `release_world_mesh`.

## 2026-11-20: Memory at #706's pair on the RTX 4070

At #706's own pair on that GPU, `4c43baa` (its parent) against `2ecbad1` (its merge, `crates` `71486d7` and `a00c4e7`), three runs each, LOCATION ticks 12-120 peaked at about 598 MiB working set and 1,297-1,303 MiB private before the change and about 598 MiB and 1,289-1,291 MiB after it; CTRY's captured ticks 14-1333 at 161 MiB and 343 MiB before and 160 MiB and 341 MiB after.
Equal peaks at both commits put the peak before `release_world_mesh` runs: the peak working set does not move (about 598 MiB), while peak private falls about 10 MiB, from 1,297-1,303 to 1,289-1,291 MiB, about 0.7 GiB above the working set on both.
After the upload LOCATION's working set is about 483 MiB before the change and about 227 MiB after it, a drop of about 256 MiB, about the CPU mesh's 253 MiB.
The whole GPU's `nvidia-smi` used memory rose from idle to 520 MiB during LOCATION's render and 200 MiB during CTRY's, the same at both commits (200 ms sampling).
In that pair the render stores are byte-identical: all seven films' `frames.zst`, `layers.zst` and `palettes.zst` (21 files) and their scores match, and every report named the RTX 4070 Laptop GPU.
The 2026-11-16 pair (942 MB working set and 1,443 MB private) is not reproduced at `4c43baa`, where three runs read about 598 MiB and 1,297-1,303 MiB; the 603 MiB peak the flag read at `77a9a49` agrees with this pair's, and the gap to 942 MB is not attributed.

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), § 7, condensed.

## 2026-11-21: Splitting one film across processes or devices, as § 7 restated it

Splitting one film's ticks across processes, or across wgpu devices in one process, was set aside ([#645](https://github.com/neilsh/stunt-reel/issues/645)) on the assumption that one queue per device serializes in-process work and each process repeats the whole memory cost while parity already runs films in parallel (`--jobs`).
`#918` measured both on `LOCATION` ticks `50..=649` (`[Bounded Observation]`, 2026-11-21), and the first assumption does not hold: two in-process `VkDevice`s used `2.21` cores on Windows `mesa-dist-win 25.2.8` and `2.07` on Ubuntu 24.04 `mesa-vulkan-drivers 25.2.8`.
Four in-process devices still lose to four child processes: `6,727.8` ms sharing one instance and `5,451.2` ms with one each, against `4,344.1` ms, on Windows; `15,890.6` ms (slower than two devices) and `13,128.4` ms against `7,650.1` ms on Ubuntu.
Each extra lavapipe device adds `751..796 MiB` RSS, close to one process's `889..953 MiB`, so sharing one instance in-process saves `257.5..299.6 MiB` polled RSS across 4 workers, and chunked child processes are preferred over in-process device pooling when sharding one long film ([section 5](../../../research/parity/lavapipe-render-time.md#5-multi-vkdevice-in-process-versus-child-processes)).
Method: `stuntreel --headless … --report-memory` prints the resident set after each stage and the peak ([`measure-a-renders-memory.md`](../../../docs/howto/measure-a-renders-memory.md)).

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), § 5, which holds these figures; the method is in [`measure-a-renders-memory.md`](../../../docs/howto/measure-a-renders-memory.md).

## 2026-11-23: Batching decal slices by screen box, as Ruled out stated it (#1000)

* **Batching the world's decal slices by screen box to cut their pipeline switches (`#1000`):** `[Bounded Observation]`, 2026-11-22, `7bfc6cca` plus [`probe-decal-batch.patch`](../1000_decal-batch-probe/probe-decal-batch.patch), a CPU count, no timing, closed on the owner's 2026-11-23 ruling on scope with no renderer change.
Greedy batches with each slice's node box grown 1 pixel leave `54.2%` of the whole `LOCATION` film's decal pipeline switches in place (`228,160` of `421,326`, most of them), so the issue's rule, "if batching leaves most switches in place, close this issue", closes it at the gate's scope, the whole film; Span B (`3680..=3979`), where batching removes `54.2%` of the switches and leaves `45.8%` (`53,728` of `117,228`), is recorded as context with nothing filed for it.
The ceiling holds at either scope: `#920`'s grouping probe, with about every decal switch gone, cut the whole film's loop `7.7%` (2 rounds, section 3, not re-measured), and batching removes `45.8%` of the whole film's switches, so the saving is at most about `3.5%` of the loop if proportional to the switches removed (`7.7%` times `45.8%`), and about `3.7%` if each span's removed share is weighted by that span's own saving (`955 ms` on Span B, `1,122.5 ms` elsewhere; `996 ms` of `27,062.5 ms`), against the issue's `5%` gate; both are inferences from `#920`'s figures, not timings.
Pad 0, boxes not grown, leaves `43.6%` of the whole film's switches and `29.4%` of Span B's, bounds of `4.3%` and `4.6%`; it is outside the issue's design, whose boxes must be conservative, so it does not trigger the issue's one-point rule.
One known alternative, not probed: an order buffer that makes decal draw order commutative could reach most of the `7.7%` ceiling, but needs a second order target beside the world's depth; [`#999`](https://github.com/neilsh/stunt-reel/issues/999)'s design note is to cite this close, per the owner's ruling; [decal pipeline switches](../1000_decal-batch-probe/journal.md#2026-11-22-decal-pipeline-switches-greedy-batching-would-leave), [the owner's ruling on scope](../1000_decal-batch-probe/journal.md#2026-11-23-the-owners-ruling-on-scope).

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), Ruled out, condensed, and § 3.

## 2026-11-23: Open question 1 as it stood at 46e5b20c

1. What inside lavapipe makes the world decal slices' fill-to-outline alternation cost Span B's loop: grouping saves 955 ms of 2,377 ms, attributed to the switches by elimination, and the rest of the world's draws cost 779 ms more; whether a state or binning flush at the switch is the cost, what the 779 ms is, and why the whole film leans toward outlines and pixels (2 rounds) are open.
   `#1002`'s profile (section 3) answers part of this: on Span B storing the fragment state is the largest single part of the loop (`28.3%`, `740` of the world's `1,948.5 ms`), and the whole film's world cost is mostly line setup, vertex work and rasterization (`9,102` of `13,620 ms`), consistent with its lean toward outlines and pixels.
   It does not tie the state store to the switches, since the stores a frame were not counted, so whether a state store at the switch is the cost stays open, as does what the remaining `779 ms` is.
   Which of the levers above 5% of the whole `LOCATION` film's loop (section 3, `#1002`, shares of lavapipe's queue thread) a renderer change can cut without moving a pixel is open too; each would justify an issue, none filed without the owner:
   the rasterizers' work (`26.7%`; an issue cutting per-fragment work in the plane shader, after open question 5);
   the draw module's vertex work (`21.4%`, the world's `11.0%`; an issue cutting the world vertices sent to the draw module);
   line setup and binning (`14.6%`, the world's `13.0%`; an issue drawing the world's outlines with fewer or cheaper line primitives at the same pixels);
   storing the fragment state (`try_update_scene_state`; `10.2%`, the world's `4.5%`; an issue cutting the fragment-state stores a frame, which by the source follow fragment-visible binds and pipeline switches, of which `#1000` counts the world decals' share and rules out batching them by screen box, Ruled out);
   other state changes and pipeline binds (`8.5%`, the world's `4.2%`; the same issue as the state store);
   triangle setup and binning (`5.4%`, the world's `2.3%`, near the bar; the vertex issue).
   Which binds trigger a fragment-state store was read from Mesa 25.2.8's source; how many stores a frame makes was not counted.
   _Source: [where Windows lavapipe spends the loop on the whole LOCATION film](../1002_lavapipe-world-profile/journal.md#2026-11-23-where-windows-lavapipe-spends-the-loop-on-the-whole-location-film)._
   The memory rise during rendering is not these draws either: its timing is consistent with lavapipe filling the world's device buffers at the first submit ([section 7](../../../research/parity/lavapipe-render-time.md#7-memory-per-worker), `[Supported Inference]` from other figures), though it is about half of the world's 333.75 MiB of buffers; untested.

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), open question 1, condensed; the lever shares are in § 3.

## 2026-11-21: In-process pooling, as Ruled out stated it (#916)

* **In-process multi-`VkDevice` pooling for 4 workers (#916):** regresses on Ubuntu (15.89 s loop, 58.22 s CPU, against 7.65 s and 45.70 s in 4 child processes) and trails child processes on Windows (6.73 s shared, 5.45 s separate instances, against 4.34 s); section 5.

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), Ruled out, condensed; the figures are in § 5.

## 2026-11-24: The note summary before the second pass

summary: "Which renderer changes cut headless render time on lavapipe and the GPU, where the time goes now, and what a render's memory goes to per worker. Landed: #596, #602, #644, #811, the view-facing cull #914 (52.4% to 80.6% of the Windows lavapipe loop in its probe), #933, #942, #943 and #944, and stuntreel --workers (#916): four child processes render LOCATION 1.85x faster on 4 vCPUs, while four in-process VkDevices sharing one instance regress on Ubuntu Mesa 25.2.8. On lavapipe the world's base and decal draws hold 49.0% of the whole LOCATION loop, on Span B mostly the decal fill-to-outline switch (by elimination); #1002's stack profile puts the whole LOCATION loop on lavapipe's queue thread (rasterizers 26.7%, vertex work 21.4%, line setup 14.6%, fragment-state store try_update_scene_state 10.2% and 28.3% of Span B, other state 8.5%, triangle setup 5.4%, submit 2.1%). #999's CPU probe sizes a frame-streamed world at up to 75,576 vertices, 76,008 indices and 149,956 outline indices a frame (INTRO tick 3635, 2.88 MiB vs LOCATION's 333.75 MiB baked). A LOCATION render's memory is mostly its world mesh (1,004 MiB Linux lavapipe peak vs CTRY's 139 MiB; release_world_mesh brings it to 749 MiB; each extra lavapipe device adds 751..796 MiB RSS). Other processes' CPU load slows the Span B lavapipe loop (16 spinners +75.2%), so mise run ab now records it and gates on it (#1018). No-go: culling actors, #919, #915b, #926, #622, #920 and #1000."

The pass began from `46e5b20c`, whose summary was this text without the `#1018` sentence before `No-go:`; main added that sentence in `19869b40` (2026-11-24), and the merged note keeps it.

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), its `summary:`, shortened.
