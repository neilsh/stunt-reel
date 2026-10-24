//! Deterministic fuzz support: a fixed-seed PRNG and the byte mutator shared by the
//! `*_fuzz.rs` integration tests, so no external crate is needed and failures reproduce.

/// Simple deterministic PRNG (Xorshift64) to avoid external crate dependencies.
pub(crate) struct XorShift64 {
    state: u64,
}

impl XorShift64 {
    pub(crate) fn new(seed: u64) -> Self {
        Self {
            state: if seed == 0 {
                0x8543_5897_4EC5_D643
            } else {
                seed
            },
        }
    }

    pub(crate) fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    pub(crate) fn next_u8(&mut self) -> u8 {
        self.next_u64() as u8
    }

    pub(crate) fn next_range(&mut self, min: usize, max: usize) -> usize {
        if min >= max {
            return min;
        }
        let span = (max - min) as u64;
        min + (self.next_u64() % span) as usize
    }

    pub(crate) fn fill_bytes(&mut self, buf: &mut [u8]) {
        for b in buf.iter_mut() {
            *b = self.next_u8();
        }
    }
}

/// Apply `1..max_mutations` random mutations (bit flip, byte overwrite, truncation, byte
/// insertion) to `mutated`, drawing every decision from `rng`.
pub(crate) fn mutate(rng: &mut XorShift64, mutated: &mut Vec<u8>, max_mutations: usize) {
    let mutation_count = rng.next_range(1, max_mutations);

    for _ in 0..mutation_count {
        let op = rng.next_range(0, 4);
        match op {
            0 => {
                // Bit flip
                if !mutated.is_empty() {
                    let idx = rng.next_range(0, mutated.len());
                    let bit = 1 << rng.next_range(0, 8);
                    mutated[idx] ^= bit;
                }
            }
            1 => {
                // Byte overwrite
                if !mutated.is_empty() {
                    let idx = rng.next_range(0, mutated.len());
                    mutated[idx] = rng.next_u8();
                }
            }
            2 => {
                // Truncation
                if !mutated.is_empty() {
                    let new_len = rng.next_range(0, mutated.len());
                    mutated.truncate(new_len);
                }
            }
            3 => {
                // Byte insertion
                let idx = rng.next_range(0, mutated.len() + 1);
                mutated.insert(idx, rng.next_u8());
            }
            _ => unreachable!(),
        }
    }
}
