# Install Utter — agent runbook

You are an AI agent installing **Utter**, a local, offline voice→desktop-action assistant,
on a **Linux** or **macOS** machine. This document is a self-contained, step-by-step runbook:
you start with no repo and no context. Follow the phases in order, verify each one, and report
what you actually saw.

If you were handed this file to *install* Utter, you are the installer — execute the commands,
don't just summarise them.

## Ground rules for you (the agent)

1. **You start with nothing.** Everything you need is in this document.
2. **Report every failure honestly.** Do not claim something works unless you ran it and saw
   the result. Do not fabricate output.
3. **Never invent fixes you cannot verify.** If a step needs a permission, device or account
   you can't get, say so and stop.
4. **Ask the human before anything destructive** (uninstalling, deleting files, changing system
   settings beyond what the app itself asks for).
5. **This is a voice app.** Any step that checks recognition needs the human to *speak*. Prompt
   them and wait.
6. Run commands in a terminal. For each step report the **exact command** and the **exact
   output** (trim long logs but keep the error lines).

## What Utter is (30-second version)

A daemon watches push-to-talk keys. Hold one, speak, release → it transcribes **on-device** and
either **types the text** (dictation) or **runs a desktop action** (assistant mode: open
apps/URLs, focus/close windows, press shortcuts). Everything is local: no account, no cloud.

- Repo: `https://github.com/sujaisubbanna/utter-assistant`
- Docs: `https://utter.sujaisubbanna.com`
- Installer (served from the site): `https://utter.sujaisubbanna.com/install.sh`

The one installer is cross-platform: on Linux it runs the wizard; on macOS it downloads the
signed app, installs it to `/Applications`, and launches it.

---

## Phase 0 — Detect the platform and report the environment

```bash
uname -s                 # Linux | Darwin
uname -m                 # x86_64 | arm64 | aarch64
# Linux:
cat /etc/os-release 2>/dev/null | head -n 2
# macOS:
sw_vers 2>/dev/null
python3 --version        # Utter needs 3.12+
curl --version | head -n 1
```

Record the OS, architecture and Python version. Utter needs **Python 3.12+** for the CLI; the
macOS app bundles its own Python runtime, so Python 3.12+ is only needed for the source path.
Stop and report if `curl` is missing.

---

## Phase 1 — Install

### Option A — the curl installer (recommended, both platforms)

Interactive wizard (a real terminal is best):

```bash
curl -fsSL https://utter.sujaisubbanna.com/install.sh -o install.sh
chmod +x install.sh && ./install.sh
```

Non-interactive, recommended defaults:

```bash
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --yes
```

Preview the plan without changing anything:

```bash
./install.sh --dry-run
```

**Linux:** this installs dependencies, the assistant core, the GUI, and the
`utter-runner.service` systemd **user** unit, then offers to enable and start it.
**macOS:** this resolves the release for your architecture (`aarch64` for Apple Silicon,
`x86_64` for Intel), downloads the `.dmg`, verifies its sha256 against the release checksums,
installs `utter.app` to `/Applications` (or `~/Applications` if that is not writable), clears
quarantine, **re-signs the app with a stable code identity** (`identifier "org.utter.settings"`)
so macOS privacy grants persist, and launches it.

### Option B — clone and run the installer

```bash
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant
./install.sh                 # or: ./install.sh --dry-run
```

### Option C — minimal package install (Linux)

```bash
./install/install.sh --yes
```

Undo with `./install/uninstall.sh --yes`.

### Option D — source checkout on macOS (developers)

End users should use Option A. For a source checkout:

```bash
./macos/setup.sh             # creates .venv-macos, writes the launchd agents
./macos/setup.sh --no-agent  # environment + config only, no background agents
```

`macos/setup.sh` refuses to clobber the agents a packaged `utter.app` already manages — if a
runtime is already installed it will point you at the app's **Settings** tab instead.

---

## Phase 2 — Verify the install

### Linux

```bash
systemctl --user status utter-runner.service --no-pager
# if it is not running yet:
systemctl --user enable --now utter-runner.service
```

Then open the GUI. On first launch the **first-run wizard** runs (see
[`ONBOARDING.md`](ONBOARDING.md)); afterwards, the **Settings** tab shows the runner service
state and a Start/Restart button. The tab also opens on launch whenever the runner is not
running.

### macOS

```bash
ls -d /Applications/utter.app
codesign -d -r- /Applications/utter.app 2>&1 | tail -n 1   # expect: identifier "org.utter.settings"
launchctl list | grep -i utter
tail -n 20 ~/Library/Logs/utter/utter.log
```

After the first-run wizard, the app's **Settings** tab unpacks the bundled Python runtime
into `~/Library/Application Support/utter/runtime/` and writes two launchd agents,
`com.utter.runner` and `com.utter.assistant`. The tab opens automatically while a required
permission is still missing.

---

## Phase 3 — macOS permissions (required before voice works)

macOS gates the APIs Utter uses. In **System Settings → Privacy & Security**, grant, for the
app **utter**:

| Permission | Used for | Symptom when missing |
|---|---|---|
| **Microphone** | capturing speech | no audio |
| **Speech Recognition** | Apple on-device recogniser (fallback) | Apple STT unavailable |
| **Input Monitoring** | the global push-to-talk key | keys never fire |
| **Accessibility** | typing text, pressing keys, window titles | injection silently does nothing |
| **Screen Recording** | reading window titles / screenshots | window titles come back empty |

Use the **Grant access** buttons on the wizard's permissions step or the **Settings** tab
(they open the exact pane). Grant each one.

**Critical gotcha:** Input Monitoring and Accessibility only take effect for **newly started**
processes. After granting them, the background agents must restart. The app does this
automatically when it sees them flip to granted; if you are doing it by hand:

```bash
launchctl kickstart -k gui/$(id -u)/com.utter.assistant
launchctl kickstart -k gui/$(id -u)/com.utter.runner
```

If a permission reads as granted but the API still does nothing, remove the app from the list
and add it back (toggling is often not enough), then restart the agents.

---

## Phase 4 — First run (needs the human to speak)

1. Open the app. The **first-run wizard** runs on first launch (see
   [`ONBOARDING.md`](ONBOARDING.md)); afterwards, on macOS the **Settings** tab confirms
   permissions and on Linux confirm the runner is running — the wizard's permissions step
   covers both.
2. Hold the **assistant key** (macOS default: **right Command**; Linux: your configured key),
   say **"open youtube"**, release.
3. Expected: a start sound, the on-screen overlay, then the browser opens YouTube and a success
   sound plays.

Report what happened. If nothing fired, check the logs first:

- macOS: `tail -f ~/Library/Logs/utter/utter.log`
- Linux: `journalctl --user -u utter-runner -f`

---

## Phase 5 — Uninstall (ask the human first)

```bash
# via the installer you already downloaded:
./install.sh --uninstall --yes

# or pipe a fresh copy:
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --uninstall --yes
```

- **Linux:** removes the installed files and disables/stops the systemd user units.
- **macOS:** stops the agents, removes `/Applications/utter.app` (and `~/Applications/utter.app`),
  `~/Library/Application Support/utter`, `~/Library/Logs/utter`, and the two
  `~/Library/LaunchAgents/com.utter.*.plist`. `~/.config/utter` (your config) is kept.

---

## Troubleshooting

- **macOS: "utter is damaged and can't be opened."** Quarantine was not cleared:
  `xattr -cr /Applications/utter.app`.
- **macOS: push-to-talk does nothing after granting Input Monitoring.** The agents are still the
  old, un-granted processes. Restart them (Phase 3).
- **macOS: `llutter`… no `launchctl` agents.** The app's **Settings** tab did not run; open
  the app and let it finish, or run `macos/setup.sh`.
- **Linux: `utter-runner` failed to start.** `systemctl --user status utter-runner.service` and
  `journalctl --user -u utter-runner -n 50` for the traceback.
- **No speech recognised.** On macOS ensure Microphone + Speech Recognition are granted; the
  default STT is local whisper.cpp with Apple Speech as fallback. On Linux check the input
  device in the config.
- **Installer checksum failure.** Re-run; the download can be retried. If it persists, report the
  asset name and the expected/actual hash.

---

## Report format (what to send back)

```
PLATFORM: <Linux|macOS> <arch> <version>
INSTALL METHOD: <A|B|C|D>
STATUS: pass | fail | partial
RAN: <exact commands>
SAW: <exact output, trimmed>
PROBLEMS: <what broke, with evidence>
COULD NOT TEST: <and why>
```

Then a short summary: what is now working, what is not, and the top problems ranked with
evidence.
