//! PLAYONE's coarse ground patches and the finer ones that replace them by depth.
//!
//! `SP_GROUND` (image `0x2360`) draws its own coarse polygon when the depth word `CX` of its
//! centre exceeds its `splitdist`, and its finer patches otherwise
//! (`research/playone-exe/world-scene.md` section 2). This module finds each such group in
//! `MAP.BIN` and the scenery tree, and gives every member the visibility gate that picks its
//! side per frame.

use std::collections::HashMap;

use crate::anchor::AnchorPoint;
use crate::contracts::VisibilityCondition;

use super::map_bin::{MapArea, MapLink};
use super::scenery::GroundNode;

/// How far a node's centre may lie from its coarse polygon's mean corner, per axis in raw
/// island units. The compiled centre is that mean in integers: the corpus tree's twelve
/// differ from it by at most one.
const CENTRE_TOLERANCE: u32 = 2;

/// The most finer patches a group may hold; the corpus's most is four.
const MAX_FINE_PATCHES: usize = 64;

/// One verified group: the indices into the `MAP.BIN` areas of a coarse patch and of the finer
/// patches that replace it, with the centre and split distance of its `SP_GROUND` node.
#[derive(Debug, PartialEq, Eq)]
pub(super) struct SplitGroup {
    pub(super) coarse: usize,
    pub(super) fine: Vec<usize>,
    /// The node's centre in raw island units.
    pub(super) centre: [i32; 3],
    pub(super) splitdist: i32,
}

/// The groups of `areas` (with their `links`, parallel) that `nodes` verify.
///
/// A group is kept only when its coarse patch's link record, every finer patch's, and exactly
/// one `SP_GROUND` node agree: the node's split distance is the record's `c >> 1`, its chain
/// holds one `SP_GLEAF` per finer patch, and its centre is the coarse polygon's mean corner.
/// Any other group, and any group whose node another group also claims, is left out, and its
/// patches draw as before.
pub(super) fn verified_groups(
    anchors: &[AnchorPoint],
    areas: &[MapArea],
    links: &[MapLink],
    nodes: &[GroundNode],
) -> Vec<SplitGroup> {
    let by_record: HashMap<usize, usize> = links
        .iter()
        .enumerate()
        .map(|(area, link)| (link.record, area))
        .collect();
    let mut claims: HashMap<usize, usize> = HashMap::new();
    let mut groups = Vec::new();
    for (coarse, link) in links.iter().enumerate() {
        let Some(first) = link.first_child else {
            continue;
        };
        let Some(fine) = fine_patches(links, &by_record, coarse, first) else {
            continue;
        };
        let Some(mean) = areas.get(coarse).and_then(|a| mean_corner(anchors, a)) else {
            continue;
        };
        let splitdist = i32::from(link.split_distance_x2 >> 1);
        let mut matching = nodes.iter().filter(|node| {
            node.splitdist == splitdist
                && node.all_leaves
                && node.patches == fine.len()
                && node
                    .centre
                    .iter()
                    .zip(mean)
                    .all(|(&c, m)| c.abs_diff(m) <= CENTRE_TOLERANCE)
        });
        let (Some(node), None) = (matching.next(), matching.next()) else {
            continue;
        };
        let claimed = claims.entry(node.node).or_default();
        *claimed = usize::saturating_add(*claimed, 1);
        groups.push((
            node.node,
            SplitGroup {
                coarse,
                fine,
                centre: node.centre,
                splitdist,
            },
        ));
    }
    groups
        .into_iter()
        .filter(|(node, _)| claims.get(node) == Some(&1))
        .map(|(_, group)| group)
        .collect()
}

/// The area indices of the finer patches listed from record `first`, or `None` when the list
/// is not a clean one: a record outside `areas`, one that names another parent, one with
/// children of its own, a repeat, no patch, or too long a list.
fn fine_patches(
    links: &[MapLink],
    by_record: &HashMap<usize, usize>,
    coarse: usize,
    first: usize,
) -> Option<Vec<usize>> {
    let parent = links.get(coarse)?.record;
    let mut fine = Vec::new();
    let mut at = Some(first);
    while let Some(record) = at {
        let area = *by_record.get(&record)?;
        let link = links.get(area)?;
        if link.parent != Some(parent)
            || link.first_child.is_some()
            || fine.contains(&area)
            || fine.len() >= MAX_FINE_PATCHES
        {
            return None;
        }
        fine.push(area);
        at = link.next;
    }
    (!fine.is_empty()).then_some(fine)
}

/// The mean of `area`'s corners in raw island units, a sentinel height counting as 0.
fn mean_corner(anchors: &[AnchorPoint], area: &MapArea) -> Option<[i32; 3]> {
    let count = i32::try_from(area.verts.len()).ok()?;
    let mut sum = [0i32; 3];
    for &vertex in &area.verts {
        let point = anchors.get(vertex)?;
        let y = if point.is_valid() { point.y } else { 0 };
        for (total, value) in sum.iter_mut().zip([point.x, y, point.z]) {
            *total = total.saturating_add(i32::from(value));
        }
    }
    let [x, y, z] = sum;
    Some([
        x.checked_div(count)?,
        y.checked_div(count)?,
        z.checked_div(count)?,
    ])
}

/// The gate of each of `count` areas: the coarse patch of a group draws while the camera is
/// beyond its split distance, its finer patches otherwise, and every other area is ungated.
///
/// The test is the `SP_1NODE` branch gate with an extent that leaves its threshold at
/// `splitdist` itself: `half = ext >> 1` exceeds `splitdist`, so the threshold is
/// `splitdist` and the subtree holds while the depth word `CX` is at most it, which is the
/// ground handler's test (image `0x239C`), in the same depth units and with no detail
/// scaling.
pub(super) fn gates(
    count: usize,
    groups: &[SplitGroup],
    base_y: f32,
) -> Vec<Option<VisibilityCondition>> {
    let mut gates = vec![None; count];
    for group in groups {
        let [x, y, z] = group.centre;
        let gate = |near| VisibilityCondition::LodBranch {
            point: [-(x as f32), -(y as f32) + base_y, z as f32],
            ext: group.splitdist.saturating_add(1).saturating_mul(2),
            splitdist: group.splitdist,
            near,
        };
        if let Some(slot) = gates.get_mut(group.coarse) {
            *slot = Some(gate(false));
        }
        for &fine in &group.fine {
            if let Some(slot) = gates.get_mut(fine) {
                *slot = Some(gate(true));
            }
        }
    }
    gates
}

#[cfg(test)]
mod tests {
    use super::*;

    fn link(record: usize, parent: Option<usize>, first_child: Option<usize>) -> MapLink {
        MapLink {
            record,
            next: None,
            first_child,
            parent,
            split_distance_x2: 400,
        }
    }

    /// Two coarse patches over one quad each, and one fine patch apiece.
    fn two_groups() -> (Vec<AnchorPoint>, Vec<MapArea>, Vec<MapLink>) {
        let anchors = [(0, 0), (10, 0), (10, 10), (0, 10)]
            .map(|(x, z)| AnchorPoint { x, y: 0, z })
            .to_vec();
        let area = |verts: &[usize]| MapArea {
            color: 1,
            verts: verts.to_vec(),
        };
        let areas = vec![
            area(&[0, 1, 2, 3]),
            area(&[0, 1, 2]),
            area(&[0, 1, 2, 3]),
            area(&[0, 2, 3]),
        ];
        let links = vec![
            link(0, None, Some(1)),
            link(1, Some(0), None),
            link(2, None, Some(3)),
            link(3, Some(2), None),
        ];
        (anchors, areas, links)
    }

    fn node(at: usize) -> GroundNode {
        GroundNode {
            node: at,
            splitdist: 200,
            centre: [5, 0, 5],
            patches: 1,
            all_leaves: true,
        }
    }

    #[test]
    fn a_node_one_group_alone_matches_verifies_it() {
        let (anchors, areas, mut links) = two_groups();
        // Only the first group stays a group.
        links[2].first_child = None;
        links[3].parent = None;
        let groups = verified_groups(&anchors, &areas, &links, &[node(7)]);
        assert_eq!(groups.len(), 1);
        assert_eq!((groups[0].coarse, groups[0].fine.as_slice()), (0, &[1][..]));
        assert_eq!((groups[0].centre, groups[0].splitdist), ([5, 0, 5], 200));
    }

    #[test]
    fn a_node_two_groups_match_verifies_neither() {
        let (anchors, areas, links) = two_groups();
        assert!(verified_groups(&anchors, &areas, &links, &[node(7)]).is_empty());
        // A second node of the same centre leaves each group two candidates.
        assert!(verified_groups(&anchors, &areas, &links, &[node(7), node(9)]).is_empty());
    }

    #[test]
    fn the_gates_pick_a_side_per_patch_and_leave_the_rest() {
        let group = SplitGroup {
            coarse: 1,
            fine: vec![2],
            centre: [5, -3, 7],
            splitdist: 200,
        };
        let gates = gates(4, &[group], 0.0);
        assert_eq!(gates[0], None);
        assert_eq!(gates[3], None);
        let near = |g: Option<VisibilityCondition>| match g {
            Some(VisibilityCondition::LodBranch {
                point,
                ext,
                splitdist,
                near,
            }) => {
                assert_eq!((point, splitdist), ([-5.0, 3.0, 7.0], 200));
                assert!(ext >> 1 > splitdist, "the threshold is splitdist itself");
                near
            }
            other => panic!("not a LodBranch: {other:?}"),
        };
        assert!(!near(gates[1]));
        assert!(near(gates[2]));
    }
}
