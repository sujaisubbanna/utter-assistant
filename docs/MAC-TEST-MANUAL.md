# Utter on macOS — verification checklist

You are verifying **Utter**, a local, offline voice→desktop-action assistant, on a **MacBook**.
Utter is natively supported on Linux and macOS; this checklist confirms the macOS install,
permissions, voice and desktop actions on a real machine. Run it, find what breaks, and fix
what you can.

## Ground rules for you (the agent)

1. **You start with nothing.** No repo, no context. Everything you need is in this document.
2. **Work in a scratch directory** and report every failure honestly. Do not claim something
   works unless you ran it and saw the result. Do not fabricate output.
3. **Never invent fixes you cannot verify.** If a fix needs a real device/account/permission
   you can't get, say so.
4. **Ask the human before anything destructive** (uninstalling, deleting files, changing
   system settings beyond the app's own permissions).
5. **This is a voice app:** each test that involves speech needs the human to *speak*. When a
   step says "speak", prompt the human and wait.
6. Run commands in **Terminal**. Report the **exact command** and the **exact output** for
   each step (trim long logs but keep the error lines).

## What Utter is (30-second version)

A daemon watches two push-to-talk keys. Hold one, speak, release → it transcribes **on-device**
and either **types the text** (dictation) or **runs a desktop action** (assistant mode: open
apps/URLs, focus/close windows, press shortcuts). Everything is local: no account, no cloud.
On macOS it uses local **whisper.cpp** for recognition (with Apple's `Speech.framework` as the
fallback) and `say`/`AVSpeechSynthesizer` for replies, plus Quartz for hotkeys and key/text injection.

Repo: `https://github.com/sujaisubbanna/utter-assistant`
Docs: `https://utter.sujaisubbanna.com`

## Machine requirements

- macOS **12 (Monterey) or newer** — the practical floor; the code does not pin a minimum (some APIs need 14+; note your version).
- Python **3.12+** (`python3 --version`). Xcode Command Line Tools (`xcode-select -p`).
- An Apple Silicon Mac is expected (Intel may behave differently — note which you have).
- A working microphone.

---

## Phase 0 — Environment report (do this first)

```bash
sw_vers
uname -m
python3 --version
xcode-select -p || echo "CLT missing: run: xcode-select --install"
command -v git && git --version
```

Record the macOS version, architecture (arm64/x86_64), and Python version in your report.
Note anything missing before continuing.

---

## Phase 1 — Install Utter

```bash
mkdir -p ~/utter-test && cd ~/utter-test
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant
```

Run the macOS setup script (it creates a virtualenv, installs Python deps, writes the launchd
agents, and asks for the privacy permissions):

```bash
macos/setup.sh
```

If you only want the environment + config without the background agents:

```bash
macos/setup.sh --no-agent
```

**Expect:** a `.venv-macos` virtualenv, Python deps installed, two launchd agents under
`~/Library/LaunchAgents/` (`com.utter.runner.plist`, `com.utter.assistant.plist`), logs under
`~/Library/Logs/utter/`, and a permissions prompt sequence.

**Verify:**
```bash
ls -la .venv-macos/bin/python
ls ~/Library/LaunchAgents/ | grep -i utter
ls ~/Library/Logs/utter/ 2>/dev/null
```

**Report:** did the clone work? did `setup.sh` complete? paste any error. If a dependency
fails to build (e.g. `pywhispercpp`, `sounddevice`, a PyObjC framework), that is a real finding
— capture the error and note exactly which package.

---

## Phase 2 — Grant permissions (this is the usual failure point)

macOS gates the APIs Utter needs. In **System Settings → Privacy & Security**, grant to the
**Python binary** that runs the daemon (and/or Terminal, whichever macOS attributes the request
to):

| Permission | Used for | What breaks without it |
|---|---|---|
| **Microphone** | capturing speech | no audio at all |
| **Speech Recognition** | Apple `Speech.framework` | on-device transcription |
| **Input Monitoring** | global push-to-talk key | keys never fire |
| **Accessibility** | typing text, pressing keys, reading window titles | injection does nothing (often **silently**) |
| **Screen Recording** | reading **window titles** (`kCGWindowName`) | window titles come back empty |

The setup script asks for these; if the prompt was dismissed, re-request:

```bash
.venv-macos/bin/python -m assistant macos-permissions --request all
.venv-macos/bin/python -m assistant macos-permissions
```

**Known macOS gotcha to test explicitly:** a permission can read as "granted" while the API
still silently does nothing. If injection/hotkeys fail, **remove the app from the list and add
it back** (toggling the switch is often not enough), then **restart the daemon**.

**Report:** the output of `macos-permissions`, and whether any prompt was missed.

---

## Phase 3 — Confirm it runs (no voice yet)

```bash
cd ~/utter-test/utter-assistant

# The management CLI — should work with no runner running:
.venv-macos/bin/python -m assistant doctor --json
.venv-macos/bin/python -m assistant recommend --json

# Agent CLI:
.venv-macos/bin/utter --help
.venv-macos/bin/utter capabilities --json
```

**Expect:** `doctor` reports the platform, deps, and whether the runner is connected (it may
be offline until the runner service is started — that is normal). `recommend` suggests model
tiers based on RAM/GPU.

**Start the runner** (the plugin supervisor):
```bash
launchctl list | grep -i utter
launchctl kickstart -k gui/$(id -u)/com.utter.runner   # or: launchctl start com.utter.runner
sleep 3
.venv-macos/bin/python -m assistant status --json
```

**Report:** does `status` show the runner connected and a plugin? If the runner fails, paste
`~/Library/Logs/utter/` contents and `launchctl list | grep utter`.

---

## Phase 4 — The real tests (voice + actions)

For each test: note **what you expected**, **what happened**, and paste the relevant log lines.
Keep `~/Library/Logs/utter/` open in another window; most failures show there, not on screen.

### T1 — Dictation into a text field
1. Open **TextEdit**, new document, click in it.
2. Hold the **dictation key** (default: **right Option**), say *"hello from utter"*, release.
3. **Expected:** the text appears in TextEdit.

### T2 — Assistant action from voice
1. Hold the **assistant key** (default: **right Command**), say *"open youtube"*, release.
2. **Expected:** a browser opens YouTube. (Set `UTTER_DRY_RUN=0` for real actions; dry-run is on
   by default — check `config.toml`.)

### T3 — Background keyboard input (macOS-specific, the newest code)
This path posts a key to a *non-focused* app without stealing focus.
1. Open TextEdit (target) and then click back to another window so TextEdit is **not** focused.
2. Use a targeted command that posts to TextEdit, e.g. via the CLI:
   ```bash
   .venv-macos/bin/utter assistant "textedit type ok" --confirm --json
   ```
   (or the relevant app id from `utter apps list --json`).
3. **Expected:** `ok` lands in TextEdit **without** focus switching to it.
4. **Report especially:** did it deliver at all? did focus change? Any error in the log about
   `CGEventPostToPid`.

### T4 — Window/context awareness
```bash
.venv-macos/bin/python -m assistant doctor --json    # compositor/context section
.venv-macos/bin/utter apps list --json
.venv-macos/bin/utter actions list --app safari --json   # pick an installed app
```
**Expected:** apps/windows are detected via `NSWorkspace` + the CoreGraphics window list.
**Known limitation to confirm:** window **titles** are empty unless Screen Recording is granted.

### T5 — Spoken replies (TTS)
```bash
.venv-macos/bin/utter speak "utter is working" --confirm --json
```
**Expected:** the Mac speaks the sentence (via `say`). **Report:** did audio play?

### T6 — Sleep / wake
1. Say *"go to sleep"* (assistant key) → **expected:** models unload, only a listener stays.
2. Hold a push-to-talk key → **expected:** it wakes (speech reloads; bigger models reload in
   the background; the on-screen waveform shows a "loading" state).

### T7 — Language
```bash
.venv-macos/bin/utter settings set stt.language --value '"de-DE"' --confirm --json
.venv-macos/bin/utter settings set tts.language --value '"de-DE"' --confirm --json
```
**Expected:** on macOS the speech recognizer uses that locale (`SFSpeechRecognizer`); if that
locale has no on-device model, it should **fall back** gracefully, not crash. **Report** whether
German dictation works at all (it needs the Apple language model downloaded).

### T8 — Settings app (GUI)
Build/launch the Tauri settings app:
```bash
cd gui-tauri
pnpm install
pnpm tauri build        # NOTE: must be `pnpm tauri build`, NOT `cargo build`
# then launch the produced .app, or: pnpm tauri dev
```
**Expected:** a window opens and renders. Confirm it is **not** a black window (a `cargo build`
binary renders black — the launcher/CI use `pnpm tauri build`).
**Report:** does it render? Do the pages load? Is the language picker present with
en/es/de/fr/it/pt/zh/ja/ko/ru?

---

## Phase 5 — What to fix

Prioritise in this order:

1. **Crashes / total failures** (install, runner start, any Python traceback).
2. **Silent no-ops** (permissions granted but injection/hotkeys do nothing) — almost always an
   Accessibility/Input-Monitoring attribution problem. Fix = re-add the app to the permission
   list and restart; if you find a code path that could *detect* this and warn, that's a good fix.
3. **T3 background input** — if `CGEventPostToPid` doesn't deliver, check for a missing
   **timestamp** on the event (macOS 15 drops untimestamped posted events) and that the pid is
   resolved from the window list.
4. **Titles empty** — expected without Screen Recording; only "fix" if you can make the code
   degrade clearly (e.g. say "enable Screen Recording for window titles").
5. **Docs**: if you find a macOS instruction that's wrong, fix it in `docs/MACOS.md`.

**When you change code:**
```bash
cd ~/utter-test/utter-assistant
git checkout -b fix/macos-<short-name>
# ... edit ...
scripts/verify.sh            # the repo's test suite (should stay green)
git commit -am "fix(macos): <what>"
git push origin fix/macos-<short-name>   # if you have push access
```
If you cannot push, leave the branch and report the diff.

**Do NOT** touch: `protocol/PROTOCOL.md` (frozen wire format), the trust/provenance rules, or
anything Linux-only without a clear macOS reason.

---

## Report format (what to send back)

For each phase and each test T1–T8:

```
TEST: T3 background input
STATUS: pass | fail | blocked | partial
RAN:   <exact command(s)>
SAW:   <exact output / observation, trimmed>
EXPECTED: <what should have happened>
DIFF:  <what actually differed>
FIX:   <branch/commit if you changed code, or "none — reason">
LOGS:  <relevant lines from ~/Library/Logs/utter/>
```

Then a short summary:
- macOS version + arch + Python version.
- Which permissions were granted (and any that couldn't be).
- The **top 5 concrete problems**, ranked, each with the evidence.
- Anything you could not test and why.

## Quick reference

```bash
# Logs
tail -f ~/Library/Logs/utter/*.log

# Services
launchctl list | grep -i utter
launchctl stop  com.utter.runner
launchctl start com.utter.runner
launchctl stop  com.utter.assistant
launchctl start com.utter.assistant

# Config (edit, then restart the daemon)
cat ~/.config/utter/config.toml
# key macOS knobs: [macos] stt_backend, speech_locale, tts_backend, tts_voice,
#                  hotkey_backend, dictation_key, assistant_key
# real actions instead of dry-run: UTTER_DRY_RUN=0 in the agent's environment

# Uninstall (ask the human first)
macos/setup.sh --uninstall
```

## Known context (so you don't rediscover what's already known)

- **macOS is supported on real hardware.** These checks cover the platform-specific paths; treat
  any failure as a bug to report.
- **The default STT is local whisper.cpp**, which needs a downloaded language model. If it cannot
  load, the code falls back to Apple's `Speech.framework` (which needs an on-device language model).
- **Background keyboard input on macOS** uses `CGEventPostToPid` (a key event posted straight to
  a process, no focus change). It is **keyboard-only** — mouse cannot target a background window.
  Scrutinise it.
- **Permissions are the #1 source of "it silently does nothing."** When in doubt: re-add the app
  to the permission list, restart the daemon, retry.
