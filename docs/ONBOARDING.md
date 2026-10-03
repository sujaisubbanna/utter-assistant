# First-run onboarding

Utter opens a short setup wizard the first time you launch the settings app. It
walks through language, permissions, keys, the apps Utter may control, and the
models to run, then lets you try one command. It takes about two minutes.

The wizard **gates the app**: until it is finished, it replaces the settings
shell entirely, so you always land somewhere that helps get Utter working rather
than on a page that assumes it already is. It downloads nothing unless you
choose it, and only a small curated set of apps is enabled up front.

## The steps

The wizard has nine steps, in this order:

| Step | What it does |
|---|---|
| **Welcome** | What Utter does and that it runs entirely on your computer. Choose **Get started**, or **Skip setup for now** to go straight to the settings shell. |
| **Language** | Sets the **UI language** of the settings app — the system language or one of the 10 shipped locales. The rest of the wizard updates immediately as a preview. |
| **Intro** | A three-point tour: hold to talk, acts in your apps, stays on your computer. |
| **Permissions** | On macOS, the five privacy permissions with a **Grant access** button, a deep link to the exact System Settings pane, and a live status badge (see [macOS permissions](MACOS.md#first-run-permissions-in-settings)). On Linux, the state of the `utter-runner` background service with a Start/Restart button. |
| **Keys** | Picks the two push-to-talk keys: the **assistant key** (turns speech into an action) and the **dictation key** (types speech into the focused field). |
| **Apps** | Picks which apps Utter is allowed to control. Only a small curated set is preselected; every other installed app is off until you tick it (see [APPS.md](APPS.md#per-app-opt-in-gate)). |
| **Models** | Chooses what to run locally: **Recommended**, **Minimal**, or **Skip for now** (built-in rules only). Anything offered here is downloaded only if you pick it. |
| **First action** | Hold the assistant key, say one of the example commands, and release. A short chime tells you Utter is listening. |
| **Done** | A summary of the language, keys, apps and models you chose, and **Start using Utter**. |

## Skipping and resuming

Nothing in the wizard is mandatory:

- The **Welcome** step offers **Skip setup for now**, which finishes the wizard
  and opens the settings shell.
- The **Permissions**, **Keys**, **Apps** and **First action** steps each show a
  **Skip this step** link in the footer.
- The **Models** step has an explicit **Skip for now** choice.
- **Language** and **Intro** simply continue with their defaults (the system
  language).

Progress is saved after every step and every choice, so quitting, restarting or
a crash resumes at the step where you left off, with your earlier answers intact.

## Running it again

You can re-run the wizard from the settings app: the **General** page has a
**Run setup again** row. It clears the saved progress and starts from the
welcome step; it is safe to run at any time.

## Language has two independent axes

The wizard's **Language** step changes the **UI language** — the language of the
settings app itself. The **spoken language** (speech-to-text and spoken replies)
is a *separate* setting: it resolves from your system locale, or from
`[stt] language` / `[tts] language` in `config.toml`, which you can also set on
the **Voice** page. The two never have to match: you can run a Spanish UI and
speak English. English ships inline; other speech models are opt-in and are
never fetched automatically — see
[spoken language](CUSTOMISING.md#spoken-language-stt--tts).

## For contributors

In a development build the wizard can be opened straight to a step with
`?onboarding=<step>` (for example, `?onboarding=5` for the apps step), which is
handy for screenshots and manual checks.
