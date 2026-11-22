//! Adapter, device and instance acquisition shared by both destinations.

use std::sync::OnceLock;

use super::{RenderError, RenderOptions};

/// The adapter a renderer draws on.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AdapterIdentity {
    /// Adapter name as its driver reports it.
    pub name: String,
    /// The adapter is a CPU implementation (lavapipe, WARP), not a GPU.
    pub is_cpu: bool,
}

impl AdapterIdentity {
    /// The identity *adapter*'s driver reports.
    pub(super) fn of(adapter: &wgpu::Adapter) -> Self {
        let info = adapter.get_info();
        Self {
            is_cpu: is_cpu_adapter(&info),
            name: info.name,
        }
    }
}

/// The one acquisition policy both destinations use.
///
/// Instance, then surface when there is one, then a high-performance adapter compatible with
/// the surface, then a low-power fallback adapter, then a device built from downlevel defaults
/// raised to the adapter's limits. A software adapter is an outcome of the fallback attempt, not
/// an offscreen privilege.
pub(super) fn acquire(
    instance: &wgpu::Instance,
    surface: Option<&wgpu::Surface<'static>>,
    options: RenderOptions,
) -> Result<(wgpu::Adapter, wgpu::Device, wgpu::Queue), RenderError> {
    let adapter = select_adapter(instance, surface, options).ok_or(RenderError::NoGpuAdapter)?;
    let (device, queue) = open_device(&adapter)?;
    Ok((adapter, device, queue))
}

/// The instances the offscreen path tries, in order: Vulkan alone, then every backend.
///
/// An all-backends instance costs about 1.9 s on a Windows workstation with an RTX 4070: about
/// 0.95 s in the Vulkan loader and 0.95 s more enumerating DX12 adapters, before it picks the same
/// Vulkan adapter. Trying Vulkan alone first saves about 1 s and 80 MiB per process, with
/// byte-identical output: a one-tick CTRY render starts in a median 1.39 s against 3.15 s with
/// every backend (six alternating runs each; `research/parity/method.md` § 3). The second attempt keeps every other machine working: it runs when
/// Vulkan finds no adapter, or only a CPU one such as CI's lavapipe (kept if nothing better
/// turns up), and gives the software path WARP where Vulkan has no software adapter.
const OFFSCREEN_BACKENDS: [wgpu::Backends; 2] = [wgpu::Backends::VULKAN, wgpu::Backends::all()];

/// The first *preferred* adapter *request* finds over *attempts*, tried in order; when none
/// is preferred, the first adapter found at all.
///
/// A Vulkan-only instance on a machine whose Vulkan has only a software driver finds a CPU
/// adapter while DX12 may have the GPU, so the offscreen path prefers hardware and keeps
/// trying; a machine with no hardware adapter still renders on the first software one.
fn first_adapter<A>(
    attempts: &[wgpu::Backends],
    preferred: impl Fn(&A) -> bool,
    mut request: impl FnMut(wgpu::Backends) -> Option<A>,
) -> Option<A> {
    let mut fallback = None;
    for &backends in attempts {
        if let Some(adapter) = request(backends) {
            if preferred(&adapter) {
                return Some(adapter);
            }
            fallback.get_or_insert(adapter);
        }
    }
    fallback
}

/// Whether *adapter* is the kind the offscreen path asked for: any adapter when the caller
/// asked for software, else one that is not a CPU implementation.
fn preferred_adapter(adapter: &wgpu::Adapter, options: RenderOptions) -> bool {
    options.software_only || !is_cpu_adapter(&adapter.get_info())
}

/// Whether *info* describes a CPU implementation rather than a GPU.
fn is_cpu_adapter(info: &wgpu::AdapterInfo) -> bool {
    info.device_type == wgpu::DeviceType::Cpu
}

/// The offscreen adapter of the acquisition policy, chosen once per process.
///
/// Creating the instance and enumerating its adapters is the expensive part of start-up (see
/// [`OFFSCREEN_BACKENDS`]: a median 1.39 s per one-tick render with Vulkan first, against 3.15 s
/// with every backend), against about 30 ms for a device. A process that opens several
/// offscreen renderers, as the GPU integration tests do, pays that once: the adapter keeps its
/// instance alive, and each renderer still opens a device of its own. A process that found no
/// adapter keeps finding none.
pub(super) fn offscreen_adapter(options: RenderOptions) -> Result<wgpu::Adapter, RenderError> {
    static PREFERRED: OnceLock<Option<wgpu::Adapter>> = OnceLock::new();
    static SOFTWARE: OnceLock<Option<wgpu::Adapter>> = OnceLock::new();
    let chosen = if options.software_only {
        &SOFTWARE
    } else {
        &PREFERRED
    };
    chosen
        .get_or_init(|| {
            first_adapter(
                &OFFSCREEN_BACKENDS,
                |adapter| preferred_adapter(adapter, options),
                |backends| select_adapter(&create_instance(backends), None, options),
            )
        })
        .clone()
        .ok_or(RenderError::NoGpuAdapter)
}

/// The features the renderer's device requires: `CLIP_DISTANCES`, which clips the outline
/// lines to a band around the view (`vs_edge` in `mode13h.wgsl`). wgpu's DX12 backend, WARP
/// included, does not offer it.
pub(crate) const REQUIRED_FEATURES: wgpu::Features = wgpu::Features::CLIP_DISTANCES;

/// Whether an adapter offering `features` can open the renderer's device.
fn offers_required_features(features: wgpu::Features) -> bool {
    features.contains(REQUIRED_FEATURES)
}

/// The adapter step of the acquisition policy: high-performance first, then the fallback;
/// an adapter without [`REQUIRED_FEATURES`] is passed over.
fn select_adapter(
    instance: &wgpu::Instance,
    surface: Option<&wgpu::Surface<'static>>,
    options: RenderOptions,
) -> Option<wgpu::Adapter> {
    let usable = |adapter: &wgpu::Adapter| offers_required_features(adapter.features());
    if options.software_only {
        return request_fallback_adapter(instance, surface).filter(usable);
    }
    pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::HighPerformance,
        compatible_surface: surface,
        force_fallback_adapter: false,
        apply_limit_buckets: false,
    }))
    .ok()
    .filter(usable)
    .or_else(|| request_fallback_adapter(instance, surface).filter(usable))
}

/// The device step of the acquisition policy: [`REQUIRED_FEATURES`] and downlevel defaults
/// raised to the adapter's limits.
pub(super) fn open_device(
    adapter: &wgpu::Adapter,
) -> Result<(wgpu::Device, wgpu::Queue), RenderError> {
    pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
        label: Some("stunt_renderer_device"),
        required_features: REQUIRED_FEATURES,
        required_limits: wgpu::Limits::downlevel_defaults().using_resolution(adapter.limits()),
        memory_hints: wgpu::MemoryHints::Performance,
        experimental_features: wgpu::ExperimentalFeatures::disabled(),
        trace: wgpu::Trace::Off,
    }))
    .map_err(|error| RenderError::DeviceRequest(error.to_string()))
}

/// The low-power fallback attempt of the acquisition policy.
fn request_fallback_adapter(
    instance: &wgpu::Instance,
    surface: Option<&wgpu::Surface<'static>>,
) -> Option<wgpu::Adapter> {
    pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::LowPower,
        compatible_surface: surface,
        force_fallback_adapter: true,
        apply_limit_buckets: false,
    }))
    .ok()
}

/// A renderer instance over *backends*: every backend for a window, [`OFFSCREEN_BACKENDS`] offscreen.
pub(super) fn create_instance(backends: wgpu::Backends) -> wgpu::Instance {
    wgpu::Instance::new(wgpu::InstanceDescriptor {
        backends,
        ..wgpu::InstanceDescriptor::new_without_display_handle()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_adapter_without_clip_distances_cannot_open_the_renderer() {
        assert!(!offers_required_features(wgpu::Features::empty()));
        assert!(!offers_required_features(
            wgpu::Features::DEPTH_CLIP_CONTROL
        ));
        assert!(offers_required_features(
            wgpu::Features::CLIP_DISTANCES | wgpu::Features::DEPTH_CLIP_CONTROL
        ));
    }

    #[test]
    fn first_adapter_stops_at_the_first_backend_that_finds_one() {
        let mut tried = Vec::new();
        let got = first_adapter(
            &OFFSCREEN_BACKENDS,
            |_| true,
            |backends| {
                tried.push(backends);
                Some(backends)
            },
        );
        assert_eq!(got, Some(wgpu::Backends::VULKAN));
        assert_eq!(tried, vec![wgpu::Backends::VULKAN]);
    }

    #[test]
    fn first_adapter_falls_back_to_all_backends() {
        let mut tried = Vec::new();
        let got = first_adapter(
            &OFFSCREEN_BACKENDS,
            |_| true,
            |backends| {
                tried.push(backends);
                (backends == wgpu::Backends::all()).then_some(backends)
            },
        );
        assert_eq!(got, Some(wgpu::Backends::all()));
        assert_eq!(tried, vec![wgpu::Backends::VULKAN, wgpu::Backends::all()]);
    }

    #[test]
    fn first_adapter_is_none_when_no_backend_finds_one() {
        assert_eq!(
            first_adapter(&OFFSCREEN_BACKENDS, |_| true, |_| None::<u8>),
            None
        );
    }

    /// A fake adapter: the backends that found it, and whether it is hardware.
    type Fake = (wgpu::Backends, bool);

    #[test]
    fn first_adapter_passes_over_a_software_vulkan_adapter_for_hardware() {
        let got = first_adapter(
            &OFFSCREEN_BACKENDS,
            |&(_, hardware): &Fake| hardware,
            |backends| Some((backends, backends == wgpu::Backends::all())),
        );
        assert_eq!(got, Some((wgpu::Backends::all(), true)));
    }

    #[test]
    fn first_adapter_keeps_the_first_software_adapter_when_no_backend_has_hardware() {
        let got = first_adapter(
            &OFFSCREEN_BACKENDS,
            |&(_, hardware): &Fake| hardware,
            |backends| Some((backends, false)),
        );
        assert_eq!(got, Some((wgpu::Backends::VULKAN, false)));
    }
}
