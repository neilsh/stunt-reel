//! Mesa gallium `draw` clipper (llvmpipe, lavapipe): a `noperspective` varying
//! that is 1.0 at every vertex reads NaN after clipping.
//!
//! Draws one triangle per case into two 64x64 RGBA8 targets, one colouring the
//! `noperspective` copy of the varying and one the perspective copy:
//! red = NaN, yellow = infinite, green = finite and 1.0, blue = finite and not 1.0,
//! black = not covered. Prints the adapter and each case's pixel counts.
//!
//! Usage: `clip-nan-repro [DEVICE-NAME-SUBSTRING]` (default: the first device).
//! Select lavapipe with `VK_DRIVER_FILES=<mesa>/lvp_icd.x86_64.json`.

use ash::vk;

const SIZE: u32 = 64;

/// Vertex shader: clip-space positions and the per-vertex attribute come from
/// push constants, indexed by `gl_VertexIndex`, so no compiler can fold the
/// varying into a constant.
const VERTEX_GLSL: &str = r#"#version 450
layout(push_constant) uniform Triangle {
    vec4 clip_pos[3];
    vec4 attr; // x, y, z: the attribute at vertex 0, 1, 2 (all 1.0)
} tri;
layout(location = 0) noperspective out float v_noperspective;
layout(location = 1) out float v_perspective;
void main() {
    gl_Position = tri.clip_pos[gl_VertexIndex];
    v_noperspective = tri.attr[gl_VertexIndex];
    v_perspective = tri.attr[gl_VertexIndex];
}
"#;

/// Fragment shader: classifies each copy by its bits, not by `isnan`, which an
/// optimiser may assume false.
const FRAGMENT_GLSL: &str = r#"#version 450
layout(location = 0) noperspective in float v_noperspective;
layout(location = 1) in float v_perspective;
layout(location = 0) out vec4 noperspective_class;
layout(location = 1) out vec4 perspective_class;
// red: NaN; yellow: infinite; green: finite and 1.0; blue: finite, not 1.0
vec4 classify(float v) {
    uint bits = floatBitsToUint(v);
    if ((bits & 0x7f800000u) == 0x7f800000u) {
        if ((bits & 0x007fffffu) != 0u) {
            return vec4(1.0, 0.0, 0.0, 1.0);
        }
        return vec4(1.0, 1.0, 0.0, 1.0);
    }
    if (abs(v - 1.0) <= 1.0e-5) {
        return vec4(0.0, 1.0, 0.0, 1.0);
    }
    return vec4(0.0, 0.0, 1.0, 1.0);
}
void main() {
    noperspective_class = classify(v_noperspective);
    perspective_class = classify(v_perspective);
}
"#;

struct Case {
    name: &'static str,
    clip_pos: [[f32; 4]; 3],
}

const CASES: [Case; 3] = [
    // x <= w leaves an edge on x = w from w = 1.5 to w = -1.5; x >= -w then
    // cuts it at (0, -0.5, -0.25, 0), where t_nopersp = (0/0 - 1) / (1 - 1).
    Case {
        name: "A: edge left on x = w, cut by x = -w at w = 0",
        clip_pos: [
            [-0.5, -0.5, 0.75, 1.0],
            [3.5, -0.5, 1.75, 2.0],
            [-2.5, -0.5, -4.25, -4.0],
        ],
    },
    // Only the near plane (z >= 0) clips. Edge v0-v1 has screen x 0.5 at both
    // ends while clip x differs, so t_nopersp = (0.5 - 0.5) / (0.5 - 0.5).
    Case {
        name: "B: near plane on an edge of constant screen x",
        clip_pos: [
            [1.0, -1.0, -1.0, 2.0],
            [2.0, 3.0, 1.0, 4.0],
            [-3.0, 3.0, 1.0, 4.0],
        ],
    },
    // Control: B with v0 moved to screen x 0; clipped by the near plane only.
    Case {
        name: "control: near plane, screen x differs",
        clip_pos: [
            [0.0, -1.0, -1.0, 2.0],
            [2.0, 3.0, 1.0, 4.0],
            [-3.0, 3.0, 1.0, 4.0],
        ],
    },
];

const CLASSES: [(&str, [u8; 3]); 5] = [
    ("nan", [255, 0, 0]),
    ("inf", [255, 255, 0]),
    ("correct", [0, 255, 0]),
    ("wrong", [0, 0, 255]),
    ("uncovered", [0, 0, 0]),
];

fn spirv(stage: naga::ShaderStage, source: &str) -> Vec<u32> {
    let module = naga::front::glsl::Frontend::default()
        .parse(&naga::front::glsl::Options::from(stage), source)
        .unwrap_or_else(|e| panic!("GLSL: {}", e.emit_to_string(source)));
    let info = naga::valid::Validator::new(
        naga::valid::ValidationFlags::all(),
        naga::valid::Capabilities::all(),
    )
    .validate(&module)
    .expect("naga validation");
    let options = naga::back::spv::Options {
        // Keep gl_Position as written: no y flip, no extra bounds clamps.
        flags: naga::back::spv::WriterFlags::empty(),
        bounds_check_policies: naga::proc::BoundsCheckPolicies {
            index: naga::proc::BoundsCheckPolicy::Unchecked,
            ..Default::default()
        },
        ..Default::default()
    };
    let pipeline = naga::back::spv::PipelineOptions {
        shader_stage: stage,
        entry_point: "main".into(),
    };
    naga::back::spv::write_vec(&module, &info, &options, Some(&pipeline)).expect("SPIR-V")
}

fn memory_type(
    props: &vk::PhysicalDeviceMemoryProperties,
    bits: u32,
    flags: vk::MemoryPropertyFlags,
) -> u32 {
    (0..props.memory_type_count)
        .find(|&i| {
            bits & (1 << i) != 0
                && props.memory_types[i as usize]
                    .property_flags
                    .contains(flags)
        })
        .expect("memory type")
}

fn main() {
    let wanted = std::env::args().nth(1);
    unsafe { run(wanted.as_deref()) }
}

unsafe fn run(wanted: Option<&str>) {
    let entry = unsafe { ash::Entry::load() }.expect("Vulkan loader");
    let app = vk::ApplicationInfo::default().api_version(vk::API_VERSION_1_2);
    let instance = unsafe {
        entry.create_instance(
            &vk::InstanceCreateInfo::default().application_info(&app),
            None,
        )
    }
    .expect("instance");

    // Pick the device.
    let devices = unsafe { instance.enumerate_physical_devices() }.expect("devices");
    let describe = |pd: vk::PhysicalDevice| {
        let mut driver = vk::PhysicalDeviceDriverProperties::default();
        let mut props2 = vk::PhysicalDeviceProperties2::default().push_next(&mut driver);
        unsafe { instance.get_physical_device_properties2(pd, &mut props2) };
        let name = props2
            .properties
            .device_name_as_c_str()
            .unwrap()
            .to_string_lossy()
            .into_owned();
        let info = driver
            .driver_info_as_c_str()
            .unwrap()
            .to_string_lossy()
            .into_owned();
        (name, info)
    };
    let physical = *devices
        .iter()
        .find(|&&pd| wanted.is_none_or(|w| describe(pd).0.contains(w)))
        .expect("no matching Vulkan device");
    let (name, driver_info) = describe(physical);
    println!("adapter: {name} (driver info: {driver_info})");

    let queue_family = unsafe { instance.get_physical_device_queue_family_properties(physical) }
        .iter()
        .position(|q| q.queue_flags.contains(vk::QueueFlags::GRAPHICS))
        .expect("graphics queue") as u32;
    let priorities = [1.0];
    let queue_info = [vk::DeviceQueueCreateInfo::default()
        .queue_family_index(queue_family)
        .queue_priorities(&priorities)];
    let device = unsafe {
        instance.create_device(
            physical,
            &vk::DeviceCreateInfo::default().queue_create_infos(&queue_info),
            None,
        )
    }
    .expect("device");
    let queue = unsafe { device.get_device_queue(queue_family, 0) };
    let mem_props = unsafe { instance.get_physical_device_memory_properties(physical) };

    // Two colour targets and two readback buffers.
    let format = vk::Format::R8G8B8A8_UNORM;
    let bytes = (SIZE * SIZE * 4) as u64;
    let mut images = Vec::new();
    let mut views = Vec::new();
    let mut buffers = Vec::new();
    let mut buffer_memory = Vec::new();
    for _ in 0..2 {
        let image = unsafe {
            device.create_image(
                &vk::ImageCreateInfo::default()
                    .image_type(vk::ImageType::TYPE_2D)
                    .format(format)
                    .extent(vk::Extent3D {
                        width: SIZE,
                        height: SIZE,
                        depth: 1,
                    })
                    .mip_levels(1)
                    .array_layers(1)
                    .samples(vk::SampleCountFlags::TYPE_1)
                    .tiling(vk::ImageTiling::OPTIMAL)
                    .usage(
                        vk::ImageUsageFlags::COLOR_ATTACHMENT | vk::ImageUsageFlags::TRANSFER_SRC,
                    ),
                None,
            )
        }
        .unwrap();
        let req = unsafe { device.get_image_memory_requirements(image) };
        let mem = unsafe {
            device.allocate_memory(
                &vk::MemoryAllocateInfo::default()
                    .allocation_size(req.size)
                    .memory_type_index(memory_type(
                        &mem_props,
                        req.memory_type_bits,
                        vk::MemoryPropertyFlags::DEVICE_LOCAL,
                    )),
                None,
            )
        }
        .unwrap();
        unsafe { device.bind_image_memory(image, mem, 0) }.unwrap();
        let view = unsafe {
            device.create_image_view(
                &vk::ImageViewCreateInfo::default()
                    .image(image)
                    .view_type(vk::ImageViewType::TYPE_2D)
                    .format(format)
                    .subresource_range(vk::ImageSubresourceRange {
                        aspect_mask: vk::ImageAspectFlags::COLOR,
                        base_mip_level: 0,
                        level_count: 1,
                        base_array_layer: 0,
                        layer_count: 1,
                    }),
                None,
            )
        }
        .unwrap();
        let buffer = unsafe {
            device.create_buffer(
                &vk::BufferCreateInfo::default()
                    .size(bytes)
                    .usage(vk::BufferUsageFlags::TRANSFER_DST),
                None,
            )
        }
        .unwrap();
        let req = unsafe { device.get_buffer_memory_requirements(buffer) };
        let host = vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT;
        let mem = unsafe {
            device.allocate_memory(
                &vk::MemoryAllocateInfo::default()
                    .allocation_size(req.size)
                    .memory_type_index(memory_type(&mem_props, req.memory_type_bits, host)),
                None,
            )
        }
        .unwrap();
        unsafe { device.bind_buffer_memory(buffer, mem, 0) }.unwrap();
        images.push(image);
        views.push(view);
        buffers.push(buffer);
        buffer_memory.push(mem);
    }

    // Render pass: clear to black, then hand the targets to the copy.
    let attachment = vk::AttachmentDescription::default()
        .format(format)
        .samples(vk::SampleCountFlags::TYPE_1)
        .load_op(vk::AttachmentLoadOp::CLEAR)
        .store_op(vk::AttachmentStoreOp::STORE)
        .initial_layout(vk::ImageLayout::UNDEFINED)
        .final_layout(vk::ImageLayout::TRANSFER_SRC_OPTIMAL);
    let attachments = [attachment, attachment];
    let color_refs = [
        vk::AttachmentReference {
            attachment: 0,
            layout: vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL,
        },
        vk::AttachmentReference {
            attachment: 1,
            layout: vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL,
        },
    ];
    let subpass = [vk::SubpassDescription::default()
        .pipeline_bind_point(vk::PipelineBindPoint::GRAPHICS)
        .color_attachments(&color_refs)];
    let dependency = [vk::SubpassDependency::default()
        .src_subpass(0)
        .dst_subpass(vk::SUBPASS_EXTERNAL)
        .src_stage_mask(vk::PipelineStageFlags::COLOR_ATTACHMENT_OUTPUT)
        .src_access_mask(vk::AccessFlags::COLOR_ATTACHMENT_WRITE)
        .dst_stage_mask(vk::PipelineStageFlags::TRANSFER)
        .dst_access_mask(vk::AccessFlags::TRANSFER_READ)];
    let render_pass = unsafe {
        device.create_render_pass(
            &vk::RenderPassCreateInfo::default()
                .attachments(&attachments)
                .subpasses(&subpass)
                .dependencies(&dependency),
            None,
        )
    }
    .unwrap();
    let framebuffer = unsafe {
        device.create_framebuffer(
            &vk::FramebufferCreateInfo::default()
                .render_pass(render_pass)
                .attachments(&views)
                .width(SIZE)
                .height(SIZE)
                .layers(1),
            None,
        )
    }
    .unwrap();

    // Pipeline: no vertex input, no depth buffer, no culling, depth clamp off
    // (so the near plane clips), viewport covering the target.
    let push_range = [vk::PushConstantRange {
        stage_flags: vk::ShaderStageFlags::VERTEX,
        offset: 0,
        size: 64,
    }];
    let layout = unsafe {
        device.create_pipeline_layout(
            &vk::PipelineLayoutCreateInfo::default().push_constant_ranges(&push_range),
            None,
        )
    }
    .unwrap();
    let vs_code = spirv(naga::ShaderStage::Vertex, VERTEX_GLSL);
    let fs_code = spirv(naga::ShaderStage::Fragment, FRAGMENT_GLSL);
    let vs = unsafe {
        device.create_shader_module(&vk::ShaderModuleCreateInfo::default().code(&vs_code), None)
    }
    .unwrap();
    let fs = unsafe {
        device.create_shader_module(&vk::ShaderModuleCreateInfo::default().code(&fs_code), None)
    }
    .unwrap();
    let main_name = c"main";
    let stages = [
        vk::PipelineShaderStageCreateInfo::default()
            .stage(vk::ShaderStageFlags::VERTEX)
            .module(vs)
            .name(main_name),
        vk::PipelineShaderStageCreateInfo::default()
            .stage(vk::ShaderStageFlags::FRAGMENT)
            .module(fs)
            .name(main_name),
    ];
    let vertex_input = vk::PipelineVertexInputStateCreateInfo::default();
    let assembly = vk::PipelineInputAssemblyStateCreateInfo::default()
        .topology(vk::PrimitiveTopology::TRIANGLE_LIST);
    let viewport = [vk::Viewport {
        x: 0.0,
        y: 0.0,
        width: SIZE as f32,
        height: SIZE as f32,
        min_depth: 0.0,
        max_depth: 1.0,
    }];
    let scissor = [vk::Rect2D {
        offset: vk::Offset2D { x: 0, y: 0 },
        extent: vk::Extent2D {
            width: SIZE,
            height: SIZE,
        },
    }];
    let viewport_state = vk::PipelineViewportStateCreateInfo::default()
        .viewports(&viewport)
        .scissors(&scissor);
    let raster = vk::PipelineRasterizationStateCreateInfo::default()
        .depth_clamp_enable(false)
        .polygon_mode(vk::PolygonMode::FILL)
        .cull_mode(vk::CullModeFlags::NONE)
        .front_face(vk::FrontFace::COUNTER_CLOCKWISE)
        .line_width(1.0);
    let multisample = vk::PipelineMultisampleStateCreateInfo::default()
        .rasterization_samples(vk::SampleCountFlags::TYPE_1);
    let blend_attachment = vk::PipelineColorBlendAttachmentState::default()
        .color_write_mask(vk::ColorComponentFlags::RGBA);
    let blend_attachments = [blend_attachment, blend_attachment];
    let blend = vk::PipelineColorBlendStateCreateInfo::default().attachments(&blend_attachments);
    let pipeline_info = [vk::GraphicsPipelineCreateInfo::default()
        .stages(&stages)
        .vertex_input_state(&vertex_input)
        .input_assembly_state(&assembly)
        .viewport_state(&viewport_state)
        .rasterization_state(&raster)
        .multisample_state(&multisample)
        .color_blend_state(&blend)
        .layout(layout)
        .render_pass(render_pass)
        .subpass(0)];
    let pipeline = unsafe {
        device.create_graphics_pipelines(vk::PipelineCache::null(), &pipeline_info, None)
    }
    .map_err(|(_, e)| e)
    .unwrap()[0];

    let pool = unsafe {
        device.create_command_pool(
            &vk::CommandPoolCreateInfo::default().queue_family_index(queue_family),
            None,
        )
    }
    .unwrap();
    let cmd = unsafe {
        device.allocate_command_buffers(
            &vk::CommandBufferAllocateInfo::default()
                .command_pool(pool)
                .command_buffer_count(1),
        )
    }
    .unwrap()[0];
    let fence = unsafe { device.create_fence(&vk::FenceCreateInfo::default(), None) }.unwrap();

    let mut nan_noperspective = 0;
    for case in &CASES {
        let mut push = [0f32; 16];
        for (i, p) in case.clip_pos.iter().enumerate() {
            push[i * 4..i * 4 + 4].copy_from_slice(p);
        }
        push[12..15].copy_from_slice(&[1.0, 1.0, 1.0]);
        let push_bytes: Vec<u8> = push.iter().flat_map(|f| f.to_le_bytes()).collect();

        unsafe {
            device
                .reset_command_buffer(cmd, vk::CommandBufferResetFlags::empty())
                .unwrap();
            device
                .begin_command_buffer(cmd, &vk::CommandBufferBeginInfo::default())
                .unwrap();
            let clear = [vk::ClearValue {
                color: vk::ClearColorValue { float32: [0.0; 4] },
            }; 2];
            device.cmd_begin_render_pass(
                cmd,
                &vk::RenderPassBeginInfo::default()
                    .render_pass(render_pass)
                    .framebuffer(framebuffer)
                    .render_area(scissor[0])
                    .clear_values(&clear),
                vk::SubpassContents::INLINE,
            );
            device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::GRAPHICS, pipeline);
            device.cmd_push_constants(cmd, layout, vk::ShaderStageFlags::VERTEX, 0, &push_bytes);
            device.cmd_draw(cmd, 3, 1, 0, 0);
            device.cmd_end_render_pass(cmd);
            for (&image, &buffer) in images.iter().zip(&buffers) {
                let region = [vk::BufferImageCopy::default()
                    .image_subresource(vk::ImageSubresourceLayers {
                        aspect_mask: vk::ImageAspectFlags::COLOR,
                        mip_level: 0,
                        base_array_layer: 0,
                        layer_count: 1,
                    })
                    .image_extent(vk::Extent3D {
                        width: SIZE,
                        height: SIZE,
                        depth: 1,
                    })];
                device.cmd_copy_image_to_buffer(
                    cmd,
                    image,
                    vk::ImageLayout::TRANSFER_SRC_OPTIMAL,
                    buffer,
                    &region,
                );
            }
            let to_host = [vk::MemoryBarrier::default()
                .src_access_mask(vk::AccessFlags::TRANSFER_WRITE)
                .dst_access_mask(vk::AccessFlags::HOST_READ)];
            device.cmd_pipeline_barrier(
                cmd,
                vk::PipelineStageFlags::TRANSFER,
                vk::PipelineStageFlags::HOST,
                vk::DependencyFlags::empty(),
                &to_host,
                &[],
                &[],
            );
            device.end_command_buffer(cmd).unwrap();
            let cmds = [cmd];
            device
                .queue_submit(
                    queue,
                    &[vk::SubmitInfo::default().command_buffers(&cmds)],
                    fence,
                )
                .unwrap();
            device.wait_for_fences(&[fence], true, u64::MAX).unwrap();
            device.reset_fences(&[fence]).unwrap();
        }

        println!("{}", case.name);
        for (target, (label, &mem)) in ["noperspective", "perspective"]
            .iter()
            .zip(&buffer_memory)
            .enumerate()
        {
            let ptr =
                unsafe { device.map_memory(mem, 0, bytes, vk::MemoryMapFlags::empty()) }.unwrap();
            let pixels = unsafe { std::slice::from_raw_parts(ptr as *const u8, bytes as usize) };
            let mut counts = [0usize; CLASSES.len()];
            let mut other = 0;
            for px in pixels.chunks_exact(4) {
                match CLASSES.iter().position(|(_, rgb)| px[..3] == *rgb) {
                    Some(i) => counts[i] += 1,
                    None => other += 1,
                }
            }
            unsafe { device.unmap_memory(mem) };
            if target == 0 && !case.name.starts_with("control") {
                nan_noperspective += counts[0];
            }
            let line: Vec<String> = CLASSES
                .iter()
                .zip(counts)
                .map(|((n, _), c)| format!("{n} {c}"))
                .collect();
            let other = if other > 0 {
                format!(", other {other}")
            } else {
                String::new()
            };
            println!("  {label:>13}: {}{other}", line.join(", "));
        }
    }
    println!("NaN noperspective pixels in cases A and B: {nan_noperspective} (expected 0)");

    // The process exits here; the driver reclaims every object.
    unsafe { device.device_wait_idle() }.unwrap();
}
