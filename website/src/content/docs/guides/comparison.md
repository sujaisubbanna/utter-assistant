---
title: "How Utter compares"
description: "How Utter compares with Talon, Wispr Flow, Aqua Voice, Handy, Vocalinux, Leon, Jarvis-style projects and OS-native assistants — a source-checked table, what makes Utter different, and where Utter is honestly behind."
---

Utter is a **local, offline, context-aware voice → desktop-action assistant**. You hold a key,
say what you want, and it acts on your desktop: opening apps and sites, focusing and closing
windows, switching workspaces, controlling media and pressing an app's own shortcuts. It runs
natively on **Linux on Wayland** (niri and KDE Plasma/KWin) and on **macOS**.

This page compares Utter with other voice tools. Every claim below is checked against a primary
source, listed at the end. Where a fact is uncertain, it is left out. Where Utter is behind, it
is said plainly.

## At a glance

| Tool | Open source | Local/offline | Platforms | Voice → actions? |
|---|---|---|---|---|
| **Utter** | Yes — Apache-2.0 | Local by default; no cloud | Linux (Wayland: niri, KDE/KWin) + macOS | Yes |
| **Talon Voice** | No — proprietary (source/binaries are trade secrets per the EULA) | Local; automatic crash reports + optional usage metrics | macOS / Windows; **Linux/X11 only, no Wayland** (free Linux/X11 releases end after Talon 1.0) | Yes — deep voice→desktop control |
| **Wispr Flow** | No — proprietary | **Cloud-only** ("Transcription always happens in the cloud") | macOS / Windows / Android | No — dictation |
| **Aqua Voice** | No — proprietary | **Cloud** (Privacy Mode is storage only; no offline mode) | macOS / Windows / iPhone | No — dictation |
| **Handy** | Yes — MIT | **Fully offline** | Windows / macOS / Linux (Wayland "limited support") | No — dictation only |
| **Vocalinux** | Yes — AGPL-3.0 | **100% offline** | Linux (X11 + Wayland) | No — dictation only |
| **Leon** | Yes — MIT | Local-first assistant | Linux / macOS / Windows | Assistant — **2.0 Developer Preview** |

Other local-capable dictation apps exist, such as superwhisper, Willow and MacWhisper. They are
proprietary, and they are best described as **local-capable** rather than fully offline.

## What makes Utter different

- **Native Linux Wayland (niri, KDE/KWin).** Talon Voice does not support Wayland, and its free
  Linux/X11 releases end after Talon 1.0.
- **Local by default, no cloud required.** Unlike Wispr Flow, which is cloud-only, and Aqua Voice,
  which is cloud-based with no offline mode, Utter's speech, models and screenshots stay on your
  machine.
- **Rules first, and a model that only chooses.** The decision head picks from a fixed list of
  prepared candidates and cannot write an action's arguments; see *Nothing on your screen can
  author an action* below.
- **Open source and local** — unlike Talon's closed source, with its automatic crash reports and
  optional usage metrics.
- **Honest local peers, not just competitors.** Handy, Vocalinux and YazSes are doing the same
  local-first work; see the note below.

## Nothing on your screen can author an action

Utter labels every value that can influence an action with its **provenance** — where that value
came from. Your spoken command and explicit input in the settings app are `user` and **trusted**.
Anything read from the screen — the accessibility tree, OCR, window titles, the clipboard or a web
page — is `screen` and **untrusted**. Untrusted content may try to influence a choice, but it can
never write the action's arguments: it can only **select among candidates Utter already prepared**.

The guarantee is **structural**, enforced by the **runner** (the trust boundary) rather than
merely asked of the model in a prompt. Screen text is never turned into a `terminal` command or an
arbitrary `open_url` scheme, and arguments that derive from `screen` provenance are rejected by
policy before anything runs. This resembles the named **Action-Selector Pattern**, a formally
studied defence against prompt injection, and is adjacent to the OWASP LLM01 mitigations. The big
vendors' own guidance treats on-screen content as untrusted and recommends confirmation for
consequential actions; Utter makes the restriction part of the mechanism rather than a
probabilistic filter.

- **Provenance tagging.** Every action-influencing value is marked `user` (trusted) or `screen`
  (untrusted), so the runner always knows the source.
- **Select, never author.** Untrusted content **may only choose among precomputed candidates**; it
  may **never create new arguments** for an action.
- **The model picks by letter.** On any model-driven path the constrained decision head
  (`llm.choose`) is **non-optional**: it chooses from a fixed list, it does not write the action.
- **Rejected by policy.** A request whose concrete arguments come from `screen` provenance is
  refused with error **`-32006`** before any plugin is called.
- **Titles and URLs are contained.** Titles are truncated and sanitised, and `open_url` allows only
  `http`, `https` and `mailto`.
- **Consequential actions ask first, with the details.** Confirmation is argument-bearing — it
  shows the concrete URL, command or target — and the target is re-validated after you approve it
  (this closes the "time-of-check to time-of-use", or TOCTOU, gap).

## Jarvis-style assistants

Most projects named "Jarvis" are LLM/chat demos or single-purpose command scripts, not general
local assistants that act on your computer. A few are real — and none combine Utter's pillars.

| Project | What it is | Local | Voice | Desktop actions | Status |
|---|---|---|---|---|---|
| `isair/jarvis` | Local voice assistant, MCP tools, offline dictation | Yes (Ollama) | Yes | Partial — reads screen, controls Chrome; macOS-first, not OS-wide | Active |
| `PersonalJarvis` (`PersonalJarvis/PersonalJarvis`) | Voice + computer-use (perceive-act-verify) | Per-layer, keyless local options | Yes | Yes — mouse/keyboard via vision loop | New / small |
| `Open Interpreter 01` (`OpenInterpreter/01`) | OSS voice interface for devices | Self-hostable | Yes | Yes — experimental, no safeguards | **Dormant since 2024** |
| `OpenJarvis` (`open-jarvis/OpenJarvis`) | Local-first agent framework (tools/memory) | Yes (Ollama) | TTS only | No — not app control | Active |

Being named after a film assistant is not the same as being one. `microsoft/JARVIS` is the
HuggingGPT **research** orchestrator — it chains models, it is not a desktop assistant. Several
popular repositories called "Jarvis" are command scripts rather than AI assistants at all; one
describes itself as "non-AI". That is a legitimate project, just a different category.

The OS-native assistants are the obvious place to look for desktop control — Apple
Intelligence/Siri, Microsoft Copilot (Actions / Click to Do), Google Gemini desktop and ChatGPT
desktop Computer Use — but they are **cloud or hybrid** rather than local-first, and their desktop
actions are LLM-driven.

The honest point: even the "Jarvis" genre generally lets the **LLM author the action**, through
vision and perceive-act loops. Utter's difference is narrower than "better": it uses a
**constrained select-among-candidates** model, adds **compositor-aware context**, and keeps actions
behind **per-app opt-in**. Those are specific design differences, not a claim that Utter wins
everywhere.

## Other local-first options we respect

These projects share Utter's preference for running on your own machine, and are worth a look:

- **Handy** — MIT-licensed, fully offline dictation for Windows, macOS and Linux. As with most
  tools, its Wayland support is described as "limited".
- **Vocalinux** — AGPL-3.0, 100% offline dictation for Linux, on X11 and Wayland.
- **YazSes** — Apache-2.0. Note that its "commands" map to editor and terminal key sequences,
  not app launching, and its SLM router is **not yet wired up**; it does not have a working LLM
  intent router today.

## Where Utter is behind

Honesty matters more than a sales pitch, so here is what Utter does not have yet:

- **No Windows support yet.**
- **No streaming partial transcripts yet** — recognition is utterance-based.
- **No wake word yet.**
- **No cloud or hybrid mode**, and no mobile companion app.
- **Smaller intent and app coverage** than mature tools such as Talon's community.

## Sources

Primary sources for the claims on this page:

- Talon Voice changelog (Linux/X11 and Wayland status):
  [talonvoice.com/dl/latest/changelog.html](https://talonvoice.com/dl/latest/changelog.html)
- Talon Voice EULA (proprietary source/binaries; crash reports and metrics):
  [talonvoice.com/EULA.txt](https://talonvoice.com/EULA.txt)
- Wispr Flow privacy (transcription in the cloud):
  [wisprflow.ai/privacy](https://wisprflow.ai/privacy)
- Aqua Voice privacy (cloud; Privacy Mode is storage only):
  [aquavoice.com/info/privacy](https://aquavoice.com/info/privacy)
- The Action-Selector Pattern paper:
  [arxiv.org/abs/2506.08837](https://arxiv.org/abs/2506.08837)
- OWASP LLM01: Prompt Injection:
  [genai.owasp.org/llmrisk/llm01-prompt-injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- `isair/jarvis`:
  [github.com/isair/jarvis](https://github.com/isair/jarvis)
- `PersonalJarvis/PersonalJarvis`:
  [github.com/PersonalJarvis/PersonalJarvis](https://github.com/PersonalJarvis/PersonalJarvis)
- `OpenInterpreter/01`:
  [github.com/OpenInterpreter/01](https://github.com/OpenInterpreter/01)
- `open-jarvis/OpenJarvis`:
  [github.com/open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
- `microsoft/JARVIS` (HuggingGPT research orchestrator):
  [github.com/microsoft/JARVIS](https://github.com/microsoft/JARVIS)
- Utter's own trust model (provenance, select-never-author, `-32006`, confirmation):
  [github.com/sujaisubbanna/utter-assistant/blob/main/docs/TRUST.md](https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/TRUST.md)
