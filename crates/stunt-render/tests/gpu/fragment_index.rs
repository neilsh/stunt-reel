//! Execute the production palette-index function with exact IEEE 754 inputs.

use crate::common;
use wgpu::util::DeviceExt as _;

/// Runs the actual WGSL function on `(shade bits, shade * w bits, w bits, fallback index,
/// expected index)` cases; storage inputs prevent constant folding of NaNs.
fn check_indices(cases: &[(u32, u32, u32, u32, u32)]) {
    common::assert_in_gpu_test();
    // No GL: dropping a GL instance ends its WGL thread later, outside the GPU test lock, and
    // that thread's exit deadlocks NVIDIA's driver against the next test (see `common`).
    let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
        backends: wgpu::Backends::all() - wgpu::Backends::GL,
        ..wgpu::InstanceDescriptor::new_without_display_handle()
    });
    let adapter = match pollster::block_on(instance.request_adapter(&Default::default())) {
        Ok(adapter) => adapter,
        Err(error) => {
            assert!(!common::require_gpu(), "GPU required: {error}");
            eprintln!("[test] Skipping GPU test: {error}");
            return;
        }
    };
    // The production shader enables clip distances (`vs_edge`), as the renderer's device does.
    if !adapter.features().contains(wgpu::Features::CLIP_DISTANCES) {
        assert!(
            !common::require_gpu(),
            "GPU required: the adapter has no clip distances"
        );
        eprintln!("[test] Skipping GPU test: the adapter has no clip distances");
        return;
    }
    let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
        required_features: wgpu::Features::CLIP_DISTANCES,
        ..Default::default()
    }))
    .unwrap();
    // Keep the complete production shader, adding only an entry point that supplies its input.
    // Its inputs sit beside `prop_runs`, which holds `@group(3) @binding(0)`.
    let source = format!(
        "{}\n{}",
        include_str!("../../src/shaders/mode13h.wgsl"),
        "
@group(3) @binding(1) var<storage, read> inputs: array<vec4<u32>>;
@group(3) @binding(2) var<storage, read_write> results: array<u32>;

@compute @workgroup_size(1)
fn test_fragment_index(@builtin(global_invocation_id) id: vec3<u32>) {
    var vertex: VertexOutput;
    vertex.shade = bitcast<f32>(inputs[id.x].x);
    vertex.shade_w = bitcast<f32>(inputs[id.x].y);
    vertex.w = bitcast<f32>(inputs[id.x].z);
    vertex.palette_index = inputs[id.x].w;
    results[id.x] = fragment_index(vertex);
}
"
    );
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("production fragment_index test"),
        source: wgpu::ShaderSource::Wgsl(source.into()),
    });
    let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
        label: Some("fragment_index"),
        layout: None,
        module: &shader,
        entry_point: Some("test_fragment_index"),
        compilation_options: Default::default(),
        cache: None,
    });
    let inputs: Vec<[u32; 4]> = cases
        .iter()
        .map(|&(bits, shade_w, w, index, _)| [bits, shade_w, w, index])
        .collect();
    let input = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("shade bits, shade * w bits, w bits and fallback indices"),
        contents: bytemuck::cast_slice(&inputs),
        usage: wgpu::BufferUsages::STORAGE,
    });
    let size = u64::try_from(cases.len()).unwrap() * 4;
    let output = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("computed indices"),
        size,
        usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
        mapped_at_creation: false,
    });
    let readback = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("index readback"),
        size,
        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    let bindings = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None,
        layout: &pipeline.get_bind_group_layout(3),
        entries: &[
            wgpu::BindGroupEntry {
                binding: 1,
                resource: input.as_entire_binding(),
            },
            wgpu::BindGroupEntry {
                binding: 2,
                resource: output.as_entire_binding(),
            },
        ],
    });
    let mut encoder = device.create_command_encoder(&Default::default());
    {
        let mut pass = encoder.begin_compute_pass(&Default::default());
        pass.set_pipeline(&pipeline);
        // Auto layouts include empty groups for the unused production bindings.
        for group in 0..3 {
            let empty = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: None,
                layout: &pipeline.get_bind_group_layout(group),
                entries: &[],
            });
            pass.set_bind_group(group, &empty, &[]);
        }
        pass.set_bind_group(3, &bindings, &[]);
        pass.dispatch_workgroups(u32::try_from(cases.len()).unwrap(), 1, 1);
    }
    encoder.copy_buffer_to_buffer(&output, 0, &readback, 0, size);
    queue.submit([encoder.finish()]);
    let (sender, receiver) = std::sync::mpsc::channel();
    readback
        .slice(..)
        .map_async(wgpu::MapMode::Read, move |result| {
            sender.send(result).unwrap();
        });
    device.poll(wgpu::PollType::wait_indefinitely()).unwrap();
    receiver.recv().unwrap().unwrap();
    let mapped = readback.slice(..).get_mapped_range().unwrap();
    let actual: &[u32] = bytemuck::cast_slice(&mapped);
    assert_eq!(actual.len(), cases.len(), "one result per case");
    for (&(bits, shade_w, w, fallback, expected), &actual) in cases.iter().zip(actual) {
        assert_eq!(
            actual, expected,
            "shade bits {bits:#010x}, shade * w bits {shade_w:#010x}, \
             w bits {w:#010x}, fallback {fallback}"
        );
    }
    drop(mapped);
    readback.unmap();
}

/// Both infinities, quiet/signaling NaNs, both signs, and distinct NaN payloads.
const NON_FINITE: [u32; 8] = [
    0x7f80_0000,
    0xff80_0000,
    0x7fc0_0000,
    0xffc0_0000,
    0x7f80_0001,
    0xff80_0001,
    0x7fff_ffff,
    0xffff_ffff,
];

#[test]
fn fragment_index_non_finite_shades_round_the_screen_linear_ratio() {
    common::gpu_test(|| {
        let mut cases = Vec::new();
        for bits in NON_FINITE {
            for (shade_w, w, expected) in [
                (-50.0f32, -0.5f32, 100),
                (50.0, 0.5, 100),
                (84.5, 0.5, 169),
                (-1.0, 0.5, 0),
                (19.745, 0.5, 39),
                (19.75, 0.5, 40),
                (127.25, 0.5, 255),
                (128.0, 0.5, 255),
                (-2.0, -2.0, 1),
            ] {
                cases.push((bits, shade_w.to_bits(), w.to_bits(), 123, expected));
            }
        }
        check_indices(&cases);
    });
}

#[test]
fn fragment_index_non_finite_ratios_use_the_flat_palette_index() {
    common::gpu_test(|| {
        let mut cases = Vec::new();
        for bits in NON_FINITE {
            for (shade_w, w) in [
                (f32::NAN, 1.0),
                (1.0, 0.0),
                (-1.0, 0.0),
                (0.0, 0.0),
                (f32::INFINITY, f32::INFINITY),
                (f32::NAN, f32::NAN),
            ] {
                for index in [0, 40, 255] {
                    cases.push((bits, shade_w.to_bits(), w.to_bits(), index, index));
                }
            }
        }
        check_indices(&cases);
    });
}

#[test]
fn fragment_index_finite_shades_round_and_clamp_without_using_the_fallback() {
    common::gpu_test(|| {
        let cases: Vec<_> = [
            (-f32::MAX, 0),
            (-1.0, 0),
            (-0.0, 0),
            (0.0, 0),
            (f32::MIN_POSITIVE, 0),
            (0.49, 0),
            (0.5, 1),
            (0.51, 1),
            (39.49, 39),
            (39.5, 40),
            (40.0, 40),
            (40.5, 41),
            (254.49, 254),
            (254.5, 255),
            (255.0, 255),
            (256.0, 255),
            (f32::MAX, 255),
        ]
        .into_iter()
        .map(|(shade, expected)| {
            (
                shade.to_bits(),
                f32::NAN.to_bits(),
                0.0f32.to_bits(),
                123,
                expected,
            )
        })
        .collect();
        check_indices(&cases);
    });
}
