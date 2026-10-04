# On-screen display (OSD)

An **optional** overlay that appears while a push-to-talk key is held — the **assistant** key
or the **dictation** key — shows what Whisper is hearing, then flashes **green** (the command
was detected / the text was typed) or **red** (it was not), and dismisses. Built on the same
Noctalia overlay-panel mechanism as the fleet attention badge.

## Behaviour
1. Hold the assistant key → a small panel appears (default bottom-centre) with a live **level
   meter** and, best-effort, the **in-progress transcript**.
2. Release → the final transcript is shown and the panel turns **green** if the router produced
   a command (activated) or **red** if not.
3. After `dismiss_ms` it fades out.

Holding the dictation key raises the same panel with `mode = "dictation"`; it turns green when
the text was typed and red if typing failed (the transcript is then copied to the clipboard).

Noctalia exposes no partial/interim transcripts, so windowed decoding is best-effort; if it
isn't available the level meter still works and the final text appears on release.

## State contract
The emitter writes `$XDG_RUNTIME_DIR/utter/osd.json` atomically:
```json
{"state":"listening","mode":"assistant","level":0.37,"text":"open you","activated":null,"ts":1700000000000}
```
| field | values |
|---|---|
| `state` | `idle` \| `listening` \| `loading` \| `final` |
| `mode` | `assistant` \| `dictation` |
| `level` | `0.0`–`1.0` (raw `0`–`100` input is normalised) |
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
- **Emitter** — `utter/voice/osd.py` (`OsdEmitter`). The native voice loops
  (`Utter.run_hotkey`, `Utter.run_macos`) drive it: PTT press -> `listening`, the capture
  callback -> `level`, a transcript -> `final` (and the emitter's own dismiss -> `idle`),
  and cold start / wake -> `loading` until ready via `utter/voice/model_loading.py`. It is a
  strict no-op when disabled and never blocks the recognition thread.
- **Panel** — the Noctalia widget (`widgets/noctalia/`, files `osd.luau` and `osd_poller.luau`),
  a persistent overlay panel plus a fast poller.

## Notes
- The Noctalia plugin must be installed/enabled.
- If a whisper model is available on the host, windowed decoding uses a second resident
  model; set `stream = false` to avoid that cost.
- Privacy: OSD text is screen-visible; the state file is written with the default mode under
  `$XDG_RUNTIME_DIR/utter/` (only the runner socket is `0700`/`0600`).
