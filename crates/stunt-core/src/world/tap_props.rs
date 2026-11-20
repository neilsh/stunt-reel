//! `OP_TAP` placement decoding: props whose tapped anchors depend on where they stand.

use std::collections::HashMap;

use crate::anchor::AnchorPoint;
use crate::contracts::SodModelIr;
use crate::sod::{DecodeMode, OP_TAP, SodError, SodStop, decode_sod_lit, trace_sod};

use super::assemble::WorldInputs;
use super::scenery::Placement;

/// Why a placed `OP_TAP` shape was drawn partly or not at all.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TapFailureReason {
    /// An anchor less the placement does not fit a 16-bit word; the placement is not drawn.
    AnchorOutOfRange {
        /// Index of the first anchor that overflowed.
        anchor: usize,
    },
    /// The stream failed to decode against the shifted table; the placement is not drawn.
    Decode(SodError),
    /// The decode stopped early; the part decoded before the stop is drawn.
    Stopped(SodStop),
}

/// A placed `OP_TAP` shape that [`crate::world::build_world`] drew partly or not at all.
#[derive(Clone, Debug, PartialEq)]
pub struct TapFailure {
    /// The shape's resource ID.
    pub shape_id: u16,
    /// Its placement in `[I1]` metres.
    pub position: [f32; 3],
    /// What went wrong.
    pub reason: TapFailureReason,
}

/// Decodes every placement of an `OP_TAP` shape against the anchor table less that
/// placement, keyed by its index in `instances`.
///
/// `PLAYONE` (image `0xAD88`) loads a tapped point as the anchor less the shape's origin, so a
/// point a stream builds from that origin, such as `0x0403`'s `CLRV; SUBV 0`, lands where
/// the tree puts it (`research/playone-exe/sod-vm.md` section 4). No rotation applies: a
/// scenery prop that does not face the view is drawn through the matrix the anchors are turned by. Placements are whole tree
/// units, so the shifted table is exact. A placement for which an anchor the stream taps
/// overflows, or whose stream fails, is dropped and reported; one whose decode stops early is
/// drawn and reported. An anchor the stream never taps may overflow: `PLAYONE` subtracts the
/// origin from tapped anchors only.
pub(super) fn anchored_models(
    inputs: &WorldInputs<'_>,
    instances: &[Placement],
) -> (HashMap<usize, Option<SodModelIr>>, Vec<TapFailure>) {
    let mut own = HashMap::new();
    let mut failures = Vec::new();
    for (
        index,
        &Placement {
            shape: shape_id,
            position,
            ..
        },
    ) in instances.iter().enumerate()
    {
        let Some(data) = inputs.anchored_shapes.get(&shape_id) else {
            continue;
        };
        let (table, overflows) = shifted_anchors(inputs.anchors, position);
        let tapped_overflow = (!overflows.is_empty())
            .then(|| {
                trace_sod(data, Some(&table), inputs.light)
                    .steps
                    .iter()
                    .filter(|step| step.opcode == OP_TAP)
                    .flat_map(|step| step.operands.iter().skip(2))
                    .map(|&offset| usize::from(offset) / 28)
                    .find(|anchor| overflows.contains(anchor))
            })
            .flatten();
        let (model, reason) = if let Some(anchor) = tapped_overflow {
            (None, Some(TapFailureReason::AnchorOutOfRange { anchor }))
        } else {
            let name = format!("MODEL_{shape_id:04X}.SOD");
            match decode_sod_lit(data, &name, Some(&table), DecodeMode::Lenient, inputs.light) {
                Ok(ir) => {
                    let stop = ir.decode().and_then(|record| record.stop);
                    (Some(ir), stop.map(TapFailureReason::Stopped))
                }
                Err(error) => (None, Some(TapFailureReason::Decode(error))),
            }
        };
        if let Some(reason) = reason {
            failures.push(TapFailure {
                shape_id,
                position,
                reason,
            });
        }
        own.insert(index, model);
    }
    (own, failures)
}

/// The anchor table less an `[I1]` placement (`-x, -y, z` of whole raw units), and the
/// indices, in order, of the anchors whose shifted coordinates leave `i16`; those keep their
/// unshifted record.
///
/// A sentinel elevation is kept, so the record stays a sentinel.
#[expect(
    clippy::cast_possible_truncation,
    reason = "placements are sums of i16 tree offsets, whole and far inside i32"
)]
fn shifted_anchors(anchors: &[AnchorPoint], position: [f32; 3]) -> (Vec<AnchorPoint>, Vec<usize>) {
    let by = [-position[0] as i32, -position[1] as i32, position[2] as i32];
    let shift = |value: i16, by: i32| i16::try_from(i32::from(value).checked_sub(by)?).ok();
    let mut overflows = Vec::new();
    let table = anchors
        .iter()
        .enumerate()
        .map(|(index, a)| {
            let y = if a.is_valid() {
                shift(a.y, by[1])
            } else {
                Some(a.y)
            };
            if let (Some(x), Some(y), Some(z)) = (shift(a.x, by[0]), y, shift(a.z, by[2])) {
                AnchorPoint { x, y, z }
            } else {
                overflows.push(index);
                *a
            }
        })
        .collect();
    (table, overflows)
}

#[cfg(test)]
mod tests {
    use super::super::test_support::tap_stream;
    use super::*;
    use crate::sod::ShadeLight;

    /// One placement's distinct corners in world `[I1]` metres.
    type Corners = Vec<[f32; 3]>;

    /// The distinct corners of each placement's own model, in world `[I1]` metres, and the
    /// failures `anchored_models` reported.
    fn placed_corners(
        anchors: &[AnchorPoint],
        shape: Vec<u8>,
        instances: &[(u16, [f32; 3])],
    ) -> (Vec<Option<Corners>>, Vec<TapFailure>) {
        let streams = HashMap::from([(0x0400, shape)]);
        let inputs = WorldInputs {
            anchors,
            map: None,
            scenery: None,
            view_eyes: &[],
            max_zoom: 1.0,
            max_lod_shift: 1,
            min_corner_depth: 0.804,
            anchored_shapes: &streams,
            light: ShadeLight::default(),
        };
        let placements: Vec<Placement> = instances
            .iter()
            .map(|&(shape, position)| Placement::bare(shape, position, 0))
            .collect();
        let (own, failures) = anchored_models(&inputs, &placements);
        let corners = instances
            .iter()
            .enumerate()
            .map(|(index, &(_, pos))| {
                let model = own
                    .get(&index)
                    .expect("every placement has an entry")
                    .as_ref()?;
                let mut corners: Vec<[f32; 3]> = model
                    .vertices
                    .iter()
                    .map(|v| {
                        [
                            v.position[0] + pos[0],
                            v.position[1] + pos[1],
                            v.position[2] + pos[2],
                        ]
                    })
                    .collect();
                corners.sort_by(|a, b| a.partial_cmp(b).expect("finite"));
                corners.dedup();
                Some(corners)
            })
            .collect();
        (corners, failures)
    }

    /// `CTRY.ALL` shape `0x0403` (scale 6): its third point is `-reg0`, the first anchor
    /// mirrored through the shape's origin, so it lands under the ridge anchor only when
    /// the anchors are loaded less the placement.
    #[test]
    fn test_anchored_models_load_tapped_points_less_the_placement() {
        use crate::sod::{OP_CLRV, OP_PUTV, OP_SUBV};
        let anchors = [
            AnchorPoint {
                x: 1120,
                y: 0,
                z: 3872,
            },
            AnchorPoint {
                x: 1538,
                y: -196,
                z: 3906,
            },
        ];
        let shape = tap_stream(0, 6, &[OP_CLRV, OP_SUBV, 0, OP_PUTV, 0x18]);
        // Placed at raw (1329, 0, 3889), the middle of the two anchors in plan.
        let (corners, failures) =
            placed_corners(&anchors, shape, &[(0x0400, [-1329.0, 0.0, 3889.0])]);
        assert!(failures.is_empty());
        assert_eq!(
            corners,
            vec![Some(vec![
                [-1538.0, 0.0, 3906.0],
                [-1538.0, 196.0, 3906.0],
                [-1120.0, 0.0, 3872.0],
            ])]
        );
    }

    /// With a header lift the tapped points still land on their anchors, the lift applied
    /// once, while a point at the origin (`CLRV; PUTV`) sits the lift above the placement.
    /// Two placements of one shape each get their own decode.
    #[test]
    fn test_anchored_models_apply_the_lift_once_per_placement() {
        use crate::sod::{OP_CLRV, OP_PUTV};
        let anchors = [
            AnchorPoint {
                x: 1835,
                y: -82,
                z: 2301,
            },
            AnchorPoint {
                x: 2047,
                y: 0,
                z: 2305,
            },
        ];
        // Scale 7 (128 units per metre), lift 256 units: 2 m.
        let shape = tap_stream(256, 7, &[OP_CLRV, OP_PUTV, 0x18]);
        let first = [-1941.0, 41.0, 2303.0];
        let second = [-1000.0, 0.0, 1000.0];
        let (corners, failures) =
            placed_corners(&anchors, shape, &[(0x0400, first), (0x0400, second)]);
        assert!(failures.is_empty());
        let with_origin = |origin: [f32; 3]| {
            let mut c = vec![[-1835.0, 82.0, 2301.0], [-2047.0, 0.0, 2305.0], origin];
            c.sort_by(|a, b| a.partial_cmp(b).expect("finite"));
            Some(c)
        };
        assert_eq!(
            corners,
            vec![
                with_origin([-1941.0, 43.0, 2303.0]),
                with_origin([-1000.0, 2.0, 1000.0]),
            ]
        );
    }

    /// A placement whose anchors less it leave `i16` is reported and not drawn.
    #[test]
    fn test_anchored_models_report_an_anchor_out_of_range() {
        use crate::sod::{OP_CLRV, OP_PUTV};
        let anchors = [
            AnchorPoint { x: 0, y: 0, z: 0 },
            AnchorPoint {
                x: -20_000,
                y: 0,
                z: 0,
            },
        ];
        let shape = tap_stream(0, 6, &[OP_CLRV, OP_PUTV, 0x18]);
        // Raw x 20,000: anchor 1 less it is -40,000.
        let pos = [-20_000.0, 0.0, 0.0];
        let (corners, failures) = placed_corners(&anchors, shape, &[(0x0400, pos)]);
        assert_eq!(corners, vec![None]);
        assert_eq!(
            failures,
            vec![TapFailure {
                shape_id: 0x0400,
                position: pos,
                reason: TapFailureReason::AnchorOutOfRange { anchor: 1 },
            }]
        );
    }

    /// An anchor the stream never taps may leave `i16` once less the placement: the
    /// placement is drawn, as `PLAYONE` subtracts the origin from tapped anchors only.
    #[test]
    fn test_anchored_models_ignore_an_untapped_anchor_out_of_range() {
        use crate::sod::{OP_CLRV, OP_PUTV};
        let anchors = [
            AnchorPoint { x: 0, y: 0, z: 0 },
            AnchorPoint { x: 100, y: 0, z: 0 },
            AnchorPoint {
                x: -20_000,
                y: 0,
                z: 0,
            },
        ];
        let shape = tap_stream(0, 6, &[OP_CLRV, OP_PUTV, 0x18]);
        // Raw x 20,000: untapped anchor 2 less it is -40,000.
        let pos = [-20_000.0, 0.0, 0.0];
        let (corners, failures) = placed_corners(&anchors, shape, &[(0x0400, pos)]);
        assert!(failures.is_empty(), "{failures:?}");
        assert_eq!(corners.len(), 1);
        assert!(corners[0].is_some());
    }
}
