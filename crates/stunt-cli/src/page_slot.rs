//! A page sink that keeps every page the renderer hands back, for the caller to take in order.

use std::cell::RefCell;
use std::collections::VecDeque;
use std::rc::Rc;

use stunt_render::{PageSink, RenderedPage, SinkError};

/// Keeps the pages the renderer accepted, oldest first. Clones share the slot, so the renderer
/// owns one clone as its sink while the caller takes each page from another.
#[derive(Clone, Default)]
pub(crate) struct PageSlot(Rc<RefCell<VecDeque<RenderedPage>>>);

impl PageSlot {
    /// The oldest page the renderer handed back, removing it; `None` when none is waiting.
    pub(crate) fn take(&self) -> Option<RenderedPage> {
        self.0.borrow_mut().pop_front()
    }
}

impl PageSink for PageSlot {
    fn accept(&mut self, page: RenderedPage) -> Result<(), SinkError> {
        self.0.borrow_mut().push_back(page);
        Ok(())
    }
}
