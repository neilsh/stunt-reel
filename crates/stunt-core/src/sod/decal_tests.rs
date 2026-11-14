//! Unit tests for the SOD `decal` stage, relocated from integration tests so the stage can stay crate-private.

use crate::contracts::shape::VisibilityCondition;
use crate::sod::DECAL_FLAG_BIT;
use crate::sod::decal::{bounds_overlap, is_coplanar_facet, polygon_bounds};
use crate::sod::vm::RawPolygon;

/// A decal on each of six planes moves exactly the displacement along its normal (`[I5]`).
#[test]
fn test_challenge_i5_exact_normal_displacement_across_multiple_planes() {
    // Test decal displacement distance across 6 canonical and oblique planes:
    // 1. Horizontal ground (normal [0, 1, 0])
    // 2. Ceiling facing down (normal [0, -1, 0])
    // 3. Vertical wall facing +Z (normal [0, 0, 1])
    // 4. Vertical wall facing +X (normal [1, 0, 0])
    // 5. 45-degree ramp (normal [0, 1/sqrt(2), 1/sqrt(2)])
    // 6. 3D diagonal plane (normal [1/sqrt(3), 1/sqrt(3), 1/sqrt(3)])
    // Each facet winds clockwise seen from its normal's side, so that side is its front
    // under `FrontFace::Cw` and the decal moves toward it.

    let test_cases: Vec<([f32; 3], Vec<[f32; 3]>)> = vec![
        // Normal [0, 1, 0]
        (
            [0.0, 1.0, 0.0],
            vec![
                [-5.0, 0.0, -5.0],
                [5.0, 0.0, -5.0],
                [5.0, 0.0, 5.0],
                [-5.0, 0.0, 5.0],
            ],
        ),
        // Normal [0, -1, 0]
        (
            [0.0, -1.0, 0.0],
            vec![
                [-5.0, 10.0, 5.0],
                [5.0, 10.0, 5.0],
                [5.0, 10.0, -5.0],
                [-5.0, 10.0, -5.0],
            ],
        ),
        // Normal [0, 0, 1]
        (
            [0.0, 0.0, 1.0],
            vec![
                [-5.0, 5.0, 2.0],
                [5.0, 5.0, 2.0],
                [5.0, -5.0, 2.0],
                [-5.0, -5.0, 2.0],
            ],
        ),
        // Normal [1, 0, 0]
        (
            [1.0, 0.0, 0.0],
            vec![
                [3.0, -5.0, 5.0],
                [3.0, 5.0, 5.0],
                [3.0, 5.0, -5.0],
                [3.0, -5.0, -5.0],
            ],
        ),
        // Oblique 45-degree ramp: normal [0, 1/sqrt(2), 1/sqrt(2)]
        {
            let inv_sqrt2 = 1.0 / 2.0f32.sqrt();
            (
                [0.0, inv_sqrt2, inv_sqrt2],
                vec![
                    [-2.0, 2.0, -2.0],
                    [2.0, 2.0, -2.0],
                    [2.0, 0.0, 0.0],
                    [-2.0, 0.0, 0.0],
                ],
            )
        },
        // General 3D diagonal plane: normal [1/sqrt(3), 1/sqrt(3), 1/sqrt(3)]
        {
            let inv_sqrt3 = 1.0 / 3.0f32.sqrt();
            (
                [inv_sqrt3, inv_sqrt3, inv_sqrt3],
                vec![[0.0, 0.0, 3.0], [0.0, 3.0, 0.0], [3.0, 0.0, 0.0]],
            )
        },
    ];

    for (case_idx, (expected_normal, base_verts)) in test_cases.into_iter().enumerate() {
        let base_poly = RawPolygon {
            vertex_palette: Vec::new(),
            vertices: base_verts.clone(),
            palette_index: 30,
            normal: expected_normal,
            flags: 0,
            is_decal: false,
            visibility: VisibilityCondition::Always,
        };

        // Decal facet scaled 0.5x toward centroid of base facet
        let mut centroid = [0.0f32; 3];
        for v in &base_verts {
            centroid[0] += v[0];
            centroid[1] += v[1];
            centroid[2] += v[2];
        }
        let n = base_verts.len() as f32;
        centroid = [centroid[0] / n, centroid[1] / n, centroid[2] / n];

        let decal_verts: Vec<[f32; 3]> = base_verts
            .iter()
            .map(|v| {
                [
                    centroid[0] + 0.5 * (v[0] - centroid[0]),
                    centroid[1] + 0.5 * (v[1] - centroid[1]),
                    centroid[2] + 0.5 * (v[2] - centroid[2]),
                ]
            })
            .collect();

        let decal_poly = RawPolygon {
            vertex_palette: Vec::new(),
            vertices: decal_verts.clone(),
            palette_index: 15,
            normal: expected_normal,
            flags: 0,
            is_decal: false,
            visibility: VisibilityCondition::Always,
        };

        // Check coplanar detection
        assert!(
            is_coplanar_facet(&decal_poly, &base_poly, 1e-4, 1e-4),
            "Case {case_idx}: decal must be detected as coplanar with base facet"
        );

        // Run identification and displacement
        let processed = crate::sod::decal::identify_coplanar_decals(
            &[base_poly, decal_poly],
            0.001,
            1e-4,
            1e-4,
        );

        assert_eq!(processed.len(), 2);
        assert!(
            !processed[0].is_decal,
            "Case {case_idx}: base facet must not be decal"
        );
        assert!(
            processed[1].is_decal,
            "Case {case_idx}: decal facet must be flagged as decal"
        );
        assert_eq!(
            processed[1].flags & DECAL_FLAG_BIT,
            DECAL_FLAG_BIT,
            "Case {case_idx}: decal facet must have DECAL_FLAG_BIT set"
        );

        // Empirically verify Invariant [I5]: ||v' - v|| == 0.001 m ± 10^-6 along unit normal
        for (v_orig, v_disp) in decal_verts.iter().zip(&processed[1].vertices) {
            let dx = v_disp[0] - v_orig[0];
            let dy = v_disp[1] - v_orig[1];
            let dz = v_disp[2] - v_orig[2];

            let disp_len = (dx * dx + dy * dy + dz * dz).sqrt();
            assert!(
                (disp_len - 0.001).abs() < 1e-6,
                "Case {case_idx}: displacement magnitude {disp_len} must equal 0.001 m within 10^-6"
            );

            // Verify displacement direction matches unit normal
            let dir_x = dx / disp_len;
            let dir_y = dy / disp_len;
            let dir_z = dz / disp_len;

            let dot = dir_x * expected_normal[0]
                + dir_y * expected_normal[1]
                + dir_z * expected_normal[2];
            assert!(
                (dot - 1.0).abs() < 1e-5,
                "Case {case_idx}: displacement direction must match normal (dot={dot})"
            );
        }
    }
}

/// A polygon that is disjoint from or not coplanar with an earlier one is not a decal (`[I5]`).
#[test]
fn test_challenge_i5_rejection_of_disjoint_and_noncoplanar_facets() {
    let base = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
            [10.0, 0.0, 10.0],
            [0.0, 0.0, 10.0],
        ],
        palette_index: 20,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // 1. Same plane y=0, but spatially disjoint (x in [50, 60], z in [50, 60])
    let disjoint = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![
            [50.0, 0.0, 50.0],
            [60.0, 0.0, 50.0],
            [60.0, 0.0, 60.0],
            [50.0, 0.0, 60.0],
        ],
        palette_index: 20,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    assert!(
        !is_coplanar_facet(&disjoint, &base, 1e-4, 1e-4),
        "Disjoint facets must not be flagged as coplanar decals"
    );

    // 2. Parallel normal [0, 1, 0], overlapping in x-z, but offset in y by 0.01m (> plane_tol 1e-4)
    let parallel_offset = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![
            [2.0, 0.01, 2.0],
            [4.0, 0.01, 2.0],
            [4.0, 0.01, 4.0],
            [2.0, 0.01, 4.0],
        ],
        palette_index: 20,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    assert!(
        !is_coplanar_facet(&parallel_offset, &base, 1e-4, 1e-4),
        "Parallel facets offset in plane constant must not be flagged as coplanar decals"
    );

    // 3. Tilted by 5 degrees about z through x = 3 (tan 5 deg ~ 0.0875); matching reads
    // the winding, not the stored normal
    let tilted = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![
            [2.0, 0.0875, 2.0],
            [4.0, -0.0875, 2.0],
            [4.0, -0.0875, 4.0],
            [2.0, 0.0875, 4.0],
        ],
        palette_index: 20,
        normal: [0.087_155, 0.996_195, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    assert!(
        !is_coplanar_facet(&tilted, &base, 1e-4, 1e-4),
        "Non-parallel facets must not be flagged as coplanar decals"
    );
}

/// A later polygon coplanar with and overlapping an earlier one becomes a displaced decal.
#[test]
fn test_coplanar_decal_geometry_resolution() {
    let base = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![
            [-10.0, 0.0, -10.0],
            [10.0, 0.0, -10.0],
            [10.0, 0.0, 10.0],
            [-10.0, 0.0, 10.0],
        ],
        palette_index: 20,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // Overlapping decal on y=0 plane
    let decal = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![
            [-2.0, 0.0, -2.0],
            [2.0, 0.0, -2.0],
            [2.0, 0.0, 2.0],
            [-2.0, 0.0, 2.0],
        ],
        palette_index: 15,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // Disjoint polygon outside base bounds
    let disjoint = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![
            [50.0, 0.0, 50.0],
            [60.0, 0.0, 50.0],
            [60.0, 0.0, 60.0],
            [50.0, 0.0, 60.0],
        ],
        palette_index: 30,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // Skewed polygon, tilted about z through the origin
    let skewed = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![
            [-2.0, 0.2, -2.0],
            [2.0, -0.2, -2.0],
            [2.0, -0.2, 2.0],
            [-2.0, 0.2, 2.0],
        ],
        palette_index: 40,
        normal: [0.1, 0.99, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    assert!(is_coplanar_facet(&decal, &base, 1e-4, 1e-4));
    assert!(!is_coplanar_facet(&disjoint, &base, 1e-4, 1e-4));
    assert!(!is_coplanar_facet(&skewed, &base, 1e-4, 1e-4));

    let processed = crate::sod::decal::identify_coplanar_decals(
        &[base, decal, disjoint, skewed],
        0.001,
        1e-4,
        1e-4,
    );

    assert_eq!(processed.len(), 4);
    assert!(!processed[0].is_decal);
    assert!(
        processed[1].is_decal,
        "overlapping facet must be tagged as decal"
    );
    assert_eq!(processed[1].flags & DECAL_FLAG_BIT, DECAL_FLAG_BIT);
    // Verifies outward displacement along normal [0.0, 1.0, 0.0] by 0.001 m
    for v in &processed[1].vertices {
        assert_eq!(v[1], 0.001);
    }
    assert!(!processed[2].is_decal, "disjoint facet is not a decal");
    assert!(!processed[3].is_decal, "skewed normal facet is not a decal");
}

/// Polygon bounds are the per-axis extremes, and overlap is their intersection.
#[test]
fn test_polygon_bounds_and_overlap() {
    let p = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[1.0, -2.0, 3.0], [5.0, 10.0, -1.0], [-4.0, 2.0, 8.0]],
        palette_index: 0,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    let (min_b, max_b) = polygon_bounds(&p);
    assert_eq!(min_b, [-4.0, -2.0, -1.0]);
    assert_eq!(max_b, [5.0, 10.0, 8.0]);

    assert!(bounds_overlap(
        &min_b,
        &max_b,
        &[0.0, 0.0, 0.0],
        &[1.0, 1.0, 1.0],
        1e-4
    ));
    assert!(!bounds_overlap(
        &min_b,
        &max_b,
        &[20.0, 20.0, 20.0],
        &[25.0, 25.0, 25.0],
        1e-4
    ));
}

/// A flat ground decal moves toward the side from which it winds clockwise, whatever its
/// shading normal says (`[I5]`, `FrontFace::Cw`).
#[test]
fn ground_decal_moves_toward_its_clockwise_side() {
    let poly = |vertices: Vec<[f32; 3]>| RawPolygon {
        vertex_palette: Vec::new(),
        normal: crate::sod::vm::compute_polygon_normal(&vertices),
        vertices,
        palette_index: 15,
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    // Clockwise seen from above (+X right, -Z away): the edge cross product points down.
    let cw = |s: f32| vec![[0.0, 0.0, 0.0], [s, 0.0, 0.0], [0.0, 0.0, s]];
    let ccw = |s: f32| vec![[0.0, 0.0, 0.0], [0.0, 0.0, s], [s, 0.0, 0.0]];
    for (base, decal, y) in [(cw(10.0), cw(2.0), 0.001), (ccw(10.0), ccw(2.0), -0.001)] {
        let processed = crate::sod::decal::identify_coplanar_decals(
            &[poly(base), poly(decal)],
            0.001,
            1e-4,
            1e-4,
        );
        let [base, decal] = processed.as_slice() else {
            panic!("two polygons");
        };
        assert!(decal.is_decal && !base.is_decal);
        assert_eq!(decal.normal, base.normal, "shading normal is kept");
        assert!(
            decal.vertices.iter().all(|v| (v[1] - y).abs() < 1e-6),
            "{:?}",
            decal.vertices
        );
        assert!(base.vertices.iter().all(|v| v[1] == 0.0));
    }
}

/// A clockwise-from-above ground square `[x0, x0 + s] x [z0, z0 + s]` at height 0.
fn ground_square(x0: f32, z0: f32, s: f32, palette_index: u8) -> RawPolygon {
    let vertices = vec![
        [x0, 0.0, z0],
        [x0 + s, 0.0, z0],
        [x0 + s, 0.0, z0 + s],
        [x0, 0.0, z0 + s],
    ];
    RawPolygon {
        vertex_palette: Vec::new(),
        normal: crate::sod::vm::compute_polygon_normal(&vertices),
        vertices,
        palette_index,
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    }
}

/// A decal painted over another decal lies one level above it, so the later one stays on
/// top as the stream paints it; a decal beside it, touching only along an edge, shares its
/// level (`[I5]`).
#[test]
fn stacked_decals_rise_one_level_per_polygon_they_cover() {
    let polygons = [
        ground_square(0.0, 0.0, 10.0, 137),
        ground_square(1.0, 1.0, 4.0, 59),
        ground_square(2.0, 2.0, 2.0, 224),
        ground_square(5.0, 1.0, 4.0, 59),
    ];
    let processed = crate::sod::decal::identify_coplanar_decals(&polygons, 0.001, 1e-4, 1e-4);
    let heights: Vec<f32> = processed.iter().map(|p| p.vertices[0][1]).collect();
    assert_eq!(heights, [0.0, 0.001, 0.002, 0.001]);
    assert!(processed.iter().skip(1).all(|p| p.is_decal));
}

/// A line has no side, so it is never a decal, even lying on a facet.
#[test]
fn a_line_on_a_facet_is_no_decal() {
    let line = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[1.0, 0.0, 1.0], [5.0, 0.0, 1.0]],
        palette_index: 50,
        normal: [0.0; 3],
        flags: crate::contracts::shape::VERTEX_FLAG_LINE,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    let processed = crate::sod::decal::identify_coplanar_decals(
        &[ground_square(0.0, 0.0, 10.0, 162), line.clone()],
        0.001,
        1e-4,
        1e-4,
    );
    assert!(!processed[1].is_decal);
    assert_eq!(processed[1].vertices, line.vertices);
}
