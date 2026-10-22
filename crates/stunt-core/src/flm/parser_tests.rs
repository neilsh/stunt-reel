//! Unit tests for the `.FLM` parser's DOS-axes conversion helpers.

use super::parser::{dos_to_i1_position, dos_to_i1_quat};

#[test]
fn test_dos_to_i1_helpers() {
    assert_eq!(dos_to_i1_position([1.0, 2.0, 3.0]), [-1.0, -2.0, 3.0]);
    assert_eq!(dos_to_i1_position([0.0, 0.0, 0.0]), [0.0, 0.0, 0.0]);
    assert_eq!(dos_to_i1_quat([0.0, 0.0, 0.0, 1.0]), [0.0, 0.0, 1.0, 0.0]);
    // q and -q are one rotation; the result keeps w >= 0.
    assert_eq!(dos_to_i1_quat([0.0, 0.0, 1.0, 0.0]), [0.0, 0.0, 0.0, 1.0]);

    let n = (0.1f32 * 0.1 + 0.2 * 0.2 + 0.3 * 0.3 + 0.4 * 0.4).sqrt();
    let q = [0.1, 0.2, 0.3, 0.4].map(|c| c / n);
    let out = dos_to_i1_quat(q);
    let norm = out.iter().map(|c| c * c).sum::<f32>().sqrt();
    assert!((norm - 1.0).abs() < 1e-6);
    assert!(out[3] >= 0.0);
}
