//! A page sink that keeps the one page each draw produces, for the caller to take.

use std::cell::RefCell;
use std::rc::Rc;

use stunt_render::{PageSink, RenderedPage, SinkError};

/// Holds the page the last draw produced. Clones share the slot, so the renderer owns one
/// clone as its sink while the caller takes each page from another.
#[derive(Clone, Default)]
pub(crate) struct PageSlot(Rc<RefCell<Option<RenderedPage>>>);

impl PageSlot {
    /// The page the last draw produced, emptying the slot; `None` when no page arrived.
    pub(crate) fn take(&self) -> Option<RenderedPage> {
        self.0.borrow_mut().take()
    }
}

impl PageSink for PageSlot {
    fn accept(&mut self, page: RenderedPage) -> Result<(), SinkError> {
        *self.0.borrow_mut() = Some(page);
        Ok(())
    }
}
