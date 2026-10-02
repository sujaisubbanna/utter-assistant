---
title: "FAQ"
description: "Short answers to the questions people ask first about Utter."
---

### Does anything leave my computer?

No. Speech recognition, the language and vision models and the screenshots all run and stay
locally. There is no account and no telemetry. The only network use is downloading a model when
**you** ask for one, and the one deliberate exception is pointing a model endpoint at a server on
another machine, which the settings app flags in amber.

### Do I need a GPU?

No. Utter works with no models at all for rule-matched commands, and speech recognition runs on
CPU with whisper.cpp. A GPU makes speech faster and is needed for the optional decision-head and
vision models. The comfortable setup for all three is a 16 GB or larger NVIDIA card; see
[Models](/guides/models/) for the recommendation per GPU class.

### Why did Utter go to sleep by itself?

By default Utter sleeps after 15 minutes without being used, so the graphics card is free while
you work on something else. Only *Utter* activity keeps it awake: a push-to-talk key, a spoken
command, or waking up. Typing or clicking in other apps does not count, and it never dozes off
while it is listening or carrying out a command. Hold either push-to-talk key to wake it; speech
is back in a fraction of a second and the bigger models reload in the background. Turn it off
or change the time under **Sleep when idle** on the General page, or set `[sleep] on_idle` and
`idle_minutes` in the config file.

### Does it work on X11, GNOME, KDE, Hyprland, sway?

Utter targets **Wayland**. **niri** and **KDE Plasma (KWin)** are first-class: a small compositor
layer detects which one is running and uses its native interface for window and workspace actions
(`niri msg` on niri, KWin's D-Bus interfaces on Plasma). Other Wayland compositors get partial
support — the generic tools it uses (`wtype`, `ydotool`, `grim`, `wl-clipboard`, PipeWire, MPRIS,
AT-SPI) work across compositors, so dictation, typing and launching work, but compositor-specific
actions (focus, move, workspaces) are not implemented for them. X11 is not supported.

### Windows or macOS?

**macOS is experimental** — native `Speech.framework` + whisper.cpp voice, Quartz push-to-talk and
injection, and an unsigned `.dmg`; it has not been tested on real Apple hardware. See
[macOS](/guides/macos/). **Windows is not supported** and has not been started.

### What is the difference between the assistant key and the dictation key?

Hold the **assistant key** and your words become an action. Hold the **dictation key** and your
words are typed into the focused field, nothing more. Each has its own sound and waveform colour.
See [Getting started](/getting-started/#2-set-your-push-to-talk-keys).

### Why Insert and F13 as defaults?

Because the reference setup remaps Right Alt to Insert and Caps Lock to F13 with keyd, which
gives two large, comfortable keys that nothing else uses. Change them on the Voice page to any
key you like.

### Can the AI run arbitrary commands?

No. Rules go first. When no rule matches, a small local model **chooses** among fully resolved
actions Utter has already prepared; it cannot write its own. Running terminal commands at all
is off by default, and anything derived from screen content can never become an argument. See
[Trust and safety](/guides/trust-and-safety/).

### Will `curl | bash` install things without asking?

Not on its own. Piped input is not a terminal, so the wizard cannot prompt: a bare pipe prints
the plan and exits without changing anything. Add `--yes` to accept the recommended defaults.
You can also read the script first; it is `install.sh` at the root of the repository.

### Does the installer download models?

Never on its own. The models step asks per tier and only pulls when you opt in and provide a
source. The settings app also downloads nothing until you press the button.

### How do I uninstall?

`./install.sh --uninstall` from a checkout, or the remote one-liner with `--uninstall`. Your
config and models are kept unless you remove them yourself. See
[Install from the web](/install/remote/#uninstall).

### Can I use my own language-model server?

Yes. Anything OpenAI-compatible works: vLLM, Ollama, llama.cpp. Set `[router] llm_base_url` and
`llm_model`, and `[vision] base_url` and `model`, or use the LLM and Perception pages.

### How do I teach it a new app?

Create a YAML profile in `~/.config/utter/profiles/` or edit the app on the **App actions**
page, then regenerate the catalog. See [Apps and actions](/guides/apps-and-actions/).

### Which languages does it speak?

The settings app and the installer ship 10 UI locales: English, Spanish, German, French,
Italian, Portuguese, Chinese, Japanese, Korean and Russian. The spoken language is a separate
setting (it defaults to your system locale), so you can use a Spanish UI and speak English.
Speech recognition depends on the model: the default is an English-only (`.en`) whisper model,
and you opt into a multilingual model (`small`, `large-v3-turbo`, …) from the settings app or the
installer. Utter never downloads a model on its own.

### Is Utter finished?

No. It is young software built with AI coding assistants and reviewed by a human. Read the code
before trusting it with anything important, and report anything that looks wrong.
