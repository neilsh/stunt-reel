//! Mapping a readback buffer and copying its rows out without the pitch padding.

use super::RenderError;

/// Runs `action` when dropped; `read_back` arms one once its buffer is mapped, so every later
/// return path unmaps it.
struct RunOnDrop<F: FnOnce()> {
    action: Option<F>,
}

impl<F: FnOnce()> RunOnDrop<F> {
    fn new(action: F) -> Self {
        Self {
            action: Some(action),
        }
    }
}

impl<F: FnOnce()> Drop for RunOnDrop<F> {
    fn drop(&mut self) {
        if let Some(action) = self.action.take() {
            action();
        }
    }
}

/// Maps a buffer once `submission` has executed, copies its rows out without the pitch padding,
/// and unmaps it.
///
/// The wait names `submission` rather than the latest one, so a later frame keeps rendering
/// while this page is mapped.
pub(super) fn read_back(
    device: &wgpu::Device,
    buffer: &wgpu::Buffer,
    width: u32,
    padded_row_bytes: u32,
    submission: &wgpu::SubmissionIndex,
) -> Result<Vec<u8>, RenderError> {
    let buffer_slice = buffer.slice(..);
    let (sender, receiver) = std::sync::mpsc::channel();
    buffer_slice.map_async(wgpu::MapMode::Read, move |result| {
        // A send fails only once `receiver` is gone, when nobody waits for the result.
        let _: Result<(), _> = sender.send(result);
    });

    device
        .poll(wgpu::PollType::Wait {
            submission_index: Some(submission.clone()),
            timeout: None,
        })
        .map_err(|error| RenderError::Readback(error.to_string()))?;

    receiver
        .recv()
        .map_err(|error| RenderError::Readback(error.to_string()))?
        .map_err(|error| RenderError::Readback(error.to_string()))?;

    // The map completed, so the buffer is mapped from here; the guard unmaps it on every return
    // path, including an error from `get_mapped_range`, so a later submission can reuse the slot.
    let _unmap = RunOnDrop::new(|| buffer.unmap());

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
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::RunOnDrop;
    use std::cell::Cell;

    #[test]
    fn an_error_after_mapping_still_runs_the_unmap_guard() {
        let unmapped = Cell::new(0);
        let result: Result<(), &'static str> = {
            let _unmap = RunOnDrop::new(|| unmapped.set(unmapped.get() + 1));
            // Stands in for `get_mapped_range` failing after the buffer was mapped.
            Err("readback failed")
        };
        assert!(result.is_err());
        assert_eq!(unmapped.get(), 1);
    }
}
