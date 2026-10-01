# Trust model

The runner is the **trust boundary**. It enforces policy; plugins and their output are
**untrusted**.

## 1. Provenance tagging
Every value that can influence an action carries provenance:
- `user` — the user's utterance / explicit UI input. **Trusted.**
- `screen` — a11y tree, OCR, window titles, clipboard, web content. **Untrusted.**

## 2. Select, never author
Untrusted content **may only select among precomputed candidates**. It may **never author
new `args`**. Concretely: the constrained decision head (`llm.choose`) is **non-optional**
on any LLM-driven path; a request whose concrete arguments derive from `screen` provenance
is rejected by policy with `-32006`. Titles are truncated/sanitized; screen text is never
turned into a `terminal` command or an arbitrary `open_url` scheme.

## 3. Confirmation
Runner-enforced and **argument-bearing**: it displays the **concrete** URL/command/target,
then re-validates the target after approval (TOCTOU). `Step.confirm`/`require_confirm` are
real. Confirmation is a runner UI channel (`host.confirm`), not a plugin self-declaration
(plugin-declared `needs_confirm` is an untrusted hint).

## 4. Dangerous capabilities (off by default)
- `action.terminal` — **off by default**; enabling requires explicit confirmation; never fed
  LLM-derived strings unless the user opted in.
- `action.input` — high risk; native/builtin preferred.
- `action.open_url` — scheme allow-list (http/https/mailto); no `file:`, `javascript:`, etc.

## 5. IPC trust
Runner socket dir `0700`, socket `0600`, verify **`SO_PEERCRED`** (same uid), allow-list of
client binaries, rate limiting. Same-uid processes must not be able to drive actions by
default; privileged control requires an explicit token/allow-list entry.

## 6. Plugin sandboxing
Subprocess plugins run under systemd-run/bubblewrap hardening where possible
(`NoNewPrivileges`, `RestrictAddressFamilies`, `DeviceAllow`, `ReadOnlyPaths`, seccomp/landlock).
**If a permission cannot be enforced on a platform, it is labelled advisory** — never
implied safe. `doctor` prints the enforced-vs-advisory status per plugin.

## 7. Secrets & logging
Remote API keys via keyring/libsecret or a 0600 file; redacted from logs and `doctor`.
Screen/clipboard/audio content is **not** logged by default; debug logging is opt-in and
warned about. The one exception is the transcript **text**, which the daemon logs at `INFO`
level — see §8.

## 8. What Utter stores

Utter keeps a small amount of state on disk. Persistent state (survives reboot):

| Path | What it is |
|---|---|
| `~/.config/utter/config.toml` | your settings (`utter/config.py`) |
| `~/.local/share/utter/generated.yaml` | app catalogue generated from your installed apps (`utter/router/profiles.py`; written by `scripts/gen_app_catalog.py`) |
| `~/.local/share/utter/models/` | downloaded model weights (`assistant/models.py`) |
| `~/.local/state/utter/install.json` | install state, reversible (`assistant/install_state.py`, `assistant/util.py`) |

Runtime-only state (lives under `$XDG_RUNTIME_DIR`, cleared on logout):

| Path | What it is |
|---|---|
| `$XDG_RUNTIME_DIR/utter/osd.json` | live on-screen-display state, including the current partial/final transcript while the panel is open (`utter/voice/osd.py`); never persisted |
| `$XDG_RUNTIME_DIR/utter/sleep.json` | asleep/awake state only, written atomically (`utter/sleep.py`); never persisted |

Utter does **not** keep:

- **audio** — no recordings persist on disk;
- **command history or transcripts as files** — nothing is appended to a history file;
- **screen contents or screenshots beyond the live session** — vision captures overwrite a
  single temporary file.

Two caveats, stated plainly:

- The transcript **text** is logged at `INFO` level (`log.info("transcript: %r", text)`,
  `utter/daemon.py`), so it can appear in the **systemd journal** (`journalctl --user`).
  Lower `[daemon] log_level` to `WARNING` to stop it. This is the transcript text, not the
  audio; §7's "not logged by default" covers screen, clipboard and audio content.
- The only **application-specific** data today is the per-app shortcut and profile data (the
  generated app catalogue plus your own profile edits).

> **Forthcoming: personal memory.** A personal memory feature (the mem0 roadmap item) is **not
> implemented yet**. When it lands it will be **local and offline**, **opt-in**, and can be
> turned off; turning it off will mean Utter keeps no memory. Until then, Utter has no memory
> feature.

## 9. Forthcoming: app-targeted actions and background input

**Not shipped yet.** Two lanes are in progress; the intended behaviour and its platform limits
are recorded here so they can be linked later.

- **Linux/Wayland.** Wayland has no background key injection, so the mechanism is a **focus
  round-trip** (focus the target, send the key, restore focus). Measured cost is about **38 ms**
  same-workspace and **41 ms** cross-workspace with compositor animations off, but **~250 ms**
  of visible viewport scroll when niri animations are on.
- **macOS.** The intended path is the native `CGEventPostToPid` for **keyboard** (no focus
  change). The mouse **cannot** target background windows.
- **Hyprland.** `sendshortcut` exists but is unreliable for Electron/Chromium apps and can
  silently do nothing.

The config keys are still being finalised; a `[wayland]` setting will control this. Do not rely
on exact key names yet.

## 10. Supply chain
Installing a plugin = running untrusted code at user privilege: require a signature
(minisign over the package + signed index) and pinned digests; model downloads pinned by
sha256 over https; explicit consent and a scoped sandbox on install.
