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
/// Instance, then surface when there is one, then the best-ranked adapter that offers
/// [`REQUIRED_FEATURES`] and is compatible with the surface (hardware before a CPU fallback),
/// then a device built from downlevel defaults raised to the adapter's limits. A software
/// adapter is an outcome of that ranking, not an offscreen privilege.
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
/// turns up), and finds WARP where Vulkan has no software adapter, which [`REQUIRED_FEATURES`]
/// then passes over.
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

/// The adapter step of the acquisition policy: of the instance's adapters that offer
/// [`REQUIRED_FEATURES`] and can present to *surface*, the one [`choose_adapter`] ranks first.
fn select_adapter(
    instance: &wgpu::Instance,
    surface: Option<&wgpu::Surface<'static>>,
    options: RenderOptions,
) -> Option<wgpu::Adapter> {
    let adapters = pollster::block_on(instance.enumerate_adapters(wgpu::Backends::all()))
        .into_iter()
        .filter(|adapter| surface.is_none_or(|surface| adapter.is_surface_supported(surface)));
    choose_adapter(adapters, options.software_only, |adapter| {
        (adapter.get_info().device_type, adapter.features())
    })
}

/// The first of *adapters* that offers [`REQUIRED_FEATURES`], ranked as wgpu ranks a
/// high-performance request (discrete, integrated, other, virtual, then CPU; ties in
/// enumeration order); with `software_only`, CPU adapters only.
///
/// Ranking after the feature filter lets a Vulkan adapter with the feature win over a
/// DX12-only GPU that wgpu would rank first.
fn choose_adapter<A>(
    adapters: impl IntoIterator<Item = A>,
    software_only: bool,
    describe: impl Fn(&A) -> (wgpu::DeviceType, wgpu::Features),
) -> Option<A> {
    let rank = |kind: wgpu::DeviceType| match kind {
        wgpu::DeviceType::DiscreteGpu => 0,
        wgpu::DeviceType::IntegratedGpu => 1,
        wgpu::DeviceType::Other => 2,
        wgpu::DeviceType::VirtualGpu => 3,
        wgpu::DeviceType::Cpu => 4,
    };
    adapters
        .into_iter()
        .filter_map(|adapter| {
            let (kind, features) = describe(&adapter);
            let wanted = offers_required_features(features)
                && (!software_only || kind == wgpu::DeviceType::Cpu);
            wanted.then(|| (rank(kind), adapter))
        })
        .min_by_key(|&(rank, _)| rank)
        .map(|(_, adapter)| adapter)
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

    /// A fake enumerated adapter: its name, device type and features.
    type Listed = (&'static str, wgpu::DeviceType, wgpu::Features);

    fn pick(adapters: Vec<Listed>, software_only: bool) -> Option<&'static str> {
        choose_adapter(adapters, software_only, |&(_, kind, features)| {
            (kind, features)
        })
        .map(|(name, _, _)| name)
    }

    const CLIP: wgpu::Features = wgpu::Features::CLIP_DISTANCES;
    const NONE: wgpu::Features = wgpu::Features::empty();

    #[test]
    fn a_dx12_only_discrete_gpu_gives_way_to_an_integrated_gpu_with_clip_distances() {
        let adapters = vec![
            ("dx12 discrete", wgpu::DeviceType::DiscreteGpu, NONE),
            ("vulkan integrated", wgpu::DeviceType::IntegratedGpu, CLIP),
            ("lavapipe", wgpu::DeviceType::Cpu, CLIP),
        ];
        assert_eq!(pick(adapters, false), Some("vulkan integrated"));
    }

    #[test]
    fn choose_adapter_ranks_like_a_high_performance_request() {
        let adapters = vec![
            ("lavapipe", wgpu::DeviceType::Cpu, CLIP),
            ("other", wgpu::DeviceType::Other, CLIP),
            ("integrated", wgpu::DeviceType::IntegratedGpu, CLIP),
            ("first discrete", wgpu::DeviceType::DiscreteGpu, CLIP),
            ("second discrete", wgpu::DeviceType::DiscreteGpu, CLIP),
        ];
        assert_eq!(pick(adapters, false), Some("first discrete"));
    }

    #[test]
    fn choose_adapter_falls_back_to_a_cpu_adapter() {
        let adapters = vec![
            ("dx12 discrete", wgpu::DeviceType::DiscreteGpu, NONE),
            ("lavapipe", wgpu::DeviceType::Cpu, CLIP),
        ];
        assert_eq!(pick(adapters, false), Some("lavapipe"));
    }

    #[test]
    fn software_only_chooses_only_a_cpu_adapter_with_clip_distances() {
        let adapters = vec![
            ("discrete", wgpu::DeviceType::DiscreteGpu, CLIP),
            ("warp", wgpu::DeviceType::Cpu, NONE),
            ("lavapipe", wgpu::DeviceType::Cpu, CLIP),
        ];
        assert_eq!(pick(adapters.clone(), true), Some("lavapipe"));
        assert_eq!(pick(adapters[..2].to_vec(), true), None);
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
