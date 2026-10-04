---
title: "Introduction"
description: "What Utter is, what it does, and the ideas behind it: rules first, a model that only chooses, and a desktop that never phones home."
---

Utter is a **local, context-aware voice → desktop-action assistant for Linux on Wayland and macOS**.
You hold a key, say what you want, and Utter turns it into something your desktop does:
open an app or a website, focus or close a window, switch workspace, play or pause media,
press an app's own shortcut, click a button it can see, or type your words into the focused field.

Everything runs on your machine. Speech recognition, the small AI models and the screenshots never leave it.

## What it does

| | |
|---|---|
| **Push-to-talk** | Hold the *assistant key* and speak, or hold the *dictation key* to type what you say into the field you started in (works on Linux and macOS). |
| **Desktop actions** | Open apps and websites, focus and close windows, switch workspaces, control media, press app shortcuts. |
| **Understands context** | Knows which app is focused and what is on screen, via accessibility information first and screenshots only as a last resort. |
| **Per-app actions you can edit** | 100+ app profiles once your installed apps are catalogued, with their shortcuts. Change any key combination from the settings app. |
| **Safe by default** | Risky abilities (terminal commands, raw input) stay off until you turn them on, and important actions ask first. |
| **Localised** | Ships 10 UI locales (en, es, de, fr, it, pt, zh, ja, ko, ru). The spoken language is a separate setting, so you can use a Spanish UI and speak English. |

## Rules first, the model only chooses

Most voice assistants hand your words to a large model and let it decide what to run. Utter does
the opposite, and that is the core design idea:

```text
  you speak ──▶ speech-to-text ──▶ router ──▶ safety policy ──▶ desktop actions
                 (local model)      │  rules first                  (keys, windows,
                                    │  then a small local AI          apps, media)
                                    ▼  that only *chooses*
                              app & screen context
```

1. **Deterministic rules go first.** Most commands ("open youtube", "close this", "workspace 3",
   "next track") are matched by fast, predictable rules. Multi-step plans such as focusing a
   window and then closing it are produced directly by the rules.
2. **A constrained decision head picks, it never writes.** When no rule matches, Utter builds a
   small list of *fully resolved* candidate actions (at most 12, plus a mandatory "none") and asks
   a tiny local model to choose one by letter. A choice below a confidence threshold counts as
   an abstention. The model cannot author its own arguments, so it cannot invent a command.
3. **A free-form planner is the last resort,** used only when rules and the decision head both
   fail. You can turn it off entirely.
4. **Perception is reached only when a step needs it.** "Click the search box" first tries the
   accessibility tree. Only if that fails does Utter take a screenshot and ask a local vision
   model where to click.

Utter picks the cheapest tier that can satisfy the intent:

| Tier | Name | Uses | Example |
|---|---|---|---|
| T0 | App | focused app and window, app profiles, URL handlers | "open youtube" with a browser focused opens the URL. No model, no screenshot. |
| T1 | Accessibility | the AT-SPI tree (role, name, actions) | "press the Play button" finds and invokes the node. No pixels. |
| T2 | Keyboard | per-app shortcuts | "new tab" presses `ctrl+t`. |
| T3 | Vision | a screenshot grounded by a local vision model | only when T0 to T2 cannot resolve the target. |

## Screen text can guide, never command

Everything Utter reads from your screen (window titles, accessibility names, OCR text, the
clipboard, web content) is tagged as **untrusted**. Untrusted content may only *select* between
options Utter has already prepared. It can never become the argument of an action, so a web page
cannot talk Utter into running a command or opening an arbitrary URL. The runner rejects any
request whose concrete arguments derive from screen content.

Risky abilities are off by default. Running terminal commands and sending raw keyboard or mouse
input must be enabled explicitly, and still ask for confirmation. Confirmation always shows the
concrete URL, command or target and is re-validated after you approve. Read more in
[Trust and safety](/guides/trust-and-safety/).

## Completely offline

**Nothing leaves your computer.** Speech is recognised locally, the AI models run locally, and
screenshots never leave the machine. There is no account and no telemetry.

The only time Utter goes online is when **you** download a model. If you deliberately point it
at a server on another machine, the settings app tells you so in amber.

Utter also works with **no models at all**. Rules, window state and accessibility handle the
deterministic commands. A speech model is needed for voice, and the vision and language models
are optional extras that unlock the fuzzier requests.

## How it is built

Under the hood a tiny **runner** supervises swappable **plugins** (speech, decision, perception,
actions, speech output, UI) over one versioned JSON-RPC protocol. The runner is the trust
boundary: it owns policy, confirmation and the data plane, and treats every plugin and its output
as untrusted.

- The core is Python and uses only the standard library.
- The settings app is Tauri v2 + React. It is a pure client: it edits the config file, shells
  out to the `assistant` CLI and drives systemd user units. No assistant logic lives there.
- The compositor integration targets **niri** first, with other Wayland compositors handled
  through generic tools.

See [Architecture](/reference/architecture/) for the full picture and the
[plugin protocol](/plugins/) if you want to extend it.

## Status

Utter is young software built with the help of AI coding assistants and reviewed by a human.
Read the code before trusting it with anything important, and please
[report anything that looks wrong](https://github.com/sujaisubbanna/utter-assistant/issues).
Linux x86_64 on Wayland and macOS are supported platforms (see [macOS](/guides/macos/)).
Windows is not supported.
