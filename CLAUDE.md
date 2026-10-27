# CLAUDE.md

Project-specific guidance for Claude Code working on **doubao-input** (豆包语音输入法 for Linux).

## What this is

A push-to-hold voice input method for **GNOME / Wayland**. Press **right Ctrl** → speak → release →
recognized text is `wl-copy`-ed and `uinput`-injected as **Ctrl+V** into the currently-focused input
field. The riskiest piece (reversing Doubao's web ASR WSS) is vendored from upstream
[`doubao-murmur`](https://github.com/yourname/doubao-murmur) under `src/doubao_input/doubao/`. The
parts that are *not* vendored — `trigger/`, `inject/`, `ui/`, `app.py`, `__main__.py` — are original.

Full design lives in [`docs/design.md`](docs/design.md). Read it before making architecture changes.

## File map

```
src/doubao_input/
├── __main__.py            Entry: `python -m doubao_input`
├── autostart.py           Start-on-login switch: reads *both* backends (systemd
│                          user unit + XDG autostart entry), writes *one*,
│                          verifies by re-reading (see module docstring).
├── i18n.py                Multi-language (gettext). Source language is English;
│                          Chinese (zh_CN / zh_TW) comes from
│                          `locale/<lang>/LC_MESSAGES/doubao-input.po`.
│                          `.po` is compiled to `.mo` on the fly (pure-Python
│                          compiler inside this file) — only `.po` is committed.
│                          Call `init()` before building any UI (done in
│                          `__main__.main()`), then wrap strings in `_()`.
│                          Language is picked in the hamburger menu
│                          (control_window `_build_language_menu()` →
│                          `win.language(<code>)` → `set_language()`: save →
│                          `i18n.switch()` → rebuild the window, because UI
│                          strings are frozen at build time). Persisted as
│                          `settings.json: language` ("" = follow the system).
│                          EVERY user-visible string must be `_()`-wrapped;
│                          `tests/probe/` has no check for this, so run the
│                          po-coverage snippet in docs/design.md before release.
│                          Never translate at module level (constants like
│                          `TITLE = "..."` are evaluated at import, before
│                          `init()` runs) — translate at call time.
├── app.py                 GtkApplication. Wires trigger → TM → overlay/injector.
│                          Wraps AudioCapture.start/stop to pipe RMS to the overlay.
│                          Hides overlay+control window before paste so injected Ctrl+V
│                          reaches the user's input field, not our widgets.
│
├── doubao/                VENDORED from doubao-murmur (see NOTICE). Lightly patched.
│   ├── asr_client.py       WSS client to ws-samantha.doubao.com.
│   ├── audio_capture.py    sounddevice 16kHz/mono/int16. Added `_on_rms` callback.
│   ├── params_store.py     JSON persistence of {cookies, device_id, web_id}.
│   ├── config.py           Fixed Doubao params, paths, timeouts. IMPORTANT: also
│   │                       hosts AUTH_ERROR_CODE=709599054 used by asr_client to
│   │                       detect session expiry.
│   ├── app_state.py        GObject observable state (LoginStatus, RecordingState).
│   ├── login_window.py     WebKitGTK login + JS hook for /alice/profile/self.
│   ├── transcription.py    State machine. Upstream had handle_toggle(); this fork
│   │                       adds handle_press() / handle_release() + 150ms debounce
│   │                       (MIN_PRESS_DURATION) to convert toggle → push-to-hold.
│   └── host_tools.py       wl-copy / xclip candidate lists.
│
├── trigger/evdev_ptt.py    Background thread reads /dev/input/event* raw, picks
│                           EV_KEY/KEY_RIGHTCTRL edges (value=1→press, 0→release,
│                           2=autorepeat ignored), forwards via GLib.idle_add.
│                           Does NOT grab the keyboard. Rescans every 1s for hot-plug.
│
├── inject/injector.py      wl-copy (or xclip fallback) then UInput Ctrl+V (or
│                           Ctrl+Shift+V if use_shift=True). 12ms gap between key
│                           events (GAP=0.012) — without it GTK coalesces press/
│                           release and the paste shortcut never registers. uinput
│                           device is created lazily and kept alive for process life.
│
├── hud/                    Myna HUD front-end (optional, snap-free). Publishes
│   │                       com.canonical.Myna.Dictation so Myna's `myna-hud`
│   │                       (Rust/GTK4) draws the pill.
│   ├── bridge.py           AppState signals → wire State/StatusMessage; the
│   │                       ~20 Hz level pump (audio thread writes only a float)
│   ├── publisher.py        Gio/DBus publisher. Properties only, no custom
│   │                       signals (contract §Confinement)
│   ├── launcher.py         spawn/supervise the myna-hud process; skips spawn
│   │                       when the GNOME myna-shell extension is enabled
│   ├── wire.py             wire vocabulary + introspection XML
│   └── settings.py         ~/.config/doubao-input/hud.json
│
├── login/resources/        inject-websocket.js, inject-dom.js — loaded by WebView
│                           to intercept /alice/profile/self + read localStorage.
│
└── ui/
    ├── (removed) overlay.py  The self-drawn rounded-rectangle capsule. Deleted:
    │                       the UI is now always Myna's capsule, and a missing
    │                       renderer falls back to desktop notifications instead
    │                       of a second, differently-shaped window.
    ├── control_window.py   libadwaita settings window, 3 ViewStack pages
    │                       (账号 / 输入 / 诊断) in Myna Settings' style:
    │                       Adw.ApplicationWindow + ToolbarView + HeaderBar +
    │                       ViewSwitcher + PreferencesPage/Group + SwitchRow,
    │                       plus Adw.Banner for the login hint and Adw.ToastOverlay
    │                       for transient results. Falls back to a plain GTK4
    │                       window when Adw is missing.
    ├── adw_compat.py       Shared Adw helpers with graceful degradation:
    │                       ButtonContent (1.6+), ShortcutLabel (1.8+),
    │                       WindowTitle (1.6+), escaped subtitles, clipboard.
    ├── onboarding.py       4-step first-run wizard (Adw.Window + StatusPage).
    └── shortcut_capture.py Modal key-capture dialog (Adw.Window + StatusPage).

tests/probe/                Manual verification scripts (NOT pytest). P5_login.py and
                           P6_asr.py confirm Doubao login + ASR round-trip still works.

start.sh                    `PYTHONPATH=src .venv/bin/python -m doubao_input`
```

## Commands

```bash
# Run
./start.sh
# Equivalent to: PYTHONPATH=src .venv/bin/python -m doubao_input

# Verify login + ASR (manually, in order)
.venv/bin/python tests/probe/P5_login.py    # opens login window, writes credentials
.venv/bin/python tests/probe/P6_asr.py      # 5-second ASR round-trip with saved creds

# Diagnostic: enumerate keyboards and watch right-Ctrl (sudo-free if user is in `input`)
python -c "import evdev; [print(p) for p in evdev.list_devices()]"
evtest                                       # apt install evtest; pick keyboard device

# Diagnostic: clipboard alone
wl-copy "abc" && wl-paste
```

There is **no pytest suite yet**. State-machine logic in `transcription.py` is unit-testable but
not currently wired up — tests/probe/ are manual-only.

## Conventions

- **Language**: explanatory text and comments in Chinese, identifiers in English. Log messages
  are mixed (often English) since they show up in crash reports.
- **Threading**: long-running I/O (evdev, WSS, audio callback) runs on background threads. **All
  UI / GTK / GObject touches must happen on the GTK main thread.** Use `GLib.idle_add(fn, ...)`
  to marshal. The pattern in `EvdevPtt._dispatch()` is canonical.
- **Logging**: every module gets `logger = logging.getLogger(__name__)`. Keep INFO messages
  short and grep-friendly (e.g. `clipboard: wl-copy ok`, `paste: uinput ok`).
- **Vendored code**: do NOT rewrite `src/doubao_input/doubao/` without checking upstream first.
  Each file's docstring cites the original Swift source. Changes are listed in [`NOTICE`](NOTICE).
- **Timeouts / constants**: live in `src/doubao_input/doubao/config.py`. Add new constants there,
  not as magic numbers in callers.

## Things that have bitten before

- **uinput without delay** — sending Ctrl down/up too fast causes GTK apps to coalesce the
  sequence into a no-op. `injector.py` uses `GAP = 0.012` between every event. Don't remove it.
- **Injecting while our window is focused** — the injected Ctrl+V goes to *our* text widgets,
  not the user's input field. `app._do_paste` hides both overlay + control window before
  injecting, then restores the control window after 600ms. Don't bypass this.
- **Injecting before physical right-Ctrl is released** — uinput's Ctrl+V races with the
  physical right-Ctrl still-down. `PASTE_DELAY + 0.10` second wait in `app._do_paste` covers it.
- **Forgetting evdev autorepeat** — `value=2` events must be ignored or one press becomes many.
  See `EvdevPtt._dispatch`.
- **Mocking `audio_capture` / `asr_client` in tests** — `transcription.py` accepts replacements
  for these on its instance (look at how `app.py` does `tm.audio_capture = self._audio_capture`).
  Use the same pattern for unit tests rather than monkey-patching the class globally.
- **`gi.require_version` must be called before importing Gtk/WebKit** — both `app.py` and
  `tests/probe/P6_asr.py` do this. If you add a new probe, copy the line.
- **GNOME 48 has no StatusNotifierItem by default** — `ui.tray` (if added) must degrade silently,
  not fail. The control window + `.desktop` file are the always-available entry points.

## Vendoring / license

- Project license: AGPL-3.0-or-later — see [`LICENSE`](LICENSE).
- `src/doubao_input/doubao/` is from `doubao-murmur` (MIT). When porting a change from upstream,
  update the docstring attribution in the affected file and amend [`NOTICE`](NOTICE) if the
  delta is non-trivial.

## Myna HUD front-end

The desktop pill can be drawn by Myna's `myna-hud` (Rust/GTK4, built with
`bash scripts/build-myna-hud.sh`, no snap). The seam is
`com.canonical.Myna.Dictation` — properties only, contract:
`~/Desktop/myna/specs/004-gnome-shell-indicator/contracts/dbus-interface.md`.

- Do NOT put transcript content anywhere but `StatusMessage` (contract C3);
  `HUD_SHOW_TRANSCRIPT` is a deliberate, documented deviation that shows the
  newest slice of the recognized text in the pill.
- Levels are pushed at ~20 Hz and are **never** deduplicated (R16a): the
  renderer decays by arrival time, so a steady voice must keep refreshing.
- If the renderer is missing or dies, status falls back to desktop
  notifications (`ui/notifier.py`), never to a second capsule window;
  recording and injection must keep working either way.

## What "done" looks like for a change

- Touched files compile (`python -m compileall src/doubao_input`).
- If you changed behavior, P5 + P6 still pass.
- If you changed UI, manually verify in a real Wayland session: focus gedit, press right Ctrl,
  speak, release — text lands in gedit, overlay fades, focus stays on gedit.
- If you changed `transcription.py`, write a pytest that drives the state machine with fake
  `AudioCapture` / `ASRClient` and asserts: short-press cancels, normal press/release pastes
  final text, late result still pastes within the 1s safety timeout.