# Instruction counts

## 3680..=3739

Baseline `base`, 3 repeats: whole-run range 4,631,541, outside the allocator 1,390,599.

* `base` (3 repeats), median, change, multiple of range:
  * whole run: 31,935,345,385 (+0, +0.0000%), 0.0x the baseline's range
  * outside glibc's `malloc.c` and `memmove`: 30,095,422,004 (+0, +0.0000%), 0.0x the baseline's range
* `shape` (3 repeats), median, change, multiple of range:
  * whole run: 29,071,377,533 (-2,863,967,852, -8.9680%), 618.4x the baseline's range
  * outside glibc's `malloc.c` and `memmove`: 27,270,934,828 (-2,824,487,176, -9.3851%), 2031.1x the baseline's range
  * stores: same
  * top function differences, repeat 0 against the baseline's:
    * ???: 8,411,161,435 -> 5,191,371,143 (-3,219,790,292)
    * <core::iter::adapters::flatten::FlatMap<core::slice::iter::Iter<core::ops::range::Range<usize>>, core::iter::adapters::map::Map<core::iter::adapters::zip::Zip<core::slice::iter::Iter<[f32; 3]>, core::ops::range::Range<usize>>, stunt_render::mesh::apex_vertices::{closure#0}::{closure#1}>, stunt_render::mesh::apex_vertices::{closure#0}> as core::iter::traits::iterator::Iterator>::next: 0 -> 445,315,413 (+445,315,413)
    * <stunt_render::mesh::GpuChunk>::upload: 37,822 -> 110,285,084 (+110,247,262)
    * __memset_avx2_unaligned_erms: 232,085,526 -> 337,339,626 (+105,254,100)
    * llvm::SelectionDAG::computeKnownBits(llvm::SDValue, llvm::APInt const&, unsigned int) const: 94,628,394 -> 72,358,637 (-22,269,757)
    * _int_malloc: 406,268,260 -> 392,026,255 (-14,242,005)
    * __memcpy_avx_unaligned_erms: 670,879,132 -> 684,475,491 (+13,596,359)
    * llvm::TargetLowering::SimplifyDemandedBits(llvm::SDValue, llvm::APInt const&, llvm::APInt const&, llvm::KnownBits&, llvm::TargetLowering::TargetLoweringOpt&, unsigned int, bool) const: 50,914,165 -> 42,553,617 (-8,360,548)
    * llvm::TargetLowering::SimplifyDemandedVectorElts(llvm::SDValue, llvm::APInt const&, llvm::APInt&, llvm::APInt&, llvm::TargetLowering::TargetLoweringOpt&, unsigned int, bool) const: 62,360,532 -> 54,713,771 (-7,646,761)
    * llvm::SelectionDAGISel::SelectCodeCommon(llvm::SDNode*, unsigned char const*, unsigned int): 52,970,367 -> 46,514,202 (-6,456,165)

One span's repeat range does not bound another's: the allocator's noise differs by film and span, and a difference of two spans adds both spans' noise.
