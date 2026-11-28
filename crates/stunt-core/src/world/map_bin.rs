//! `MAP.BIN` terrain patch records and the anchor-indexed polygons they form.

/// Polygonal terrain patch from `MAP.BIN`.
#[derive(Clone, Debug)]
pub(super) struct MapArea {
    pub(super) color: u8,
    pub(super) verts: Vec<usize>,
}

/// `MAP.BIN` records `PLAYONE` never draws: eight sand patches with no polygon in its scene
/// tree, its image, any game file or any `OP_TAP` operand
/// (`research/playone-exe/world-scene.md` section 2.1). Ground leaf `0x00DA` (`MAP.BIN`
/// record 7, flat at height 0) lies under 54 and 55, the two whose anchors are all valid and
/// so were drawn; the other six already fail [`patch_corners`].
const PATCHES_PLAYONE_NEVER_DRAWS: [usize; 8] = [52, 53, 54, 55, 62, 63, 64, 65];

/// Bytes of `MAP.BIN`'s list head, before the first record (`research/formats/auxiliary/map.md`
/// section 2.3).
const MAP_HEAD: usize = 2;
/// Vertex slots in a `MAP.BIN` record.
const MAP_SLOTS: usize = 8;

/// The links of one `MAP.BIN` record, kept beside its [`MapArea`] (`research/formats/auxiliary/map.md`
/// section 3.1).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct MapLink {
    /// The record's index in the file.
    pub(super) record: usize,
    /// The next patch in the same list.
    pub(super) next: Option<usize>,
    /// The first of the finer patches that replace this one, for a coarse patch.
    pub(super) first_child: Option<usize>,
    /// The coarse patch whose child list holds this one.
    pub(super) parent: Option<usize>,
    /// Twice the `SP_GROUND` split distance (`c`).
    pub(super) split_distance_x2: i16,
}

/// A link word, `30 * index` on disk and negative for none, as a record index.
fn link_index(word: i16) -> Option<usize> {
    usize::try_from(word).ok().map(|offset| offset / 30)
}

/// Parses the 30-byte polygon patch records that follow `MAP.BIN`'s 2-byte list head, leaving
/// out the records in [`PATCHES_PLAYONE_NEVER_DRAWS`].
#[cfg(test)]
pub(super) fn parse_map_bin(data: &[u8], anchor_count: usize) -> Vec<MapArea> {
    parse_map_bin_linked(data, anchor_count).0
}

/// [`parse_map_bin`] with each kept record's [`MapLink`], parallel to the areas.
pub(super) fn parse_map_bin_linked(
    data: &[u8],
    anchor_count: usize,
) -> (Vec<MapArea>, Vec<MapLink>) {
    let (records, _partial) = data.get(MAP_HEAD..).unwrap_or_default().as_chunks::<30>();
    let mut areas = Vec::new();
    let mut links = Vec::new();
    for (index, record) in records.iter().enumerate() {
        if PATCHES_PLAYONE_NEVER_DRAWS.contains(&index) {
            continue;
        }
        // Constant indices into the fixed 30-byte record, so none can fall outside it.
        if record[0] == 0 {
            continue; // a free record
        }
        let color = record[10];
        // A negative count reads every slot, as the sign-extending cast it replaces did.
        let num_verts = i16::from_le_bytes([record[12], record[13]]);
        let nverts = usize::try_from(num_verts).map_or(MAP_SLOTS, |n| n.min(MAP_SLOTS));
        if nverts < 3 {
            continue;
        }
        // Bytes 14..30 hold eight little-endian anchor indices.
        let (vert_words, _) = record.as_chunks::<2>();
        let verts: Vec<usize> = vert_words
            .iter()
            .skip(7)
            .take(nverts)
            .map(|&word| usize::from(u16::from_le_bytes(word)))
            .collect();
        if verts.iter().all(|&v_idx| v_idx < anchor_count) {
            let &[_, next, child, split, parent, ..] = vert_words else {
                continue;
            };
            let word = i16::from_le_bytes;
            areas.push(MapArea { color, verts });
            links.push(MapLink {
                record: index,
                next: link_index(word(next)),
                first_child: link_index(word(child)),
                parent: link_index(word(parent)),
                split_distance_x2: word(split),
            });
        }
    }
    (areas, links)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::anchor::parse_anchor_table;

    /// One 30-byte `MAP.BIN` record: `flags` (in-use byte, block byte), `color`, and `verts`.
    fn map_record(flags: u16, color: u8, verts: &[u16]) -> Vec<u8> {
        let mut rec = Vec::with_capacity(30);
        rec.extend(flags.to_le_bytes());
        rec.extend([-1i16, -1, 100, -1].iter().flat_map(|w| w.to_le_bytes()));
        rec.extend([color, 0]);
        rec.extend(i16::try_from(verts.len()).unwrap().to_le_bytes());
        rec.extend(verts.iter().flat_map(|v| v.to_le_bytes()));
        rec.resize(30, 0);
        rec
    }

    /// A `MAP.BIN` of `records` behind a list head naming the first.
    fn map_bin(records: &[Vec<u8>]) -> Vec<u8> {
        let mut data = 0i16.to_le_bytes().to_vec();
        data.extend(records.concat());
        data
    }

    #[test]
    fn test_parse_map_bin_filtering() {
        let data = map_bin(&[
            map_record(0x01FF, 150, &[0, 1, 2, 3]), // in use: a quad
            map_record(0x0100, 160, &[0, 1, 2]),    // free: in-use byte 0
        ]);
        let areas = parse_map_bin(&data, 10);
        assert_eq!(areas.len(), 1);
        assert_eq!(areas[0].color, 150);
        assert_eq!(areas[0].verts, vec![0, 1, 2, 3]);

        // If anchor_count is too low, the polygon is rejected
        let areas_low = parse_map_bin(&data, 3);
        assert_eq!(areas_low.len(), 0);
    }

    #[test]
    fn a_record_holds_eight_vertex_slots_after_the_list_head() {
        // MAP.BIN patch 131 has 8 vertices, all in its own record once the 2-byte list head
        // is accounted for (research/formats/auxiliary/map.md section 2).
        let data = map_bin(&[
            map_record(0x01FF, 14, &[0, 1, 2, 3, 4, 5, 6, 7]),
            map_record(0x01FF, 15, &[7, 8, 9]),
        ]);
        let areas = parse_map_bin(&data, 10);
        assert_eq!(areas.len(), 2);
        assert_eq!(areas[0].verts, vec![0, 1, 2, 3, 4, 5, 6, 7]);
        assert_eq!(areas[1].verts, vec![7, 8, 9]);
    }

    /// `parse_map_bin` leaves out the `MAP.BIN` records in `PATCHES_PLAYONE_NEVER_DRAWS` and
    /// keeps every record around and after them.
    #[test]
    fn the_sand_patches_playone_never_draws_are_left_out() {
        // 70 active triangles, each coloured by its record index; records 52-55 and 62-65 are
        // the patches with no leaf in PLAYONE's scene tree (world-scene.md section 2.1). The
        // records past 65 show the skip does not end the parse.
        let records: Vec<Vec<u8>> = (0..70u8)
            .map(|index| map_record(0x00FF, index, &[0, 1, 2]))
            .collect();
        let colours: Vec<u8> = parse_map_bin(&map_bin(&records), 3)
            .iter()
            .map(|a| a.color)
            .collect();
        let expected: Vec<u8> = (0..70)
            .filter(|i| !matches!(i, 52..=55 | 62..=65))
            .collect();
        assert_eq!(colours, expected);
    }

    #[test]
    fn truncated_anchor_and_map_inputs_stop_without_panicking() {
        // A trailing partial record is ignored rather than read past the end.
        let mut anchors = vec![0u8; 28 + 10];
        anchors[0..2].copy_from_slice(&7i16.to_le_bytes());
        assert_eq!(parse_anchor_table(&anchors).len(), 1);

        // The partial second record claims a patch too, but only the whole first one counts;
        // a file shorter than its list head has no records.
        let whole = map_bin(&[
            map_record(0x01FF, 1, &[0, 1, 2]),
            map_record(0x01FF, 1, &[0, 1, 2]),
        ]);
        assert_eq!(parse_map_bin(&whole[..whole.len() - 10], 10).len(), 1);
        assert!(parse_map_bin(&whole[..1], 10).is_empty());
    }
}
