---
title: "Noctalia widget and OSD"
description: "The optional bar widget, attention panel and assistant-mode on-screen display for the Noctalia shell."
---

If you run the [Noctalia](https://github.com/noctalia-dev/noctalia-shell) shell, Utter ships an
optional widget package with three parts: a **bar widget**, a persistent **attention panel**, and
an **assistant-mode on-screen display (OSD)**. None of it is installed by default, and the core
assistant does not depend on it.

## Install

```bash
widgets/noctalia/install.sh            # copy + lint
widgets/noctalia/install.sh --yes      # + enable and add the bar widget
./install.sh --with-noctalia           # via the main installer (step 8 of the wizard)
```

The remote installer offers the same step and skips it with a one-line hint when Noctalia is not
detected. The widget is installed to `~/.local/share/noctalia/plugins/utter`. Its left-click
opens `utter-gui`; if the installer's prefix is not on your `PATH`, the installer offers to
create a `~/.local/bin/utter-gui` symlink so the widget can find it.

## The on-screen display

The OSD appears while the **assistant** push-to-talk key is held. Dictation does not raise it.

1. Hold the assistant key: a small panel appears (bottom centre by default) with a live
   **level meter** and, best-effort, the **in-progress transcript**.
2. Release: the final transcript is shown and the panel turns **green** if the router produced
   a command, or **red** if nothing matched.
3. After `dismiss_ms` it fades out.

Noctalia exposes no partial transcripts of its own, so the live transcript uses windowed
decoding and is best-effort. When it is not available, the level meter still works and the final
text appears on release.

:::note[Forthcoming: a loading state]
A `loading` state is being added to the OSD so the waveform can show models coming back after a
wake or cold start. It is **not shipped yet** — today the state is `idle`, `listening` or
`final`.
:::

### Configuration

```toml
[osd]
enabled = true            # UTTER_OSD=0 disables at runtime
position = "bottom_center"
dismiss_ms = 1200
stream = true             # best-effort windowed live transcription
stream_interval_ms = 700
window_s = 6
```

If a whisper model is present in the bridge environment, windowed decoding uses a second resident
model. Set `stream = false` to avoid that cost.

### How it works

The emitter writes `$XDG_RUNTIME_DIR/utter/osd.json` atomically:

```json
{"state":"listening","mode":"assistant","level":0.37,"text":"open you","activated":null,"ts":1700000000000}
```

| Field | Values |
|---|---|
| `state` | `idle`, `listening` or `final` |
| `mode` | `assistant` (dictation does not raise the OSD) |
| `level` | `0.0` to `1.0` |
| `text` | live, partial or final transcript |
| `activated` | `true` (command detected), `false` (not), or `null` while listening |
| `ts` | epoch milliseconds |

The Noctalia OSD service polls this file (every 50 ms while active, 500 ms when idle) and opens,
updates or closes the panel. An IPC push (`noctalia msg plugin <id>:osd focused show '<json>'`)
is also accepted for immediacy. The emitter is a strict no-op when disabled and never blocks the
recognition thread.

### Privacy

The OSD text is, by design, visible on your screen. The state file lives `0700` under
`$XDG_RUNTIME_DIR` and is not logged.

## Components in the repository

- **Emitter**: `utter/voice/osd.py`, wired into the vocalinux bridge for the assistant
  press, release and transcript paths. Loading it requires a restart of the bridge service.
- **Panel**: the Noctalia plugin under `plugins/ui/noctalia/` and the widget package under
  `widgets/noctalia/` (bar widget, attention panel, OSD and their pollers).
