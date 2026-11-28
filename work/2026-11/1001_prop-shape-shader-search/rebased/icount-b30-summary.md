# Instruction counts

## 3680..=3709

Baseline `base`, 3 repeats: whole-run range 4,674,521, outside the allocator 912,520.

* `base` (3 repeats), median, change, multiple of range:
  * whole run: 28,159,572,670 (+0, +0.0000%), 0.0x the baseline's range
  * outside glibc's `malloc.c` and `memmove`: 26,593,611,349 (+0, +0.0000%), 0.0x the baseline's range
* `shape` (3 repeats), median, change, multiple of range:
  * whole run: 26,759,290,554 (-1,400,282,116, -4.9727%), 299.6x the baseline's range
  * outside glibc's `malloc.c` and `memmove`: 25,214,126,982 (-1,379,484,367, -5.1873%), 1511.7x the baseline's range
  * stores: same
  * top function differences, repeat 0 against the baseline's:
    * ???: 5,499,536,325 -> 3,729,296,209 (-1,770,240,116)
    * <core::iter::adapters::flatten::FlatMap<core::slice::iter::Iter<core::ops::range::Range<usize>>, core::iter::adapters::map::Map<core::iter::adapters::zip::Zip<core::slice::iter::Iter<[f32; 3]>, core::ops::range::Range<usize>>, stunt_render::mesh::apex_vertices::{closure#0}::{closure#1}>, stunt_render::mesh::apex_vertices::{closure#0}> as core::iter::traits::iterator::Iterator>::next: 0 -> 441,903,963 (+441,903,963)
    * <stunt_render::mesh::GpuChunk>::upload: 28,042 -> 109,112,054 (+109,084,012)
    * __memset_avx2_unaligned_erms: 226,707,211 -> 330,805,247 (+104,098,036)
    * llvm::SelectionDAG::computeKnownBits(llvm::SDValue, llvm::APInt const&, unsigned int) const: 94,628,394 -> 72,358,637 (-22,269,757)
    * _int_malloc: 381,607,094 -> 366,066,457 (-15,540,637)
    * __memcpy_avx_unaligned_erms: 461,735,431 -> 474,804,680 (+13,069,249)
    * llvm::TargetLowering::SimplifyDemandedBits(llvm::SDValue, llvm::APInt const&, llvm::APInt const&, llvm::KnownBits&, llvm::TargetLowering::TargetLoweringOpt&, unsigned int, bool) const: 50,914,165 -> 42,553,617 (-8,360,548)
    * llvm::TargetLowering::SimplifyDemandedVectorElts(llvm::SDValue, llvm::APInt const&, llvm::APInt&, llvm::APInt&, llvm::TargetLowering::TargetLoweringOpt&, unsigned int, bool) const: 62,360,532 -> 54,713,771 (-7,646,761)
    * llvm::SelectionDAGISel::SelectCodeCommon(llvm::SDNode*, unsigned char const*, unsigned int): 52,970,367 -> 46,514,202 (-6,456,165)

One span's repeat range does not bound another's: the allocator's noise differs by film and span, and a difference of two spans adds both spans' noise.
