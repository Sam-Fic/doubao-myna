//! The Wayland layer-shell status surface host (`myna-hud --anchor bottom`):
//! the HUD pins its own window to the bottom of the screen, as `myna-shell`
//! does on GNOME, on compositors that speak `zwlr_layer_shell_v1` (niri,
//! sway, hyprland, KDE, ...).
//!
//! Mutters do not speak the protocol (GNOME/mutter#973), which is what the
//! GNOME extension is for; on a GNOME desktop `--anchor bottom` therefore
//! commits to the X11 host over XWayland up front instead (see `main`'s
//! backend choice — GDK cannot switch displays after init).
//!
//! Placement is `myna_platform::status_surface`'s bottom-centre spec: the
//! bottom edge anchored, [`BOTTOM_MARGIN`] above it, and the horizontal axis
//! left unanchored — the protocol centres a surface on any axis it is not
//! anchored on. `exclusive_zone(0)` puts the pill outside other layer
//! surfaces' reservations (a bottom bar) without reserving any of its own.
//! Margins are surface-local, so the spec margin needs no scale factor
//! (unlike the X11 host's device pixels).

use std::rc::Rc;

use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};

use myna_platform::status_surface::BOTTOM_MARGIN;

use super::Host;
use crate::window::HudWindow;

/// The layer-shell host. There is no per-map work: layer properties live on
/// the `GtkWindow` and survive its idle unmap/remap cycle, so unlike the X11
/// host nothing needs re-asserting before every map. Keeping a host *set*
/// still matters — [`HudWindow::set_hidden_faded`] maps through an idle when
/// hosted, so a return from idle lands at the new size instead of the old.
pub struct LayerShellHost;

impl LayerShellHost {
    /// Turn `hud`'s window into a bottom-centred layer surface. The caller
    /// has checked `gtk4_layer_shell::is_supported()`; the window must not
    /// have mapped yet.
    pub fn install(hud: &Rc<HudWindow>) -> Rc<Self> {
        let window = hud.window();
        window.init_layer_shell();
        // Defaults per the protocol, made explicit: a top layer surface that
        // never takes keyboard focus. `Top` is above every application
        // window — the shell extension's overlay is the same idea.
        window.set_layer(Layer::Top);
        window.set_keyboard_mode(KeyboardMode::None);
        window.set_anchor(Edge::Bottom, true);
        window.set_exclusive_zone(0);
        window.set_margin(Edge::Bottom, BOTTOM_MARGIN);
        // Lets compositor rules (niri's layer-rule, sway's for_window) match
        // the pill by namespace, as they would any other layer surface.
        window.set_namespace(Some("myna-hud"));
        Rc::new(Self)
    }
}

impl Host for LayerShellHost {
    fn before_map(&self) {}
}
