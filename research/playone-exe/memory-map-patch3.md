---
summary: "Patch #3 `PLAYONE.EXE` counterparts of memory-map rows, unmapped ones marked: moved `DGROUP` offsets, unchanged work-segment offsets, and code addresses, paired function by function."
---
# Memory Map: Patch #3 Build

Part of the `PLAYONE.EXE` memory map: [`memory-map.md`](memory-map.md) lists its files and states the default conventions (target binary, image base, linear address); a section that differs says so.
Section numbers run across the files.

## 1.1 Patch #3 build

Every row of the other memory-map files is for the unpatched 1992 `PLAYONE.EXE` (102,703 bytes, sha256 `3c93493c…`).
Patch #3's `PLAYONE.EXE` (97,790 bytes, `fc532c94…`) is relinked: `DGROUP` is paragraph `0x0C71` (`DS = 0x0E66` under dosbox-automation), the display-list VM segment `0x0754` (was `0x0824`) and the work segment `0x14BF` (was `0x15D4`), and the `DGROUP` data moved by 12 different shifts, so no single shift maps it.
The tables below give Patch #3 counterparts for rows of [§ 1](memory-map.md#1-dgroup-memory-reference-table), [§ 3](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm) and [`[MEM-PALETTE]`](memory-map-main.md#-mem-palette) on both builds; a § 1 or code row absent here has no counterpart recorded.
They come from pairing the two images function by function with `mise run pair-builds`; the method, the counts and what did not pair are in [`patch3.md` § 4](patch3.md#4-function-pairing-the-whole-map).
Patched offsets are `[Supported Inference]` (static) unless a row says otherwise.
The unpatched row's own tier is unchanged.

The **Evidence** column says how each patched offset was found.
*N refs* means N memory operands name the offset in paired instructions and all N give this answer.
*N disp* means N paired displacements off a base or index register (`[bx + 0x4F02]`, an array or table base) do.
*N imm* means N paired immediates equal to the offset (a pointer loaded into a register) do.
*Bracketed* means no instruction names it and the nearest named offsets on both sides share one shift.
*Bytes* means the 16 initialised bytes at the two offsets are equal.

**`DGROUP` (`DS`) offsets.**

| Unpatched | Patch #3 | Evidence | Row | Anchor |
|---|---|---|---|---|
| `0x0542` | `0x05BE` | 13 refs | Segment of the display-list work segment (`mov es, [0x542]` before `es:[0x8078]`) | |
| `0x056C` | `0x05E8` | 1 disp (`jmp [bx+0x56C]` at `0x213D`, `jmp [bx+0x5E8]` at patched `0x2250`, in the paired `SP_1NODE` handlers; [`lod.md`](lod.md) section 1.2) | Scene-walker dispatch table entered by a near `SP_1NODE` | |
| `0x05AC`, `0x05B5`, `0x05BE`, `0x05CA`, `0x05D4`, `0x05DB` | `0x0628`, `0x0631`, `0x063A`, `0x0646`, `0x0650`, `0x0657` | 1, 1, 1, 1, 2, 1 imm; bytes for each | `game.cfg`, `game.var`, `install.exe`, `pfont.bin`, `pilots`, `res\*.res` | |
| `0x065D`, `0x069B` | `0x06D9`, `0x0717` | 1 imm each; bytes | Memory and disk-space messages | |
| `0x09DE`, `0x09EA` | `0x0A62`, `0x0A6E` | 1 imm, 2 imm; bytes | Sky colour pairs; blended zenith and horizon | `# [MEM-PALETTE]` |
| `0x09F0`, `0x09F6` | `0x0A74`, `0x0A7A` | 1 imm each; the 6 bytes of each entry match | Day and night colours of entries 213–214 | `# [MEM-PALETTE]` |
| `0x0A58`, `0x0A62` | `0x0ADC`, `0x0AE6` | 2 imm each; bytes | `VAULT\*.*`, `LOAD FILM` | |
| `0x0AAB` | `0x0B1E` | 2 imm | Selected film path buffer | |
| `0x0C10` | `0x0D22` | 2 imm: `mov di, 0x0C10` before `jmp 0x5404` pairs with `mov di, 0x0D22` before `jmp 0x55FB`. No memory operand names it, and its neighbours moved `+0x74`, not `+0x112` | The address the code passes; that it holds a camera rig stays `[Hypothesis]` ([§ 2](memory-map-runtime.md#2-runtime-dynamic-capture-anchors)) | `# [MEM-CAMERA-RIG]` |
| `0x0C50` | `0x0CC4` | 1 imm; bytes | Actor-table far pointer, `[Hypothesis]` ([§ 2](memory-map-runtime.md#2-runtime-dynamic-capture-anchors)) | `# [MEM-ACTOR-TABLE]` |
| `0x0CA0` | `0x0D14`, `[Hypothesis]` | bracketed; the bytes differ | Local stage block, `[Hypothesis]` ([§ 2](memory-map-runtime.md#2-runtime-dynamic-capture-anchors)) | `# [MEM-ACTOR-TABLE]` |
| `0x0C60` | unmapped | No instruction names it in either build, so nothing pairs it | Retired label | |
| `0x10A4` | `0x0E26` | 1 imm (`mov si, 0x10A4` before the copy to `0x2240`); its 17 near pointers are the 17 paired driver entries (`0x7B70` → `0x6E77`, …) | Graphics driver vector source | `# [MEM-PALETTE]` |
| `0x2240` | `0x1BC6` | 1 ref; bytes | Driver vector table | `# [MEM-PALETTE]` |
| `0x225A` | `0x1BE0` | 12 refs | Text driver slot | |
| `0x2263`, `0x2264`, `0x2265` | `0x1BE9`, `0x1BEA`, `0x1BEB` | 11, 4, 3 refs | Display mode, sound driver mode, audio channel flags | |
| `0x2272` | `0x1BF8` | 20 refs | Playback-active flag | `# [MEM-FLM-TICK]` |
| `0x2275` | `0x1BFB` | 2 refs | Video-mode flag | `# [MEM-PALETTE]` |
| `0x227A`, `0x227B`, `0x227C`, `0x227D` | `0x1C00`, `0x1C01`, `0x1C02`, `0x1C03` | 9, 3, 3, 2 refs | Screen-faded flag, cached palette inputs | `# [MEM-PALETTE]` |
| `0x2285` | `0x1C0B` | 2 refs; bytes | View-direction selector | |
| `0x2294`, `0x2296`, `0x2298`, `0x229A` | `0x1C1A`, `0x1C1C`, `0x1C1E`, `0x1C20` | 27, 16, 13, 9 refs | Credits clip rectangle | |
| `0x229C`, `0x229E`, `0x22A4` | `0x1C22`, `0x1C24`, `0x1C2A` | 4, 4, 2 refs | Lens mantissa, lens shift count, `0x22A4` | `# [MEM-PALETTE]` |
| `0x22B6` | `0x1C3C` | 2 refs | View-setup scale | `# [MEM-PALETTE]` |
| `0x22B8` | `0x1C3E` | 3 refs; a live capture ([`patch3.md` § 2](patch3.md#2-patched-playoneexe-offsets)) | Global 50 Hz tick | `# [MEM-FLM-TICK]` |
| `0x22BC` | `0x1C42` | 1 ref | Var 10 at the previous frame's bank write (`0x1D96`) | `# [MEM-PALETTE]` |
| `0x22C4` | `0x1C4A`, `[Established]` | 3 refs (`mov [0x1C4A], es` in the patched entry routine) | Stored PSP segment | |
| `0x22CA`, `0x22CC` | `0x1C50`, `0x1C52`, `[Bounded Observation]` | 17, 6 refs; a live capture flagged 72 of 1,906 frames torn against 66 of 1,908 unpatched ([`patch3.md` § 3.1](patch3.md#31-composed-pages)) | Composed-page segments | |
| `0x22CE`, `0x22D0` | `0x1C54`, `0x1C56` | 2 refs each | Saved `SS`, `SP` around the `INSTALL.EXE` EXEC | |
| `0x22DE` | `0x1C64` | 2 refs; bytes | View camera's slot record pointer | |
| `0x22EC` | `0x1C72` | 1 ref (`0x215A`, patched `0x226D`; [`lod.md`](lod.md) section 1.2) | `SP_1NODE` stand-in object word | |
| `0x2A68` | `0x23EE` | 4 refs; bytes | View eye | |
| `0x2468` | `0x1DEE` | 3 imm | Base palette | `# [MEM-PALETTE]` |
| `0x2768` | `0x20EE` | 9 imm; a live capture read identical palettes ([`patch3.md` § 2](patch3.md#2-patched-playoneexe-offsets)) | Working palette | `# [MEM-PALETTE]` |
| `0x474A` | `0x40D0` | 12 imm | Live film-state struct | `# [MEM-PALETTE]` |
| `0x474A + 0x7E + 2n` (`0x47C8 + 2n`) | `0x40D0 + 0x7E + 2n` (`0x414E + 2n`) | 1 imm on `0x47C8`; the struct moved whole | Live film variables: var 13 `0x47E2` → `0x4168`, vars 14 and 15 `0x47E4`/`0x47E6` → `0x416A`/`0x416C` | `# [MEM-PALETTE]` |
| `0x4758` | `0x40DE` | 8 refs | `0x474A + 0x0E`, not the film clock | `# [MEM-FLM-TICK]` |
| `0x4764`, `0x4778` | `0x40EA`, `0x40FE` | 1 ref, 2 disp | `0x474A + 0x1A` (`view_obj`); per-slot record pointers | `# [MEM-PALETTE]` |
| `0x4888` | `0x420E` | 11 refs | Snapshot struct | `# [MEM-PALETTE]` |
| `0x4896` | `0x421C` | 17 refs (the byte match of [`patch3.md` § 2](patch3.md#2-patched-playoneexe-offsets) found 2); a live capture | Active film clock | `# [MEM-FLM-TICK]` |
| `0x48A2`, `0x48B6`, `0x4906` | `0x4228`, `0x423C`, `0x428C` | 1 ref, 1 disp, 1 imm | Snapshot `view_obj`, per-slot pointers, variable copies | `# [MEM-PALETTE]` |
| `0x49C6` | `0x434C` | 3 imm | The recorder's previous variables | `# [MEM-PALETTE]` |
| `0x49EC`, `0x49EE`, `0x49F0` | `0x4372`, `0x4374`, `0x4376` | 4 refs each | Sun or moon direction from var 13 | `# [MEM-PALETTE]` |
| `0x4F02` | `0x4888` | 6 disp | `PFONT.BIN` width table | |

**Work-segment offsets are all unchanged.**
The work segment is the same `0x8130` bytes in both images.
Of the 165 offsets that the VM segment names through `DS`, 164 are work-segment offsets and pair with themselves; the other, `0x8042`, is read while `DS` is `DGROUP` and moved `-0x67A`.
All 50 offsets the main program names through `ES` pair with themselves.
The segment's initial bytes are identical except 12 at `0x1952..0x195D`.
So the [§ 3](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm) table holds on the patched build as written: `0x19A8`, `0x41B8`, `0x41C8`/`0x41CA`, `0x41D4..0x41DA`, `0x4450 + n*12`, `0x7468`, `0x806C..0x8070`, `0x8072`, `0x8078`, `0x8082..0x8088`, `0x80C0..0x80CA`, `0x8108..0x810C` and `0x8120..0x8128` each pair at least once.
The anchor table (`0x0000`, `0x0004 + n*0x1C`) is reached through registers, so no operand names it; it is unchanged by the same identity.
The segment's runtime paragraph is the load paragraph plus `0x14BF`.
On the patched build, read it from `DS:0x05BE`; that is unpatched `DS:0x0542`, and unpatched `0x05BE` holds the `install.exe` string.

**Code addresses**, as load-image offsets.
The notebook addresses of `[MEM-SOD-VM]` are image `- 0x6F30`; a VM `CS:IP` is image `- 0x8240` unpatched and `- 0x7540` patched.
Each patched address is an aligned instruction of a paired function unless the row says otherwise.

| Unpatched image | Patch #3 image | Row | Anchor |
|---|---|---|---|
| `0x0C5E` | `0x0D70`, the patched header's entry `CS:IP` | Entry point; the per-frame trap conflict of [§ 2](memory-map-runtime.md#-mem-vsync-03da) is unaffected. The only `0x03DA` poll in either image is in the DAC upload, `0x7B79` → `0x6E80` | `# [MEM-VSYNC-03DA]` |
| `0x0C78`, `0x0C90`, `0x0C94`, `0x0C98`, `0x0CBD`, `0x0CC4`, `0x0CC8`, `0x0CD2`, `0x0CF2`, `0x0CFA` | `0x0D8A`, `0x0DA2`, `0x0DA6`, `0x0DAA`, `0x0DCF`, `0x0DD6`, `0x0DDA`, `0x0DE4`, `0x0E04`, `0x0E0C` | Entry-routine instructions cited in [§ 1](memory-map.md#1-dgroup-memory-reference-table) | |
| `0x0EE6`, `0x0EE9` | `0x0FFA`, `0x0FFD` | Per-frame film render step | `# [MEM-PALETTE]` |
| `0x0F84`, `0x58D0` | `0x1097`, `0x5AC7` | Credits centring, string width | |
| `0x0FD2` | `0x10E5` | Palette build | `# [MEM-PALETTE]` |
| `0x11F8`, `0x11FC`, `0x122E`, `0x1238`, `0x123D` | `0x130B`, `0x130F`, `0x1341`, `0x134B`, `0x1350` | View setup and its lens stores | `# [MEM-PALETTE]` |
| `0x1251` | `0x1364` | View setup: eye copy from the view slot record (the `view-slot` plan's break) | |
| `0x12DC`, `0x12E3`, `0x12F8` | `0x13EF`, `0x13F6`, `0x140B` | Lens zoom of the view matrix | `# [MEM-PALETTE]` |
| `0x136F` | `0x1482` | Film-variable interpolation | `# [MEM-PALETTE]` |
| `0x196C` | `0x1A7F` | World light from var 13 (the same 14 instructions) | `# [MEM-PALETTE]` |
| `0x1D96` | `0x1EA9` | Vars 10 and 12 to the work segment | `# [MEM-PALETTE]` |
| `0x39B0`, `0x39D0` | `0x3AC3`, `0x3AE3` | Film-state snapshot and its variable copy | `# [MEM-PALETTE]` |
| `0x3D54`, `0x3D7F` | `0x3E67`, `0x3E92` | `var_set` and `view_obj` handlers | `# [MEM-PALETTE]` |
| `0x42F5` | `0x4428` | Film recorder | `# [MEM-PALETTE]` |
| `0x4A29`, `0x4A32`, `0x4A35` | `0x4B68`, `0x4B71`, `0x4B74` | Frame loop: lens scale, `view_obj` load, render-step call | `# [MEM-PALETTE]` |
| `0x6E1B` | unmapped | The alternate video-mode path. Its function, `0x6DCB`, is one of the 12 unpatched display-driver functions with no patched counterpart; the patch dropped Tandy and CGA graphics | `# [MEM-PALETTE]` |
| `0x737B` | `0x65A1` | `int 10h` mode `0x13` | `# [MEM-PALETTE]` |
| `0x7B70` | `0x6E77` | VGA DAC upload | `# [MEM-PALETTE]` |
| `0x8240 + 9n` (notebook `0x1310 + 9n`) | `0x7540 + 9n` for opcodes `9n` up to `0x0333`; unpatched opcode `0x033C` has no patched slot; unpatched opcode `0x0345 + 9k` is patched `0x033C + 9k` | Dispatch slots: 108 unpatched, 107 patched, paired through their handlers ([`patch3.md` § 4.1](patch3.md#41-the-patched-build-has-one-dispatch-slot-fewer)) | `# [MEM-SOD-VM]` |
| `0x843E` (notebook `0x150E`) | `0x773E` | `OP_ANIMATE` (`0x01F8`) slot jump; below `0x033C`, so the same slot | `# [FMT-SOD-ANIMATE]` |
| `0x8A1C`, `0x8C45` (VM `0x07DC`, `0x0A05`) | `0x7D13`, `0x7F3C` (VM `0x07D3`, `0x09FC`) | Frame-routine targets chosen by the video-mode flag | `# [MEM-PALETTE]` |
| `0x908E` | `0x8385` | Sun projection through the camera matrix | `# [MEM-PALETTE]` |
| `0x9100`, `0x9106` | `0x83F7`, `0x83FD` | Light setup entries | |
| `0x94D8`, `0x95C0`, `0x9BB3`, `0x9BCC`, `0x9BE5` | `0x87CF`, `0x88B7`, `0x8DBE`, `0x8DD7`, `0x8DF0` | `REJVEC`, `REJ2D`, `BVIS`, `IFVIS` and `BZLT` handlers, byte for byte | `# [FMT-SOD-IFVIS]` |
| `0xA9DC` (notebook `0x3AAC`) | `0x9BE7` | `OP_ANIMATE` handler | `# [FMT-SOD-ANIMATE]` |
| `0xAD88`, `0xAE66` (notebook `0x3E58`, `0x3F36`) | `0x9F93`, `0xA071` | `OP_TAP` handler, `OP_HUGETAP` entry | `# [MEM-SOD-VM]` |
| `0xB85D` (notebook `0x492D`) | `0xAA68` | Anchor-cache invalidation | `# [MEM-SOD-ANCHOR-TABLE]` |
| `0x1DEA:0x05B1` (image `0x1E451`) | `0x1CD5:0x0B67` (image `0x1D8B7`), by its one paired far call, from `0x104B` (unpatched call site `0x0F3A`) | PCM mixer var-11 setter. The mixer segment was rewritten (2 of its 30 functions pair): the patched setter takes var 11 in `AX` and a channel in `BX` and stores it at `+0x12` of that channel's record in segment `0x1F57`, so `cs:[0x49]` and `cs:[0xD7]` have no patched counterpart | `# [MEM-PALETTE]` |

The relocation rule of [§ 1](memory-map.md#1-dgroup-memory-reference-table) (`image + 0x8240` in the DOSBox-X session) adds the load paragraph times 16, which depends on the emulator, not the build.
Its VM `CS:IP` term is the VM segment's image offset: `0x7540` (paragraph `0x0754`) on the patched build.
