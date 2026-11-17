use super::*;

#[test]
fn decode_record_keeps_stream_provenance() {
    let header = SodHeader {
        bounding_size: 100,
        ground_y_offset: -4,
        scale_index: 1,
        header_flags: 0,
        scale_factor: 0.5,
        collision_meta: 7,
    };
    let stop = SodStop {
        offset: 42,
        opcode: 0x0FFF,
        reason: SodStopReason::UnknownOpcode,
    };
    let record = DecodeRecord {
        header,
        stop: Some(stop),
        stepped_over: vec![stop],
        returned_at: Some(52),
        bank_operands: vec![0x14, 0x18],
    };
    let mut ir = SodModelIr::new("DECODED");
    ir.set_decode(record);
    let attached = ir.decode().expect("decoded shape keeps its record");
    assert_eq!(attached.header, header);
    assert_eq!(attached.stop, Some(stop));
    assert_eq!(attached.stepped_over, vec![stop]);
    assert_eq!(attached.returned_at, Some(52));
    assert_eq!(attached.bank_operands, [0x14, 0x18]);
}
