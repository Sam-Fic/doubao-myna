//! Status surface hosts: what places and protects the HUD window where no
//! desktop shell does it for us.
//!
//! On GNOME the `myna-shell` extension is the host and this crate has none.
//! Elsewhere the HUD hosts itself: [`x11`] on an X11 window manager (real
//! X11, or XWayland on a mutter), [`layer_shell`] on compositors that speak
//! zwlr_layer_shell_v1 (`--anchor bottom`, feature `layer-shell`).

pub mod ewmh;
#[cfg(feature = "layer-shell")]
pub mod layer_shell;
pub mod x11;

/// A host's hook into the window's idle unmap/remap cycle.
pub trait Host {
    /// The window is realized and unmapped, and is about to map.
    fn before_map(&self);
}
