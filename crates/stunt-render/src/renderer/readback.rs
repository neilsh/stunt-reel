//! Mapping a readback buffer and copying its rows out without the pitch padding.

use super::RenderError;

/// Maps a buffer, copies its rows out without the pitch padding, and unmaps it.
pub(super) fn read_back(
    device: &wgpu::Device,
    buffer: &wgpu::Buffer,
    width: u32,
    padded_row_bytes: u32,
) -> Result<Vec<u8>, RenderError> {
    let buffer_slice = buffer.slice(..);
    let (sender, receiver) = std::sync::mpsc::channel();
    buffer_slice.map_async(wgpu::MapMode::Read, move |result| {
        // A send fails only once `receiver` is gone, when nobody waits for the result.
        let _: Result<(), _> = sender.send(result);
    });

    device
        .poll(wgpu::PollType::wait_indefinitely())
        .map_err(|error| RenderError::Readback(error.to_string()))?;

    receiver
        .recv()
        .map_err(|error| RenderError::Readback(error.to_string()))?
        .map_err(|error| RenderError::Readback(error.to_string()))?;

    let mapped = buffer_slice
        .get_mapped_range()
        .map_err(|error| RenderError::Readback(error.to_string()))?;
    let row_bytes = width as usize * 4;
    let bytes = mapped
        .chunks_exact(padded_row_bytes as usize)
        .flat_map(|row| row.iter().take(row_bytes))
        .copied()
        .collect();
    drop(mapped);
    buffer.unmap();
    Ok(bytes)
}
