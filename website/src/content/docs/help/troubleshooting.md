---
title: "Troubleshooting"
description: "Fixes for the common problems: a blank settings window on dual NVIDIA GPUs, ydotoold not running, missing input-group permission, missing models, PATH and services."
---

Start with the doctor. It checks the command-line tools, the `input` group, `uinput`, the
plugins' negotiation and each permission's enforcement status:

```bash
assistant doctor          # human-readable
assistant doctor --json   # the same, for scripts and bug reports
```

The **Diagnostics** page of the settings app shows the same report, a live log tail and an
**Export support bundle** button that gathers everything into one archive without secrets.

## The settings window is blank or black

**Symptom:** `utter-gui` opens a window but it stays blank (or black), typically on Wayland with
**two NVIDIA GPUs**.

**Cause:** WebKitGTK's DMABUF renderer fails on that setup.

**Fix:** disable the DMABUF renderer so the webview draws through shared memory:

```bash
WEBKIT_DISABLE_DMABUF_RENDERER=1 utter-gui
```

The `utter-gui` launcher wrapper in the repository and the dev scripts already set this. If you
start the app from a `.desktop` entry, add the variable to its `Exec=` line:

```ini
Exec=env WEBKIT_DISABLE_DMABUF_RENDERER=1 utter-gui
```

## Clicks and typed text do nothing (`ydotoold`)

**Symptom:** `doctor` reports `ydotoold` missing or not running; "click" steps or dictation
produce nothing, or `ydotool` prints a socket error.

**Cause:** `ydotool` needs its daemon, `ydotoold`, and a socket it can reach.

**Fix:** enable the daemon as a user service:

```bash
systemctl --user enable --now ydotool      # distro-provided unit, if present
# or the unit shipped in the repo:
cp systemd/ydotoold.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ydotoold.service
```

The shipped unit runs `ydotoold` with a per-user socket under `$XDG_RUNTIME_DIR` and Utter sets
`YDOTOOL_SOCKET` for its clients automatically. `ydotoold` also needs the `uinput` kernel module
(`sudo modprobe uinput`) and write access to `/dev/uinput`, which is the next item.

## Push-to-talk never triggers (input group and `/dev/uinput`)

**Symptom:** holding the key does nothing, no start sound; `doctor` flags `input_group` or
`uinput`.

**Cause:** the push-to-talk listener reads your keyboard through evdev, which requires
membership in the `input` group. Input injection additionally needs `/dev/uinput`.

**Fix:**

```bash
sudo usermod -aG input "$USER"
sudo modprobe uinput
```

Then **log out and back in** so the new group applies. If `/dev/uinput` is still not writable,
add a udev rule such as `KERNEL=="uinput", GROUP="input", MODE="0660"` and reload udev. The
installer prints these exact steps and never changes your groups for you.

The listener does **not** grab the keyboard, so your key keeps working in other apps.

## "No models yet" or speech recognition does nothing

**Symptom:** the Models page says *No models yet*, or the assistant key plays the start sound
but nothing is transcribed.

**Cause:** the installer never downloads a model; speech recognition needs one.

**Fix:** open the **Models** page and press **Get it** on the recommended speech model, or pull
one from the command line:

```bash
assistant recommend                     # what suits this machine
assistant models pull hf:org/repo:file  # a specific file
assistant models list
```

For whisper.cpp, Utter looks in `$UTTER_WHISPER_MODEL`, `$UTTER_MODELS_DIR`,
`<repo>/models/whisper`, `~/.local/share/vocalinux/models/whispercpp` and `~/.cache/whisper`,
and `pywhispercpp` will download a known model name on first use. The **decision** and
**vision** models are optional; without them Utter still handles every rule-matched command.
See [Models](/guides/models/).

## The decision head or vision never responds

**Symptom:** fuzzy phrasing falls back to rules, or "click ..." reports *vision disabled* or a
timeout.

**Cause:** the model store holds files; a server has to serve them. The endpoints in
`[router] llm_base_url` and `[vision] base_url` must be running.

**Fix:** start the servers (`scripts/serve_planner.sh`, `scripts/serve_vision.sh`) or point the
config at your own OpenAI-compatible server, then use **Test endpoint** on the LLM page. The
decision head **fails open to rules** on any error, so a missing server degrades gracefully rather
than breaking commands.

## `assistant` or `utter-gui`: command not found

The installer puts binaries under `$PREFIX/bin`, `~/.local/bin` by default:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Add that to your shell profile to make it permanent.

## The runner service is not running

```bash
systemctl --user status utter-runner.service
journalctl --user -u utter-runner.service -f
systemctl --user restart utter-runner.service
```

User services do not inherit the session environment. The shipped unit runs through a wrapper
that discovers `WAYLAND_DISPLAY`, `DBUS_SESSION_BUS_ADDRESS` and `NIRI_SOCKET` first, so make
sure it starts **after** your Wayland session is up (it is bound to
`graphical-session.target`).

## "Open youtube" opens a duplicate tab

Background-tab awareness needs the browser to expose WebDriver BiDi. For the Zen browser run
`scripts/install-zen-bidi-desktop.sh` so it starts with `--remote-debugging-port=9222`; for
other Firefox-family browsers start them with that flag and set `ZEN_BIDI_PORT`. Chromium-family
browsers are matched by window title only. See
[Apps and actions](/guides/apps-and-actions/#browser-tab-control-over-webdriver-bidi).

## A terminal command or raw input is refused

That is the policy working. `action.terminal` and `action.input` are off by default and need an
explicit opt-in in the runner config, after which they still ask for confirmation. See
[Trust and safety](/guides/trust-and-safety/#dangerous-abilities-are-off-by-default).

## The theme does not follow my wallpaper

The settings app reads `~/.local/share/utter/colors.css`. Run
`scripts/install-matugen-utter.sh`, then your usual matugen command. A dark palette is ignored
while the app is in Light mode (and vice versa) by design. See [Theming](/guides/theming/).

## Still stuck?

Export a support bundle from the **Diagnostics** page, or attach `assistant doctor --json`, and
[open an issue](https://github.com/sujaisubbanna/utter-assistant/issues).
