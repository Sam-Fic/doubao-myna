//! `myna-hud` — the dictation HUD renderer (feature 004, T124).
//!
//! Modes, one binary:
//!
//! * **hosted** (default) — consume `com.canonical.Myna.Dictation` and render
//!   the pill. Under GNOME the `myna-shell` extension launches this through a
//!   `Meta.WaylandClient` and owns the window's placement (R21). Where nobody
//!   else places the window, the HUD can host it itself: `--host x11` places
//!   it on an X11 window manager ([`myna_hud::host::x11`], a real X11 session
//!   or XWayland), and `--anchor bottom` pins it to the bottom of the screen
//!   — layer-shell ([`myna_hud::host::layer_shell`], feature `layer-shell`)
//!   on compositors that speak it, the X11 host on a mutter over XWayland,
//!   and nobody (the compositor's own placement) when neither is available.
//!   A renderer that also positioned itself under a positioning host would
//!   fight its host — hence the explicit flags.
//! * `--lab` — the development lab: manual controls driving the identical
//!   renderer modules with no backend at all.
//! * `--serve-dbus` — publish a simulated `com.canonical.Myna.Dictation` so the real
//!   hosted path can be exercised without the Python daemon.
//!
//! GTK owns the main thread; the bus worker talks to it over a channel.

use gdk4_x11 as gdkx11;
use gtk::glib;
use gtk4 as gtk;
use libadwaita as adw;
use libadwaita::prelude::*;

use myna_hud::bus::{self, BusEvent};
use myna_hud::dbus_consumer::DictationService;
#[cfg(feature = "layer-shell")]
use myna_hud::host::layer_shell::LayerShellHost;
use myna_hud::host::x11::X11Host;
use myna_hud::hud_logic::HudStyle;
use myna_hud::platform::Platform;
use myna_hud::signals::quit_on_signal;
use myna_hud::states::state_to_descriptor;
use myna_hud::window::HudWindow;
use myna_platform::{Desktop, Profile, Session, SessionKind};

const APP_ID: &str = "com.canonical.Myna.Hud";

/// Self-hosting on X11 without any X display to host on: retrying cannot
/// help (EX_CONFIG).
const EXIT_WRONG_SESSION: u8 = 78;

/// Who hosts the hosted HUD's window.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Host {
    /// A desktop shell (GNOME's `myna-shell`), or nobody.
    External,
    /// The HUD itself, on an X11 window manager (real X11, or XWayland).
    X11,
    /// The HUD itself, by whatever the session supports: layer-shell on
    /// compositors that speak it, else the X11 host over XWayland, else
    /// nobody.
    Auto,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Mode {
    Hosted(Host),
    #[cfg(dev_lab)]
    Lab,
    #[cfg(dev_lab)]
    ServeDbus,
}

fn main() -> glib::ExitCode {
    let mode = match parse_mode() {
        Ok(mode) => mode,
        Err(message) => {
            eprintln!("{message}");
            return glib::ExitCode::FAILURE;
        }
    };

    let platform = Platform::current();
    let wants_x11_backend = match mode {
        Mode::Hosted(host) => host_wants_x11_backend(host, &platform.session),
        // The lab harnesses run on the default backend; nobody positions
        // their windows.
        #[cfg(dev_lab)]
        Mode::Lab | Mode::ServeDbus => false,
    };
    if wants_x11_backend {
        if !x_display_available(&platform.session, std::env::var("DISPLAY").ok().as_deref()) {
            eprintln!(
                "myna-hud: the X11 host needs an X display (an X11 session or XWayland), \
                 this one is {:?}",
                platform.session
            );
            return glib::ExitCode::new(EXIT_WRONG_SESSION);
        }
        gtk::gdk::set_allowed_backends("x11");
    }

    // Lab / serve-dbus are developer harnesses that you want to run
    // repeatedly (often several at once) without D-Bus single-instance
    // forwarding — e.g. `myna-hud --lab` alongside a hosted instance.
    // There `NON_UNIQUE` is correct. The hosted HUD (no flag) must be a
    // singleton owning `com.canonical.Myna.Hud` so `myna-desktop`'s
    // `RegisterClient` + `NameOwnerChanged` pruning sees it, and the snap
    // `hud` D-Bus slot is actually claimed.
    let flags = {
        #[cfg(dev_lab)]
        {
            match mode {
                Mode::Lab | Mode::ServeDbus => gtk::gio::ApplicationFlags::NON_UNIQUE,
                Mode::Hosted(_) => gtk::gio::ApplicationFlags::empty(),
            }
        }
        #[cfg(not(dev_lab))]
        {
            gtk::gio::ApplicationFlags::empty()
        }
    };
    if let Err(error) = gtk::init() {
        // A forced X11 backend with nothing listening on $DISPLAY lands here;
        // there is nothing to retry.
        eprintln!("myna-hud: cannot open a display: {error}");
        return glib::ExitCode::FAILURE;
    }
    myna_hud::appearance::generic::remember_startup_theme();
    let app = adw::Application::builder()
        .application_id(APP_ID)
        .flags(flags)
        .build();

    quit_on_signal();

    let failed = std::rc::Rc::new(std::cell::Cell::new(false));
    let failed_in_activate = failed.clone();
    let profile = platform.profile;
    app.connect_activate(move |app| match mode {
        Mode::Hosted(host) => {
            if !activate_hosted(app, host, profile) {
                failed_in_activate.set(true);
                app.quit();
            }
        }
        #[cfg(dev_lab)]
        Mode::Lab => activate_lab(app, profile),
        #[cfg(dev_lab)]
        Mode::ServeDbus => activate_serve_dbus(app, profile),
    });

    // Our own argv is already consumed above.
    let code = app.run_with_args::<&str>(&[]);
    if failed.get() {
        glib::ExitCode::FAILURE
    } else {
        code
    }
}

fn parse_mode() -> Result<Mode, String> {
    parse_args(std::env::args().skip(1))
}

fn parse_args(arguments: impl Iterator<Item = String>) -> Result<Mode, String> {
    let mut mode = Mode::Hosted(Host::External);
    let mut arguments = arguments;
    while let Some(argument) = arguments.next() {
        match argument.as_str() {
            "--host" => mode = Mode::Hosted(parse_host(arguments.next().as_deref())?),
            other if other.starts_with("--host=") => {
                mode = Mode::Hosted(parse_host(other.strip_prefix("--host="))?)
            }
            "--anchor" => mode = Mode::Hosted(parse_anchor(arguments.next().as_deref())?),
            other if other.starts_with("--anchor=") => {
                mode = Mode::Hosted(parse_anchor(other.strip_prefix("--anchor="))?)
            }
            #[cfg(dev_lab)]
            "--lab" => mode = Mode::Lab,
            #[cfg(not(dev_lab))]
            "--lab" => {
                return Err(format!(
                    "myna-hud: --lab requires --features dev-lab (or a debug build)\n\n{USAGE}"
                ))
            }
            #[cfg(dev_lab)]
            "--serve-dbus" => mode = Mode::ServeDbus,
            #[cfg(not(dev_lab))]
            "--serve-dbus" => {
                return Err(format!(
                "myna-hud: --serve-dbus requires --features dev-lab (or a debug build)\n\n{USAGE}"
            ))
            }
            "--version" => {
                println!("myna-hud {}", env!("MYNA_VERSION"));
                std::process::exit(0);
            }
            "--help" | "-h" => {
                println!("{USAGE}");
                std::process::exit(0);
            }
            other => return Err(format!("myna-hud: unknown option {other}\n\n{USAGE}")),
        }
    }
    Ok(mode)
}

fn parse_host(value: Option<&str>) -> Result<Host, String> {
    match value {
        Some("x11") => Ok(Host::X11),
        Some(other) => Err(format!("myna-hud: unknown host {other}\n\n{USAGE}")),
        None => Err(format!("myna-hud: --host needs a value\n\n{USAGE}")),
    }
}

fn parse_anchor(value: Option<&str>) -> Result<Host, String> {
    match value {
        // The only anchored placement the pill's spec defines: bottom-centre
        // of the screen, `BOTTOM_MARGIN` above the bottom edge.
        Some("bottom") => Ok(Host::Auto),
        Some(other) => Err(format!(
            "myna-hud: unknown anchor {other} (only bottom)\n\n{USAGE}"
        )),
        None => Err(format!("myna-hud: --anchor needs a value\n\n{USAGE}")),
    }
}

/// Whether `host` must run the window on GDK's X11 backend, decided before
/// `gtk::init` — GDK cannot switch displays afterwards.
///
/// `--host x11` always. `--anchor bottom` only on a mutter: mutters have no
/// zwlr_layer_shell_v1 (mutter#973), so their Wayland backend can never host
/// the pill and the X11 host over XWayland is the only self-placement there
/// is. Anywhere else the Wayland backend may speak layer-shell
/// (`is_supported()` decides at activate), and if it does not the HUD stays
/// where the compositor puts it — the pre-`--anchor` status quo.
fn host_wants_x11_backend(host: Host, session: &Session) -> bool {
    match host {
        Host::X11 => true,
        Host::Auto => {
            session.kind == SessionKind::Wayland && matches!(session.desktop, Desktop::Gnome)
        }
        Host::External => false,
    }
}

/// An X11 session, or a Wayland session whose `DISPLAY` names XWayland. An
/// empty value counts as unset, as it does everywhere sessions are detected.
fn x_display_available(session: &Session, display: Option<&str>) -> bool {
    session.kind == SessionKind::X11
        || display.is_some_and(|value| !value.trim().is_empty())
}

#[cfg(dev_lab)]
const USAGE: &str = "\
Usage: myna-hud [OPTION]

The myna dictation HUD renderer.

  (no option)     consume com.canonical.Myna.Dictation and render the HUD
  --host x11      as above, placing its own window on an X11 window manager
                  (real X11, or XWayland on a Wayland session)
  --anchor bottom as above, pinning its own window to the bottom of the
                  screen: layer-shell on compositors that speak it, the X11
                  host over XWayland on a mutter, else nobody
  --lab           development lab: manual controls, no backend
  --serve-dbus    publish a simulated com.canonical.Myna.Dictation
  --version       print the version and exit
  -h, --help      print this help and exit";

#[cfg(not(dev_lab))]
const USAGE: &str = "\
Usage: myna-hud [OPTION]

The myna dictation HUD renderer.

  (no option)     consume com.canonical.Myna.Dictation and render the HUD
  --host x11      as above, placing its own window on an X11 window manager
                  (real X11, or XWayland on a Wayland session)
  --anchor bottom as above, pinning its own window to the bottom of the
                  screen: layer-shell on compositors that speak it, the X11
                  host over XWayland on a mutter, else nobody
  --version       print the version and exit
  -h, --help      print this help and exit";

/// The shipping path: render whatever the publisher reports. False when
/// the requested host cannot run.
fn activate_hosted(app: &adw::Application, host: Host, profile: Profile) -> bool {
    let hud = HudWindow::new(app, profile);
    if !install_host(&hud, host) {
        return false;
    }
    // Start idle → the window stays UNMAPPED and shows nothing until the
    // first non-idle state maps it, at which point the host adopts it (the
    // host adopts on map, and re-adopts on every subsequent map across the
    // idle unmap/remap cycle). Presenting an empty window at startup would
    // otherwise flash a static, empty pill before the first bus event.
    hud.apply_descriptor(state_to_descriptor(None, ""));

    let (sender, receiver) = async_channel::unbounded::<BusEvent>();
    bus::spawn(sender);

    // The consumer's rules run on the main thread beside the widgets, so a
    // state change and its redraw can never interleave.
    let hud_for_events = hud.clone();
    glib::spawn_future_local(async move {
        let mut service = DictationService::builder()
            .on_state_changed({
                let hud = hud_for_events.clone();
                move |state, status_message| {
                    hud.apply_descriptor(state_to_descriptor(Some(state), status_message));
                }
            })
            .on_level({
                let hud = hud_for_events.clone();
                move |rms, peak| hud.push_level(rms, peak)
            })
            .on_hud_style_changed({
                let hud = hud_for_events.clone();
                move |nick| hud.set_hud_style(HudStyle::from_nick(nick))
            })
            .build();
        service.enable();

        while let Ok(event) = receiver.recv().await {
            match event {
                BusEvent::NameAppeared(snapshot) => service.simulate_name_appeared(snapshot),
                BusEvent::NameVanished => service.simulate_name_vanished(),
                BusEvent::Properties(snapshot) => service.simulate_properties_changed(snapshot),
            }
        }
    });
    true
}

/// The development lab: manual controls, no backend.
#[cfg(dev_lab)]
fn activate_lab(app: &adw::Application, profile: Profile) {
    myna_hud::lab::present(app, profile);
}

/// The simulated publisher: the lab, plus a real `com.canonical.Myna.Dictation` on the
/// session bus so the hosted path can be exercised without the daemon.
#[cfg(dev_lab)]
fn activate_serve_dbus(app: &adw::Application, profile: Profile) {
    myna_hud::lab::present_serving(app, profile);
}

/// Place the window where nobody else does. False when an explicitly
/// requested host cannot run (`--host x11` only): `--anchor bottom` degrades
/// to the compositor's own placement rather than fail the daemon.
fn install_host(hud: &std::rc::Rc<HudWindow>, host: Host) -> bool {
    match host {
        Host::External => true,
        Host::X11 => match X11Host::install(hud) {
            Ok(_) => true,
            Err(e) => {
                eprintln!("myna-hud: --host x11: {e}");
                false
            }
        },
        Host::Auto => {
            let display = gtk::gdk::Display::default().expect("gtk is initialised");
            if display.is::<gdkx11::X11Display>() {
                // A real X11 session, or the XWayland leg a mutter was
                // committed to before init.
                if let Err(e) = X11Host::install(hud) {
                    eprintln!("myna-hud: --anchor bottom: {e}");
                }
                return true;
            }
            #[cfg(feature = "layer-shell")]
            if gtk4_layer_shell::is_supported() {
                LayerShellHost::install(hud);
                return true;
            }
            // No layer-shell here — a mutter with the feature compiled out,
            // or a compositor without the protocol: nobody places the
            // window, and the compositor keeps it where it puts ordinary
            // windows.
            true
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mode(args: &[&str]) -> Result<Mode, String> {
        parse_args(args.iter().map(|value| value.to_string()))
    }

    fn session(kind: SessionKind, desktop: &str) -> Session {
        Session {
            kind,
            desktop: Desktop::parse(desktop),
        }
    }

    #[test]
    fn anchored_bottom_hosts_itself_automatically() {
        assert_eq!(mode(&["--anchor", "bottom"]), Ok(Mode::Hosted(Host::Auto)));
        assert_eq!(mode(&["--anchor=bottom"]), Ok(Mode::Hosted(Host::Auto)));
    }

    #[test]
    fn only_bottom_is_an_anchored_placement() {
        let error = mode(&["--anchor", "top"]).expect_err("top is not a placement");
        assert!(error.contains("unknown anchor top"), "{error}");
        assert!(
            mode(&["--anchor"]).is_err(),
            "a bare --anchor is a usage error"
        );
    }

    #[test]
    fn the_x11_host_still_parses_and_unknown_hosts_still_fail() {
        assert_eq!(mode(&["--host", "x11"]), Ok(Mode::Hosted(Host::X11)));
        assert_eq!(mode(&["--host=x11"]), Ok(Mode::Hosted(Host::X11)));
        assert!(mode(&["--host", "mutter"]).is_err());
        assert!(mode(&["--anchor", "bottom", "--host", "x11"]).is_ok());
    }

    #[test]
    fn a_mutter_wayland_session_commits_to_the_x11_backend() {
        // Ubuntu's list form names GNOME just the same.
        assert!(host_wants_x11_backend(
            Host::Auto,
            &session(SessionKind::Wayland, "ubuntu:GNOME")
        ));
    }

    #[test]
    fn compositors_that_may_speak_layer_shell_keep_the_wayland_backend() {
        assert!(!host_wants_x11_backend(
            Host::Auto,
            &session(SessionKind::Wayland, "niri")
        ));
        assert!(!host_wants_x11_backend(
            Host::Auto,
            &session(SessionKind::Wayland, "")
        ));
        // An X11 session has no Wayland backend to keep: the X11 host it is.
        assert!(!host_wants_x11_backend(
            Host::Auto,
            &session(SessionKind::X11, "niri")
        ));
    }

    #[test]
    fn the_explicit_x11_host_always_wants_the_x11_backend() {
        assert!(host_wants_x11_backend(Host::X11, &session(SessionKind::Wayland, "niri")));
        assert!(!host_wants_x11_backend(
            Host::External,
            &session(SessionKind::Wayland, "ubuntu:GNOME")
        ));
    }

    #[test]
    fn an_x_display_is_a_live_session_or_xwayland() {
        let wayland = session(SessionKind::Wayland, "ubuntu:GNOME");
        let x11 = session(SessionKind::X11, "Xfce");
        assert!(x_display_available(&x11, None));
        assert!(x_display_available(&wayland, Some(":0")));
        assert!(!x_display_available(&wayland, None));
        // An empty value counts as unset, as it does in session detection.
        assert!(!x_display_available(&wayland, Some("")));
        assert!(!x_display_available(&wayland, Some("  ")));
    }
}
