# Native Windows support — plan

Status: **not yet supported** (Linux + macOS today). This documents the
grounded plan and the first landed groundwork. Windows is an explicit non-goal
in `README.md` and `docs/TRUST.md`; this file tracks the path to change that.

## Shape

The **protocol/policy brain is already portable** (framing, `runner/rpc.py`,
streams, handles, policy + provenance, `utter/router/**`, `utter/executor.py`,
the model store). The hard work is the **"plant"**: the platform integrations.
Mirror the macOS pattern — a `utter/win32/**` tree behind `utter/platform.py`,
plus a native runner transport and an NSIS/MSI installer.

## What already landed (P0 groundwork)

- `utter/platform.py`: `WINDOWS` + `is_windows()`, `sys.platform`/`UTTER_PLATFORM`
  aliases. (PR #51)
- `assistant/deps.py`: no longer hard-crashes on Windows (`import grp` guarded);
  Windows branch reports `powershell`/`nvidia-smi`/`ollama` and marks native
  backends advisory.
- `assistant/util.py`: `%LOCALAPPDATA%\utter` / `%APPDATA%\utter` paths.
- `assistant/doctor.py`: platform-specific runner start hint.
- `tests/platform/test_windows_detection.py`.

## Runner transport & trust (the key decision)

`runner` uses AF_UNIX + `SO_PEERCRED` (+ `/proc/<pid>/exe`) for peer identity.
On Windows that does **not** port as-is:

- Python 3.12/3.14 on Windows do **not** expose `socket.AF_UNIX`, and `asyncio`
  has no `create_unix_server()` (CPython gh-77589).
- No `SO_PEERCRED` on native Win32 (only `SIO_AF_UNIX_GETPEERPID` for a peer PID).

**P0 choice (implemented):** **loopback TCP 127.0.0.1:<port> + mandatory token**
(or **named pipes** later) in an ACL'd per-user location, with `fd.pass`
disabled (`-32005`), plugins on stdio, and permissions reported **advisory** (no
sandbox). Named pipes (`GetNamedPipeClientProcessId` + token SID) are the P2
hardening path for real peer identity. Do **not** weaken `docs/TRUST.md`
invariant #5.

### P0 transport contract (landed)

- **Selection** — `runner/platform.py`: `UTTER_RUNNER_TRANSPORT=unix|tcp` overrides
  the platform default (`tcp` on Windows, `unix` otherwise); `runner.socket_transport`
  in the TOML does the same. The override lets Linux tests exercise the TCP path.
- **Endpoint** — the server binds `127.0.0.1:0` (kernel-assigned port) and writes
  `%LOCALAPPDATA%\utter\runner.endpoint` = `{"host":"127.0.0.1","port":N}` atomically
  (temp file + `os.replace`). This file *is* `default_socket_path()` on Windows, and
  the assistant reads it (`assistant/util.py: runner_sock_path()`).
- **Token** — `%LOCALAPPDATA%\utter\runner-token`, created with
  `secrets.token_urlsafe(32)` via `O_CREAT|O_EXCL` (mode `0600` best-effort). The
  actual protection is **NTFS ACL inheritance** from the per-user profile
  directory; `chmod` on Windows only toggles the read-only bit and is advisory.
  A config `[socket] token` wins and is persisted to the same file so clients
  discover it; otherwise a fresh token is generated once and reused.
- **Auth** — every TCP client is default-deny until it sends
  `runner.auth {token}`. `allow_same_uid` / `allow_binaries` are **never** grants
  over TCP (there is no `SO_PEERCRED`); config validation rejects them with a
  clear error and requires a token.
- **No `fd.pass`** — `SCM_RIGHTS` does not exist here; `fd.pass` returns
  `-32005`, the runner does not advertise `host.fd.pass@1`, and plugins may only
  use the **stdio** transport (config rejects `connect`/`listen`).
- **Unix is byte-identical** — same AF_UNIX socket, `0600`, `SO_PEERCRED` /
  `/proc/<pid>/exe`, `SCM_RIGHTS`; the TCP code paths are never taken when
  `transport_kind() == "unix"`.

## Dependencies (wheels)

A **CPU-only** Windows path is shippable from wheels alone on 3.12/3.14:
`pywhispercpp` (CPU wheel) or `faster-whisper`+`ctranslate2` (CPU),
`sounddevice` (PortAudio DLLs bundled), `numpy`, `uiautomation`+`comtypes`
(a11y), `mss` (capture), `pywin32` (clipboard), `comtypes` (SAPI TTS). GPU STT
is **not** wheels-only (`ctranslate2` needs system CUDA 12 + cuDNN;
`pywhispercpp` GPU needs a source build).

The **`windows` extra** (`pip install -e ".[windows]"`) pins the CPU-first
runtime set — `numpy`, `sounddevice`, `pywin32`, `uiautomation`, `comtypes`,
`mss`. Optional STT (`pywhispercpp`) is intentionally left out until a
`win_amd64`/cp312 wheel is confirmed, so the extra always installs cleanly.

## CI (`windows-latest`)

`.github/workflows/windows.yml` runs on a real Windows runner (independent of the
Linux `verify` job) whenever `runner/**`, `assistant/**`, `tests/platform/**`,
`pyproject.toml` or the workflow change. It installs `.[windows]` (falling back
to the explicit wheel list), then asserts Windows detection + path/dependency
seams, the loopback-TCP runner transport, a core import smoke test, and
`python -m assistant --version`. `python -m runner._selftest` does **not** run
there: its non-e2e suite uses Unix-only primitives (`os.memfd_create`,
`os.getuid`, `socketpair`+`SCM_RIGHTS`, `AF_UNIX`).

## Phases

- **P0** — voice→action, no GUI: platform plumbing (landed), the transport
  above, `utter/win32/{desktop,clipboard,launch,inject,pointer,hotkey}.py`,
  STT/TTS/screenshot branches, a `windows` extra, tests.
- **P1** — GUI + service + installer: `%LOCALAPPDATA%`/`%APPDATA%` everywhere,
  **per-user Scheduled Task** (Session 0 services cannot do UIA/input/hotkeys),
  GUI WASAPI/PowerShell ports, PowerShell/NSIS installer, CI `windows-latest`,
  microphone-consent UX.
- **P2** — depth + hardening: full UI Automation, DPI-aware capture, named-pipe
  transport, optional Windows Speech backend, toasts/media integration.

## Spikes to run first

1. Transport: localhost TCP + token vs named pipes (decides P0).
2. Wheel installability on a real Win11 VM (esp. `ctranslate2`/`sounddevice`).
3. `WH_KEYBOARD_LL` PTT without admin.
4. UI Automation tree quality without elevation.
5. Tauri NSIS/MSI + per-user Scheduled Task + a relocatable Python runtime.

## Risks

- Weaker trust boundary (no peer identity without named pipes); no sandbox.
- UIPI blocks input into **elevated** windows unless Utter is elevated (avoid).
- Per-monitor DPI makes screenshot↔pointer coordinates error-prone.
- Packaging a Python runtime plus CUDA deps into an MSI is heavy.
