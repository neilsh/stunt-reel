"""Pair two builds of a real-mode program function by function and map their offsets.

Two links of the same program (`PLAYONE.EXE` before and after Patch #3) hold mostly the same
functions in mostly the same order, with their code and data at different addresses. This
module decodes the code segments of both load images with iced-x86, splits each segment into
functions at its call targets, pairs the functions (identical instruction shapes first, then an
order-preserving alignment of the rest by similarity), aligns the instructions inside each
pair, and reads off what every aligned operand became: data offsets, segment values and code
addresses. Method and results: `research/playone-exe/patch3.md` section 4.

It lives in `python/scripts/`, not the shipped `stunt_reel` package, because it needs iced-x86,
a dev-group dependency (ADR 0010, ADR 0033). `pair_builds.py` and other scripts import it.

Operands are abstracted before comparison: register names, small constants (below `0x100`)
and small displacements stay in an instruction's shape; addresses, larger constants and branch
targets become wildcards and are recorded as a `Ref`, so two instructions match when they do
the same thing to different addresses.
"""

from __future__ import annotations

import bisect
import difflib
import itertools
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import cast
lazy from pathlib import Path

import unlzexe
from iced_x86 import (
    Code,
    Decoder,
    FlowControl,
    Formatter,
    FormatterSyntax,
    Instruction,
    MemorySizeExt,
    Mnemonic,
    OpKind,
    Register,
)

#: An immediate or displacement at or above this, and below its negation, is an address.
SMALL: int = 0x100
#: Functions whose instruction shapes are this similar or more may pair.
MIN_RATIO: float = 0.5

#: Ref kinds: an absolute memory operand, a displacement off a base or index register, an
#: immediate, a relocated immediate (a segment value), a far pointer, a near branch target.
MEM, DISP, IMM, SEG, FAR, BRANCH = "mem", "disp", "imm", "seg", "far", "branch"


@dataclass(frozen=True, slots=True)
class Ref:
    """One abstracted operand: its kind, segment override (`""` for none) and value."""

    kind: str
    override: str
    value: int


@dataclass(frozen=True, slots=True)
class Insn:
    """A decoded instruction at a load-image offset, with its shape and abstracted operands."""

    addr: int
    shape: tuple[str, ...]
    refs: tuple[Ref, ...]
    text: str


@dataclass(frozen=True, slots=True)
class Function:
    """The instructions from one call target up to the next, in one code segment."""

    paragraph: int
    start: int
    insns: tuple[Insn, ...]

    @property
    def shapes(self) -> tuple[tuple[str, ...], ...]:
        """The instruction shapes, the sequence two functions are compared by."""
        return tuple(insn.shape for insn in self.insns)


@dataclass(frozen=True, slots=True)
class LoadImage:
    """An unpacked real-mode load image: bytes, relocation offsets and entry point."""

    data: bytes
    relocs: frozenset[int]
    entry_cs: int
    entry_ip: int
    stack_paragraph: int

    @property
    def entry(self) -> int:
        """The entry point as a load-image offset."""
        return self.entry_cs * 16 + self.entry_ip

    def word(self, offset: int) -> int:
        """The little-endian word at *offset*."""
        value: int = struct.unpack_from("<H", self.data, offset)[0]
        return value

    def paragraphs(self) -> list[int]:
        """Every segment value the relocations name, plus the stack segment, ascending."""
        named = {self.word(r) for r in self.relocs if r + 2 <= len(self.data)}
        return sorted(named | {self.entry_cs, self.stack_paragraph})

    def code_paragraphs(self) -> list[int]:
        """Segments that a relocated far call or jump lands in, plus the entry segment."""
        targets = {self.entry_cs}
        for r in self.relocs:
            if r >= 3 and self.data[r - 3] in {0x9A, 0xEA}:
                targets.add(self.word(r))
        return sorted(targets)

    def segment_end(self, paragraph: int) -> int:
        """Where the segment at *paragraph* ends: the next named segment, or the image end."""
        later = [p for p in self.paragraphs() if p > paragraph]
        return min(later[0] * 16 if later else len(self.data), len(self.data))

    def dgroup(self) -> int:
        """The data segment the entry routine loads into `DS` (`mov ax, seg; mov ds, ax`)."""
        code = self.data[self.entry : self.entry + 0x100]
        insns = list(Decoder(16, code, ip=self.entry))
        for first, second in itertools.pairwise(insns):
            # iced's stubs list one member per enum, so compare as plain ints (see `_int`).
            if (
                _int(first.code) == _int(Code.MOV_R16_IMM16)
                and _int(first.op0_register) == _int(Register.AX)
                and _int(second.code) == _int(Code.MOV_SREG_RM16)
                and _int(second.op0_register) == _int(Register.DS)
                and _int(second.op1_register) == _int(Register.AX)
            ):
                value: int = first.immediate(1)
                return value
        raise ValueError("the entry routine does not load DS from an immediate")


def load_image(path: Path) -> LoadImage:
    """Unpack an LZEXE 0.91 executable into a load image."""
    image, meta = unlzexe.unpack(path.read_bytes())
    entry = cast("dict[str, int]", meta["entry"])
    relocs = cast("list[int]", meta["relocs"])
    return LoadImage(bytes(image), frozenset(relocs), entry["cs"], entry["ip"], entry["ss"])


def _int(value: int) -> int:
    """An iced-x86 enum value as a plain int.

    The package's stubs declare each enum with one member, so mypy would take every comparison
    between two enum values as always true.
    """
    return int(value)


def _names(namespace: object) -> dict[int, str]:
    """iced-x86 enum values to their lower-case names, for readable shapes."""
    return {v: k.lower() for k, v in vars(namespace).items() if k.isupper() and isinstance(v, int)}


_REGISTER, _MNEMONIC = _names(Register), _names(Mnemonic)
_BRANCHES = frozenset(
    {
        FlowControl.UNCONDITIONAL_BRANCH,
        FlowControl.CONDITIONAL_BRANCH,
        FlowControl.CALL,
        FlowControl.INDIRECT_BRANCH,
        FlowControl.INDIRECT_CALL,
    }
)
_IMMEDIATES = frozenset(
    {OpKind.IMMEDIATE8, OpKind.IMMEDIATE16, OpKind.IMMEDIATE8TO16, OpKind.IMMEDIATE8_2ND}
)


def _formatter() -> Formatter:
    fmt = Formatter(FormatterSyntax.INTEL)
    fmt.space_after_operand_separator = True
    fmt.hex_prefix = "0x"
    fmt.hex_suffix = ""
    fmt.uppercase_hex = False
    return fmt


def _reg(register: int) -> str:
    return _REGISTER.get(register, str(register)) if register != Register.NONE else ""


def _abstract(insn: Instruction, relocated: bool) -> tuple[tuple[str, ...], tuple[Ref, ...]]:
    """The instruction's shape and the operands abstracted out of it.

    Far branch targets are read from `far_branch_selector`/`far_branch16`; iced's text puts the
    offset first.
    """
    if insn.is_invalid:
        return (".byte",), ()
    mnemonic = _MNEMONIC.get(insn.mnemonic, str(insn.mnemonic))
    if insn.op_count == 1 and insn.op0_kind == OpKind.FAR_BRANCH16:
        target = (insn.far_branch_selector << 16) | insn.far_branch16
        return (mnemonic, "far"), (Ref(FAR, "", target),)
    shape = [mnemonic]
    refs: list[Ref] = []
    branch = insn.flow_control in _BRANCHES
    for n in range(insn.op_count):
        kind = _int(insn.op_kind(n))
        if kind == OpKind.REGISTER:
            shape.append(_reg(insn.op_register(n)))
        elif kind == OpKind.NEAR_BRANCH16:
            shape.append("T")
            refs.append(Ref(BRANCH, "", insn.near_branch16))
        elif kind in _IMMEDIATES:
            value = insn.immediate(n) & 0xFFFF
            if branch:
                shape.append("T")
                refs.append(Ref(BRANCH, "", value))
            elif relocated:
                shape.append("S")
                refs.append(Ref(SEG, "", value))
            elif SMALL <= value < 0x10000 - SMALL:
                shape.append("#")
                refs.append(Ref(IMM, "", value))
            else:
                shape.append(str(value))
        elif kind == OpKind.MEMORY:
            base, index = _reg(insn.memory_base), _reg(insn.memory_index)
            # Without a prefix, an address formed from BP is in the stack segment, not DS.
            override = _reg(insn.segment_prefix) or ("ss" if base == "bp" else "")
            disp = insn.memory_displacement & 0xFFFF
            size = MemorySizeExt.size(insn.memory_size)
            if not base and not index:
                shape.append(f"[{override}:#]{size}")
                refs.append(Ref(MEM, override, disp))
            elif SMALL <= disp < 0x10000 - SMALL:
                shape.append(f"[{override}:{base}+{index}+#]{size}")
                refs.append(Ref(DISP, override, disp))
            else:
                shape.append(f"[{override}:{base}+{index}+{disp}]{size}")
        else:  # string-operation operands and other implicit forms
            shape.append(f"k{kind}")
    return tuple(shape), tuple(refs)


def decode_segment(image: LoadImage, paragraph: int) -> list[Insn]:
    """Linear-sweep decode of one code segment, addresses as load-image offsets.

    The decoder starts at segment offset 0, so a near branch target in a `Ref` is an offset in
    the segment, as the CPU sees it. An invalid encoding decodes as one `.byte` instruction and
    the sweep goes on after it.
    """
    start, end = paragraph * 16, image.segment_end(paragraph)
    relocs = sorted(image.relocs)
    fmt = _formatter()
    out: list[Insn] = []
    for insn in Decoder(16, image.data[start:end], ip=0):
        addr = start + insn.ip
        k = bisect.bisect_left(relocs, addr)
        relocated = k < len(relocs) and relocs[k] < addr + insn.len
        shape, refs = _abstract(insn, relocated)
        out.append(Insn(addr, shape, refs, "(bad)" if insn.is_invalid else fmt.format(insn)))
    return out


def split_functions(image: LoadImage) -> dict[int, list[Function]]:
    """Each code segment's functions, split at the near and far call targets that land in it."""
    decoded = {p: decode_segment(image, p) for p in image.code_paragraphs()}
    starts: dict[int, set[int]] = {p: {p * 16} for p in decoded}
    starts[image.entry_cs].add(image.entry)
    for paragraph, insns in decoded.items():
        for insn in insns:
            for ref in insn.refs:
                if ref.kind == FAR and (ref.value >> 16) in starts:
                    seg = ref.value >> 16
                    starts[seg].add(seg * 16 + (ref.value & 0xFFFF))
                elif ref.kind == BRANCH and insn.shape[0] == "call":
                    starts[paragraph].add(paragraph * 16 + (ref.value & 0xFFFF))
    out: dict[int, list[Function]] = {}
    for paragraph, insns in decoded.items():
        index = {insn.addr: i for i, insn in enumerate(insns)}
        cuts = sorted(index[s] for s in starts[paragraph] if s in index)
        bounds = [*cuts, len(insns)]
        out[paragraph] = [
            Function(paragraph, insns[a].addr, tuple(insns[a:b]))
            for a, b in itertools.pairwise(bounds)
            if b > a
        ]
    return out


def _ratio(a: tuple[tuple[str, ...], ...], b: tuple[tuple[str, ...], ...]) -> float:
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if matcher.real_quick_ratio() < MIN_RATIO or matcher.quick_ratio() < MIN_RATIO:
        return 0.0
    ratio = matcher.ratio()
    return ratio if ratio >= MIN_RATIO else 0.0


def _increasing(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The longest run of *pairs* increasing in both indices (pairs sorted by the first)."""
    tails: list[int] = []
    tail_at: list[int] = []
    previous: list[int | None] = []
    for k, (_, b) in enumerate(pairs):
        j = bisect.bisect_left(tails, b)
        if j == len(tails):
            tails.append(b)
            tail_at.append(k)
        else:
            tails[j] = b
            tail_at[j] = k
        previous.append(tail_at[j - 1] if j else None)
    out: list[tuple[int, int]] = []
    cursor = tail_at[-1] if tail_at else None
    while cursor is not None:
        out.append(pairs[cursor])
        cursor = previous[cursor]
    return out[::-1]


def _align_gap(
    left: list[Function], right: list[Function], lo: tuple[int, int], hi: tuple[int, int]
) -> dict[int, tuple[int, float]]:
    """Order-preserving alignment of the functions strictly between two anchors."""
    us, ps = list(range(lo[0] + 1, hi[0])), list(range(lo[1] + 1, hi[1]))
    if not us or not ps:
        return {}
    score = [[_ratio(left[i].shapes, right[j].shapes) for j in ps] for i in us]
    n, m = len(us), len(ps)
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    move = [[0] * (m + 1) for _ in range(n + 1)]
    for x in range(1, n + 1):
        for y in range(1, m + 1):
            s = score[x - 1][y - 1]
            options = (best[x - 1][y], best[x][y - 1], best[x - 1][y - 1] + (s or -1.0))
            move[x][y] = max(range(3), key=options.__getitem__)
            best[x][y] = options[move[x][y]]
    out: dict[int, tuple[int, float]] = {}
    x, y = n, m
    while x and y:
        if move[x][y] == 2:
            if score[x - 1][y - 1]:
                out[us[x - 1]] = (ps[y - 1], score[x - 1][y - 1])
            x, y = x - 1, y - 1
        elif move[x][y] == 0:
            x -= 1
        else:
            y -= 1
    return out


def pair_functions(left: list[Function], right: list[Function]) -> list[tuple[int, int, float]]:
    """Index pairs `(left, right, similarity)` for two segments' functions.

    Functions with the same instruction shapes, unique on both sides and in the same order,
    pair first (similarity 1.0); the functions between two such anchors are aligned in order,
    pairing those at least `MIN_RATIO` similar.
    """
    lshapes, rshapes = [f.shapes for f in left], [f.shapes for f in right]
    lcount, rcount = Counter(lshapes), Counter(rshapes)
    rindex = {s: j for j, s in enumerate(rshapes)}
    exact = [(i, rindex[s]) for i, s in enumerate(lshapes) if lcount[s] == 1 and rcount.get(s) == 1]
    anchors = _increasing(exact)
    pairs = {i: (j, 1.0) for i, j in anchors}
    bounds = [(-1, -1), *anchors, (len(left), len(right))]
    for lo, hi in itertools.pairwise(bounds):
        pairs.update(_align_gap(left, right, lo, hi))
    return sorted((i, j, r) for i, (j, r) in pairs.items())


#: A vote's key: the left code segment it was read in, the ref kind, override and left value.
VoteKey = tuple[int, str, str, int]


@dataclass(slots=True)
class SegmentStats:
    """How much of one code segment pair matched."""

    left: int
    right: int
    left_functions: int
    right_functions: int
    exact: int
    paired: int
    aligned: int
    unpaired_left: list[int] = field(default_factory=list)
    unpaired_right: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Pairing:
    """What two builds' paired code says each left address and operand became on the right."""

    left: LoadImage
    right: LoadImage
    segments: dict[int, int]
    stats: list[SegmentStats]
    functions: list[tuple[Function, Function, float]]
    code: dict[int, int]
    votes: dict[VoteKey, Counter[int]]
    sites: dict[VoteKey, list[int]]

    def function_at(self, addr: int) -> tuple[Function, Function, float] | None:
        """The function pair whose left function holds *addr*."""
        for pair in self.functions:
            insns = pair[0].insns
            if insns and insns[0].addr <= addr <= insns[-1].addr:
                return pair
        return None


def pair_images(left: LoadImage, right: LoadImage) -> Pairing:
    """Pair *left*'s code segments with *right*'s in order, then their functions and operands."""
    lfuncs, rfuncs = split_functions(left), split_functions(right)
    if len(lfuncs) != len(rfuncs):
        raise ValueError(f"{len(lfuncs)} code segments against {len(rfuncs)}; pair them by hand")
    segments = dict(zip(sorted(lfuncs), sorted(rfuncs), strict=True))
    pairing = Pairing(left, right, segments, [], [], {}, defaultdict(Counter), defaultdict(list))
    for lpara, rpara in segments.items():
        lf, rf = lfuncs[lpara], rfuncs[rpara]
        pairs = pair_functions(lf, rf)
        stats = SegmentStats(lpara, rpara, len(lf), len(rf), 0, len(pairs), 0)
        for i, j, ratio in pairs:
            stats.exact += ratio == 1.0
            pairing.functions.append((lf[i], rf[j], ratio))
            stats.aligned += _vote(pairing, lpara, lf[i], rf[j])
        lpaired, rpaired = {i for i, _, _ in pairs}, {j for _, j, _ in pairs}
        stats.unpaired_left = [f.start for i, f in enumerate(lf) if i not in lpaired]
        stats.unpaired_right = [f.start for j, f in enumerate(rf) if j not in rpaired]
        pairing.stats.append(stats)
    return pairing


#: A run of one shape pattern this many periods long is too regular to align: an inserted or
#: deleted period can sit anywhere in it, so the aligner may pair the wrong repeats.
PERIODS: int = 4
#: The longest pattern, in instructions, checked for repetition.
MAX_PERIOD: int = 4


def periodic(shapes: tuple[tuple[str, ...], ...]) -> set[int]:
    """Indices that lie in a run of `PERIODS` or more repeats of one short shape pattern."""
    out: set[int] = set()
    for period in range(1, MAX_PERIOD + 1):
        start = 0
        for i in range(len(shapes) - period + 1):
            if i + period < len(shapes) and shapes[i] == shapes[i + period]:
                continue
            # shapes[start : i + period] repeats with this period
            if i + period - start >= PERIODS * period:
                out.update(range(start, i + period))
            start = i + 1
    return out


def _vote(pairing: Pairing, paragraph: int, a: Function, b: Function) -> int:
    """Align two paired functions' instructions and record what each operand became.

    When the two functions differ, instructions in a periodic run (a jump table, an unrolled
    loop) are left out: the aligner cannot tell which repeat a missing one was.
    """
    matcher = difflib.SequenceMatcher(None, a.shapes, b.shapes, autojunk=False)
    blocks = matcher.get_opcodes()
    differ = any(tag != "equal" for tag, *_ in blocks)
    ambiguous = periodic(a.shapes) if differ else set()
    ambiguous_right = periodic(b.shapes) if differ else set()
    aligned = 0
    for tag, i1, i2, j1, _ in blocks:
        if tag != "equal":
            continue
        for k, (x, y) in enumerate(zip(a.insns[i1:i2], b.insns[j1 : j1 + (i2 - i1)], strict=True)):
            if i1 + k in ambiguous or j1 + k in ambiguous_right:
                continue
            pairing.code[x.addr] = y.addr
            aligned += 1
            for rx, ry in zip(x.refs, y.refs, strict=True):
                if rx.kind == BRANCH:
                    continue
                key = (paragraph, rx.kind, rx.override, rx.value)
                pairing.votes[key][ry.value] += 1
                pairing.sites[key].append(x.addr)
    return aligned


def signed(value: int) -> int:
    """A 16-bit value as a signed shift."""
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


#: How a data offset was mapped: absolute memory operands naming it; displacements equal to it
#: off a base or index register (an array or table base); immediates equal to it (a pointer
#: loaded into a register); the shift its nearest referenced neighbours share; not at all.
REFERENCED, DISPLACEMENT, IMMEDIATE, BRACKETED = (
    "referenced",
    "displacement",
    "immediate",
    "bracketed",
)


@dataclass(frozen=True, slots=True)
class DataMapping:
    """Where one left data offset went, and the paired operands that say so."""

    offset: int
    mapped: int | None
    how: str
    #: Operands that agreed with `mapped`, and all operands read (`REFERENCED`, `IMMEDIATE`).
    agreeing: int = 0
    references: int = 0
    #: The nearest memory-referenced offsets on each side (`BRACKETED`, `UNMAPPED`).
    below: int | None = None
    above: int | None = None


def _data_votes(
    pairing: Pairing, paragraph: int, override: str, kinds: frozenset[str] = frozenset({MEM, DISP})
) -> dict[int, Counter[int]]:
    out: dict[int, Counter[int]] = defaultdict(Counter)
    for (para, kind, ovr, value), votes in pairing.votes.items():
        if para == paragraph and kind in kinds and ovr == override:
            out[value].update(votes)
    return out


def _memory_votes(pairing: Pairing, paragraph: int, override: str) -> dict[int, Counter[int]]:
    """Each offset's absolute-operand votes, or its displacement votes when it has none.

    The same priority as `map_data`, so a neighbour's shift and a run's shift come from the
    evidence its own query would report.
    """
    out = _data_votes(pairing, paragraph, override, frozenset({DISP}))
    out.update(_data_votes(pairing, paragraph, override, frozenset({MEM})))
    return out


def map_data(pairing: Pairing, offset: int, paragraph: int = 0, override: str = "") -> DataMapping:
    """Map a data offset that code segment *paragraph* addresses through *override*.

    Absolute memory operands naming the offset decide it when there are any; then
    displacements equal to it; then immediates equal to it (only without an override, since an
    immediate carries no segment). Otherwise it takes the shift of the nearest offsets that
    either kind of memory operand names, below and above, when they share one.
    """
    table = _memory_votes(pairing, paragraph, override)
    for kind, how in ((MEM, REFERENCED), (DISP, DISPLACEMENT)):
        votes = _data_votes(pairing, paragraph, override, frozenset({kind}))
        if offset in votes:
            target, agreeing = votes[offset].most_common(1)[0]
            return DataMapping(offset, target, how, agreeing, votes[offset].total())
    immediates = _data_votes(pairing, paragraph, "", frozenset({IMM})) if not override else {}
    if offset in immediates:
        target, agreeing = immediates[offset].most_common(1)[0]
        return DataMapping(offset, target, IMMEDIATE, agreeing, immediates[offset].total())
    keys = sorted(table)
    k = bisect.bisect_left(keys, offset)
    below = keys[k - 1] if k else None
    above = keys[k] if k < len(keys) else None
    mapped = None
    if below is not None and above is not None:
        shift_below = signed(table[below].most_common(1)[0][0] - below)
        shift_above = signed(table[above].most_common(1)[0][0] - above)
        if shift_below == shift_above:
            mapped = (offset + shift_below) & 0xFFFF
    how = BRACKETED if mapped is not None else UNMAPPED
    return DataMapping(offset, mapped, how, below=below, above=above)


@dataclass(frozen=True, slots=True)
class Run:
    """Consecutive referenced data offsets that all moved by the same shift."""

    first: int
    last: int
    shift: int
    offsets: int


def shift_runs(pairing: Pairing, paragraph: int = 0, override: str = "") -> list[Run]:
    """The data offsets segment *paragraph* references, grouped into runs of one shift."""
    runs: list[Run] = []
    for offset, votes in sorted(_memory_votes(pairing, paragraph, override).items()):
        shift = signed(votes.most_common(1)[0][0] - offset)
        if runs and runs[-1].shift == shift:
            last = runs[-1]
            runs[-1] = Run(last.first, offset, shift, last.offsets + 1)
        else:
            runs.append(Run(offset, offset, shift, 1))
    return runs


#: How a code address was mapped: an aligned instruction; an offset from the aligned
#: instruction before it in the same function pair; the far calls that land on it; not at all.
ALIGNED, ESTIMATED, FAR_CALL, UNMAPPED = "aligned", "estimated", "far call", "unmapped"


@dataclass(frozen=True, slots=True)
class CodeMapping:
    """Where one left code address went, and how that was found."""

    addr: int
    mapped: int | None
    how: str
    #: For `FAR_CALL`: the paired far calls that agreed, and all paired far calls to `addr`.
    agreeing: int = 0
    references: int = 0


def map_code(pairing: Pairing, addr: int) -> CodeMapping:
    """Map a left load-image code address to the right build."""
    if addr in pairing.code:
        return CodeMapping(addr, pairing.code[addr], ALIGNED)
    pair = pairing.function_at(addr)
    if pair is not None:
        before = [i.addr for i in pair[0].insns if i.addr < addr and i.addr in pairing.code]
        if before:
            return CodeMapping(addr, pairing.code[before[-1]] + (addr - before[-1]), ESTIMATED)
    calls: Counter[int] = Counter()
    for (_, kind, _, value), votes in pairing.votes.items():
        if kind == FAR and (value >> 16) * 16 + (value & 0xFFFF) == addr:
            for target, n in votes.items():
                calls[(target >> 16) * 16 + (target & 0xFFFF)] += n
    if calls:
        target, agreeing = calls.most_common(1)[0]
        return CodeMapping(addr, target, FAR_CALL, agreeing, calls.total())
    return CodeMapping(addr, None, UNMAPPED)


#: The first six bytes of a display-list dispatch slot, `mov word es:[si-2], imm16`; a `jmp
#: rel16` (`E9`) to the handler follows (`research/playone-exe/sod-vm.md` section 1).
SLOT_PREFIX: bytes = bytes.fromhex("26c744fe")
SLOT_BYTES: int = 9


def dispatch_slots(image: LoadImage, paragraph: int) -> list[int]:
    """Handler load-image offsets of the 9-byte dispatch slots at the start of a segment."""
    base = paragraph * 16
    handlers: list[int] = []
    at = base
    while image.data[at : at + 4] == SLOT_PREFIX and image.data[at + 6] == 0xE9:
        handlers.append(base + image.word(at + 4))
        at += SLOT_BYTES
    return handlers


def pair_slots(pairing: Pairing, paragraph: int) -> list[tuple[int, int | None]]:
    """For each left slot index, the right slot whose handler pairs with its handler."""
    left = dispatch_slots(pairing.left, paragraph)
    right = {h: k for k, h in enumerate(dispatch_slots(pairing.right, pairing.segments[paragraph]))}
    out: list[tuple[int, int | None]] = []
    for k, handler in enumerate(left):
        mapped = pairing.code.get(handler)
        out.append((k, right.get(mapped) if mapped is not None else None))
    return out
