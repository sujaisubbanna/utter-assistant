---
title: "How Utter compares"
description: "How Utter compares with Talon, Wispr Flow, Aqua Voice, Handy, Vocalinux and Leon — a source-checked table, what makes Utter different, and where Utter is honestly behind."
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
- **Rules first, and a model that only chooses.** Utter's model may *select among fixed
  candidates*; it cannot author action arguments from untrusted screen content. This is the named
  **Action-Selector Pattern**, a formally studied prompt-injection defence, and it aligns with the
  OWASP LLM01 mitigations for prompt injection.
- **Open source and local** — unlike Talon's closed source, with its automatic crash reports and
  optional usage metrics.
- **Honest local peers, not just competitors.** Handy, Vocalinux and YazSes are doing the same
  local-first work; see the note below.

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
