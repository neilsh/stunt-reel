//! GLB container and JSON document packing (Khronos glTF 2.0 binary layout).
//!
//! Layout: 12-byte header (`glTF`, version 2, total length), a JSON chunk padded with
//! spaces to 4 bytes, and a BIN chunk padded with zeros to 4 bytes. `BufferViews` start on
//! 4-byte boundaries and carry `ARRAY_BUFFER` / `ELEMENT_ARRAY_BUFFER` targets.

use serde_json::{Map, Value, json};

use crate::GltfError;

const MAGIC: &[u8; 4] = b"glTF";
const CHUNK_JSON: u32 = 0x4E4F_534A;
const CHUNK_BIN: u32 = 0x004E_4942;

/// `ARRAY_BUFFER` bufferView target.
pub(crate) const TARGET_ARRAY_BUFFER: u32 = 34962;
/// `ELEMENT_ARRAY_BUFFER` bufferView target.
pub(crate) const TARGET_ELEMENT_ARRAY_BUFFER: u32 = 34963;
/// Accessor component type `UNSIGNED_INT`.
pub(crate) const COMPONENT_UNSIGNED_INT: u32 = 5125;
/// Accessor component type `FLOAT`.
pub(crate) const COMPONENT_FLOAT: u32 = 5126;

/// Generator string written to `asset.generator`.
const GENERATOR: &str = "stunt-reel stunt-gltf";

/// Converts an `f32` to a JSON number that reads back as the same `f32`.
///
/// The shortest decimal that round-trips the `f32` is used, so `0.1f32` is written as
/// `0.1`. Non-finite values (not representable in JSON) become `0`.
pub(crate) fn num(x: f32) -> Value {
    if !x.is_finite() {
        return json!(0.0);
    }
    let text = format!("{x}");
    text.parse::<f64>()
        .ok()
        .and_then(serde_json::Number::from_f64)
        .map_or_else(|| json!(0.0), Value::Number)
}

/// JSON array of `f32` numbers.
pub(crate) fn num_array(values: &[f32]) -> Value {
    Value::Array(values.iter().copied().map(num).collect())
}

/// Parameters of one glTF accessor.
pub(crate) struct AccessorSpec<'a> {
    pub(crate) view: usize,
    pub(crate) byte_offset: usize,
    pub(crate) component_type: u32,
    pub(crate) count: usize,
    pub(crate) kind: &'a str,
    pub(crate) bounds: Option<(Vec<f32>, Vec<f32>)>,
}

/// Accumulates the BIN payload and the JSON arrays of one glTF document.
#[derive(Debug, Default)]
pub(crate) struct GlbBuilder {
    bin: Vec<u8>,
    views: Vec<Value>,
    accessors: Vec<Value>,
    pub(crate) meshes: Vec<Value>,
    pub(crate) nodes: Vec<Value>,
    pub(crate) cameras: Vec<Value>,
}

impl GlbBuilder {
    pub(crate) fn new() -> Self {
        Self::default()
    }

    /// Appends `data` at the next 4-byte boundary and returns its bufferView index.
    pub(crate) fn add_view(&mut self, data: &[u8], target: u32) -> usize {
        self.bin.resize(self.bin.len().next_multiple_of(4), 0);
        let offset = self.bin.len();
        self.bin.extend_from_slice(data);
        self.views.push(json!({
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": data.len(),
            "target": target,
        }));
        self.views.len() - 1
    }

    /// Adds an accessor and returns its index.
    pub(crate) fn add_accessor(&mut self, spec: &AccessorSpec<'_>) -> usize {
        let mut accessor = json!({
            "bufferView": spec.view,
            "byteOffset": spec.byte_offset,
            "componentType": spec.component_type,
            "count": spec.count,
            "type": spec.kind,
        });
        if let Some((min, max)) = &spec.bounds {
            accessor["min"] = num_array(min);
            accessor["max"] = num_array(max);
        }
        self.accessors.push(accessor);
        self.accessors.len() - 1
    }

    /// Serializes the document with `scene_roots` as the default scene's nodes.
    pub(crate) fn finish(mut self, scene_roots: &[usize]) -> Result<Vec<u8>, GltfError> {
        self.bin.resize(self.bin.len().next_multiple_of(4), 0);

        let mut root = Map::new();
        root.insert(
            "asset".into(),
            json!({ "version": "2.0", "generator": GENERATOR }),
        );
        root.insert("extensionsUsed".into(), json!(["KHR_materials_unlit"]));
        root.insert("scene".into(), json!(0));
        root.insert(
            "scenes".into(),
            json!([{ "name": "StuntReel", "nodes": scene_roots }]),
        );
        root.insert("nodes".into(), Value::Array(self.nodes));
        root.insert(
            "materials".into(),
            json!([{
                "name": "StuntReel_Mode13h_Unlit",
                "doubleSided": true,
                "pbrMetallicRoughness": { "metallicFactor": 0.0, "roughnessFactor": 1.0 },
                "extensions": { "KHR_materials_unlit": {} },
            }]),
        );
        if !self.meshes.is_empty() {
            root.insert("meshes".into(), Value::Array(self.meshes));
        }
        if !self.cameras.is_empty() {
            root.insert("cameras".into(), Value::Array(self.cameras));
        }
        if !self.bin.is_empty() {
            root.insert("buffers".into(), json!([{ "byteLength": self.bin.len() }]));
            root.insert("bufferViews".into(), Value::Array(self.views));
            root.insert("accessors".into(), Value::Array(self.accessors));
        }

        let mut json_bytes = serde_json::to_vec(&Value::Object(root))
            .map_err(|_| GltfError::InvalidContainer("JSON serialization failed"))?;
        json_bytes.resize(json_bytes.len().next_multiple_of(4), b' ');

        let bin_chunk = if self.bin.is_empty() {
            0
        } else {
            8 + self.bin.len()
        };
        let total = 12 + 8 + json_bytes.len() + bin_chunk;
        let total32 = u32::try_from(total).map_err(|_| GltfError::TooLarge)?;

        let mut out = Vec::with_capacity(total);
        out.extend_from_slice(MAGIC);
        out.extend_from_slice(&2u32.to_le_bytes());
        out.extend_from_slice(&total32.to_le_bytes());
        out.extend_from_slice(&(json_bytes.len() as u32).to_le_bytes());
        out.extend_from_slice(&CHUNK_JSON.to_le_bytes());
        out.extend_from_slice(&json_bytes);
        if !self.bin.is_empty() {
            out.extend_from_slice(&(self.bin.len() as u32).to_le_bytes());
            out.extend_from_slice(&CHUNK_BIN.to_le_bytes());
            out.extend_from_slice(&self.bin);
        }
        Ok(out)
    }
}

/// Counts read back from a `.glb`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct GlbSummary {
    /// Entries in the glTF `nodes` array.
    pub nodes: usize,
    /// Entries in the glTF `meshes` array.
    pub meshes: usize,
    /// Total container size in bytes.
    pub bytes: usize,
}

/// Reads the node and mesh counts of `.glb` bytes produced by this crate.
pub fn summarize(glb: &[u8]) -> Result<GlbSummary, GltfError> {
    let word = |at: usize| -> Result<u32, GltfError> {
        glb.get(at..at + 4)
            .map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
            .ok_or(GltfError::InvalidContainer("truncated header"))
    };
    if glb.get(..4) != Some(MAGIC.as_slice()) {
        return Err(GltfError::InvalidContainer("bad magic"));
    }
    if word(4)? != 2 || word(8)? as usize != glb.len() {
        return Err(GltfError::InvalidContainer("bad version or length"));
    }
    if word(16)? != CHUNK_JSON {
        return Err(GltfError::InvalidContainer("first chunk is not JSON"));
    }
    let len = word(12)? as usize;
    let json_bytes = glb
        .get(20..20 + len)
        .ok_or(GltfError::InvalidContainer("JSON chunk truncated"))?;
    let doc: Value = serde_json::from_slice(json_bytes)
        .map_err(|_| GltfError::InvalidContainer("JSON chunk does not parse"))?;
    let count = |key: &str| doc.get(key).and_then(Value::as_array).map_or(0, Vec::len);
    Ok(GlbSummary {
        nodes: count("nodes"),
        meshes: count("meshes"),
        bytes: glb.len(),
    })
}
