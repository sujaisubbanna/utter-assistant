# Assistant-mode OSD (on-screen display)

An **optional** overlay that appears while the **assistant** push-to-talk key is held, shows
what Whisper is hearing, then flashes **green** (a command was detected) or **red** (not), and
dismisses. Built on the same Noctalia overlay-panel mechanism as the fleet attention badge.

## Behaviour
1. Hold the assistant key → a small panel appears (default bottom-centre) with a live **level
   meter** and, best-effort, the **in-progress transcript**.
2. Release → the final transcript is shown and the panel turns **green** if the router produced
   a command (activated) or **red** if not.
3. After `dismiss_ms` it fades out.

Noctalia exposes no partial/interim transcripts, so windowed decoding is best-effort; if it
isn't available the level meter still works and the final text appears on release.

## State contract
The emitter writes `$XDG_RUNTIME_DIR/utter/osd.json` atomically:
```json
{"state":"listening","mode":"assistant","level":0.37,"text":"open you","activated":null,"ts":1700000000000}
```
| field | values |
|---|---|
| `state` | `idle` \| `listening` \| `final` |
| `mode` | `assistant` (dictation does not raise the OSD) |
| `level` | `0.0`–`1.0` (vocalinux reports 0–100; the emitter normalises) |
| `text` | live/partial or final transcript |
| `activated` | `true` (command detected) \| `false` (not) \| `null` while listening |
| `ts` | epoch ms |

The Noctalia OSD service polls this file (50 ms while active, 500 ms idle) and opens/updates/
closes the panel; an IPC push (`noctalia msg plugin <id>:osd focused show '<json>'`) is also
accepted for immediacy.

## Configuration (`config.default.toml`)
```toml
[osd]
enabled = true            # UTTER_OSD=0 disables at runtime
position = "bottom_center"
dismiss_ms = 1200
stream = true             # best-effort windowed live transcription
stream_interval_ms = 700
window_s = 6
```

## Components
- **Emitter** — `utter/voice/osd.py` (`OsdEmitter`), wired additively into
  `utter/voice/vocalinux_bridge.py` for the assistant press/release/transcript paths. It is
  a strict no-op when disabled and never blocks the recognition thread.
- **Panel** — the Noctalia plugin (`plugins/ui/noctalia/`), a persistent overlay panel plus a
  fast poller.

## Notes
- Requires a restart of `utter-bridge` to load the emitter, and the Noctalia plugin to be
  installed/enabled.
- If a whisper model is present in the bridge venv, windowed decoding uses a second resident
  model; set `stream = false` to avoid that cost.
- Privacy: OSD text is screen-visible; the state file is 0700 under `$XDG_RUNTIME_DIR`.
