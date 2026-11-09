# Journal: distilling `development.md`

The dated text of [`development.md`](../../../docs/development.md) as of commit `4e4abbb`, moved here verbatim when the page was distilled. Only relative link paths changed.

## 2026-11-07: GPU tests hang on an NVIDIA laptop

The join is the point: on 2026-11-07, 12 of 150 runs on an NVIDIA RTX 4070 laptop hung because a thread that had used NVIDIA's OpenGL driver (`nvoglv64.dll`, reached through the software-only adapter's all-backends instance, or a dropped GL instance's `wgpu-hal WGL Instance Thread`) exited after an earlier lock had already been released, and its `DllMain` detach, holding the loader lock, deadlocked against the next test's Vulkan `request_device` loading a DLL; with the join, 200 runs on the same machine passed.

**Lives in** [`development.md`](../../../docs/development.md#gpu-tests), GPU tests.
