---
title: "Getting started"
description: "Your first ten minutes with Utter: the two push-to-talk keys, picking a first model, the two modes and sleep mode."
---

This page assumes Utter is installed. If it is not, start with the [install overview](/install/).

## Requirements

- **Linux on Wayland** and **macOS**. On Linux, **niri** and **KDE Plasma (KWin)** are first-class;
  other compositors get partial support (dictation, typing, launching; no window actions).
- **PipeWire** for audio (Linux).
- **Python 3.12 or newer**.
- An NVIDIA GPU is recommended for the larger models, but not required. Utter runs with no
  models at all, and with CPU-only speech recognition.

## 1. Start the runner and open the settings app

```bash
systemctl --user enable --now utter-runner.service   # start the background runner
assistant doctor                                     # check tools, plugins and permissions
utter-gui                                            # open the settings window
```

If `utter-gui` is not found, the installer's prefix is probably not on your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`assistant doctor` tells you which command-line tools are missing and whether your user can read
input devices. The most common fixes are covered in [Troubleshooting](/help/troubleshooting/).

Opening `utter-gui` for the first time runs a mandatory **onboarding wizard** before the settings
shell appears. It walks through your **language**, the required **permissions**, your
push-to-talk **keys**, which **apps** Utter is allowed to act on, and a first **model**. Every
step can be skipped, progress is remembered across launches, and you can re-run the wizard any
time from Settings.

## 2. Set your push-to-talk keys

Utter has **two** push-to-talk keys, one per mode. Both are plain evdev key names and both are
set on the **Voice** page of the settings app, or under `[ptt]` in
`~/.config/utter/config.toml`:

```toml
[ptt]
dictation_key = "KEY_F13"
assistant_key = "KEY_INSERT"
```

| | Hold | What happens to your words | On screen |
|---|---|---|---|
| **Assistant** | the *assistant key* (Insert by default) | Turned into an action: open apps and sites, click things, press shortcuts | A yellow waveform |
| **Dictation** | the *dictation key* (F13 by default) | Typed into whatever field has focus | A blue waveform with "Dictation · typing" |

Each mode has its own start sound, so you can tell them apart without looking.

The defaults assume a keyboard remap that turns an awkward physical key into Insert or F13.
Most people will want keys that are actually on their keyboard. Any evdev name works
(`KEY_RIGHTCTRL`, `KEY_PAUSE`, `KEY_SCROLLLOCK`, ...). If you use `keyd`, the
[configuration guide](/guides/configuration/#keyd-remap) shows how to map Caps Lock and Right
Alt onto the defaults.

The key listener only needs your user to be in the `input` group. It never grabs the keyboard,
so the key keeps working for other apps too.

## 3. Pick a first model

Open the **Models** page. The **Recommended for your computer** section looks at your processor,
memory and graphics card and suggests one model per tier:

| Tier | What it does | Needed for |
|---|---|---|
| **Speech recognition** | turns your voice into text | everything you say |
| **Decision model** | chooses among prepared actions when no rule matches | fuzzier phrasing ("pull up youtube") |
| **Screen vision** | finds a described element on a screenshot | "click the search box" when accessibility fails |

Nothing is downloaded without you. Start with speech recognition: without it, the assistant key
has nothing to transcribe. The decision and vision models are optional and can be added later.

Press **Get it** next to a recommendation, or paste a source such as `hf:org/name` into
**Add a model**. Downloads resume if interrupted and are checked against their SHA-256 digest.
The [Models guide](/guides/models/) lists what is recommended for each GPU class and how the
model store works.

## 4. Say something

Hold the assistant key, say **"open youtube"**, release. A browser opens or an existing YouTube
tab is focused. Then try:

- "close this", "fullscreen", "workspace 3", "focus right" (window and workspace control)
- "pause", "next track" (any MPRIS media player)
- "new tab", "find" (the focused app's own shortcuts)
- "click the search box" (accessibility first, then vision if you installed it)

Hold the dictation key and talk to type into the focused field. Dictation never runs commands.

To see what Utter *would* do without doing it, use the dry run from a source checkout:

```bash
python3 -m utter.daemon --text "open youtube" --dry-run
```

## 5. Sleep mode

Say **"go to sleep"** in assistant mode and Utter frees your graphics card. The AI model
services stop, the speech model is unloaded, and only a tiny listener stays alive.
**Hold either push-to-talk key to wake it**: speech is back in a fraction of a second, and the
bigger models reload in the background.

Utter also falls asleep **by itself** after 15 minutes without being used. Only Utter activity
counts (a push-to-talk key, a spoken command, waking up), never typing or clicking in other
apps, so the graphics card is freed while you work. Waking is the same key press.

The phrase and the timer are yours to choose, on the **General** page or in the config file:

```toml
[sleep]
enabled = true
trigger = ["go to sleep", "take a break"]
services = ["utter-vision", "utter-planner"]   # what gets unloaded
unload_speech = true
on_idle = true                                 # sleep by itself when unused…
idle_minutes = 15                              # …after this long
```

:::note[Forthcoming: a loading state]
A `loading` state is being added to the on-screen display so the waveform can show the models
coming back after a wake or a cold start. It is **not shipped yet**.
:::

## Next steps

- [Configuration](/guides/configuration/) for every config section, speech backends, the
  decision head, vision and audio.
- [Apps and actions](/guides/apps-and-actions/) to edit an app's shortcuts or teach Utter a new
  application.
- [Trust and safety](/guides/trust-and-safety/) before you enable terminal commands or raw input.
