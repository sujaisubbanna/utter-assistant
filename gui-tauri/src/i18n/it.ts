import type { Messages } from "./en";

/** it — Crowdin-imported. Keys mirror `en.ts`; missing values fall back.
 *  Unreviewed unless a fluent speaker has checked it (docs/TRANSLATING.md). */
export const it: Messages = {
  "app": {
    "name": "Utter",
    "tagline": "Your voice, turned into actions on your desktop.",
    "settings": "Settings"
  },
  "common": {
    "refresh": "Refresh",
    "retry": "Try again",
    "save": "Save",
    "cancel": "Cancel",
    "close": "Close",
    "enable": "Turn on",
    "disable": "Turn off",
    "on": "On",
    "off": "Off",
    "use": "Use this",
    "test": "Test",
    "copy": "Copy",
    "copied": "Copied",
    "clear": "Clear",
    "remove": "Remove",
    "download": "Download",
    "install": "How to install",
    "website": "Website",
    "learnMore": "Learn more",
    "details": "Details",
    "showDetails": "Show details",
    "hideDetails": "Hide details",
    "default": "Default",
    "unknown": "Unknown",
    "none": "None",
    "loading": "Loading…",
    "somethingWrong": "Something went wrong",
    "runnerUnavailable": "Utter's background assistant isn't running. Open Set up or General and start it.",
    "notInstalled": "Not installed",
    "installed": "Installed",
    "recommended": "Recommended",
    "advanced": "Advanced",
    "savedTo": "Settings are saved automatically.",
    "commaHint": "Separate items with commas.",
    "saveFailed": "Couldn't save {what}: {error}",
    "ms": "ms",
    "px": "px"
  },
  "modelRequired": {
    "title": "You need a model first",
    "sttBody": "Speech recognition needs a model. Get the recommended one, or let your engine fetch it when you first dictate.",
    "visionBody": "Screen vision needs a model on this computer. Get the recommended one, then turn it on.",
    "action": "Get a model",
    "recommended": "Recommended",
    "size": "About {size}",
    "storeLabel": "Saved to",
    "estimatedNote": "We couldn't check your hardware, so this is a safe default.",
    "sttNote": "Your speech engine can also download it the first time you dictate.",
    "noSourceNote": "Set this model up from the Models page.",
    "shardedNote": "These are sharded models, so Utter downloads and sets them up for you.",
    "notNow": "Not now",
    "openModels": "Open Models",
    "download": "Download",
    "downloading": "Downloading…",
    "progress": "{done} of {total}",
    "starting": "Starting the download…",
    "stop": "Stop",
    "failedTitle": "Download failed",
    "failedBody": "The download didn't finish. Check your connection and try again.",
    "retry": "Try again",
    "doneTitle": "Model ready",
    "doneBody": "{name} is ready to use.",
    "done": "Done"
  },
  "nav": {
    "sections": "Sections",
    "groups": {
      "essentials": "Essentials",
      "understanding": "Understanding",
      "advanced": "Advanced"
    },
    "general": "General",
    "voice": "Voice",
    "models": "Models",
    "llm": "AI model",
    "apps": "App actions",
    "tts": "Spoken replies",
    "perception": "Screen",
    "plugins": "Plugins",
    "safety": "Safety",
    "diagnostics": "Troubleshooting",
    "about": "About",
    "setup": "Settings"
  },
  "theme": {
    "label": "Theme",
    "light": "Light",
    "dark": "Dark",
    "system": "System",
    "matugen": "Desktop colours",
    "desktop": "Use desktop colours",
    "desktopHint": "Match your Matugen palette instead of the default grey and yellow.",
    "desktopMissing": "No Matugen palette found for this theme."
  },
  "language": {
    "label": "Language",
    "description": "Used for this window.",
    "system": "Match system ({name})"
  },
  "onboarding": {
    "step": "Step {current} of {total}",
    "skipStep": "Skip this step",
    "skipSetup": "Skip setup",
    "back": "Back",
    "next": "Continue",
    "finish": "Start using Utter",
    "rerun": "Run setup again",
    "rerunHint": "Walk through the first-run steps again.",
    "welcome": {
      "eyebrow": "Welcome",
      "title": "Your voice, turned into actions.",
      "body": "Utter listens while you hold a key, works out what you mean and does it — all on your computer. Nothing is uploaded. This takes about two minutes.",
      "start": "Get started",
      "skip": "Skip setup for now",
      "privacy": "Private by design · runs entirely on your computer"
    },
    "language": {
      "eyebrow": "Language",
      "title": "Choose your language",
      "body": "This changes the language of these settings. You can change it later."
    },
    "intro": {
      "eyebrow": "What Utter does",
      "title": "Speak, and it's done",
      "body": "Utter turns a spoken request into an action in the app you're already using.",
      "listenTitle": "Hold to talk",
      "listenBody": "Nothing is recorded unless you hold your key.",
      "actTitle": "Acts in your apps",
      "actBody": "Opens pages, presses shortcuts and types what you say.",
      "privateTitle": "Stays on your computer",
      "privateBody": "Speech and screen never leave your machine."
    },
    "permissions": {
      "eyebrow": "Permissions",
      "title": "A few permissions to go",
      "bodyMac": "macOS asks for each one the first time. Utter only uses them while you're talking to it.",
      "bodyLinux": "Utter runs as a background service. Start it here so it's ready when you are.",
      "runnerTitle": "Assistant service",
      "running": "Running",
      "stopped": "Not running yet",
      "missing": "Not installed",
      "start": "Start assistant",
      "restart": "Restart",
      "linuxNote": "If it won't start, run this in a terminal: systemctl --user enable --now utter-runner.service",
      "grantedCount": "{granted} of {total} granted",
      "allGranted": "Everything is granted.",
      "continueAnyway": "Continue anyway",
      "unavailable": "Couldn't check permissions"
    },
    "keys": {
      "eyebrow": "Shortcut keys",
      "title": "Pick your keys",
      "body": "Hold a key to talk. Choose keys you don't use for anything else.",
      "assistant": "Assistant key",
      "assistantHint": "Turns what you say into an action.",
      "dictation": "Dictation key",
      "dictationHint": "Types what you say into the focused field.",
      "change": "Change",
      "capture": "Press any key",
      "captureHint": "Press Esc to cancel.",
      "modifier": "Modifier",
      "notSet": "Not set",
      "conflict": "Choose two different keys.",
      "linuxNote": "On Linux a function key such as F13 is a good choice — nothing else uses it.",
      "macNote": "Right ⌘ and Right ⌥ are good defaults; nothing else uses them alone."
    },
    "apps": {
      "eyebrow": "Apps",
      "title": "Which apps should Utter control?",
      "body": "Deselect anything you'd rather keep to yourself. Common apps are already selected.",
      "recommended": "Recommended",
      "installed": "Other installed apps",
      "selected": "{count} selected",
      "selectAll": "Select all",
      "showAll": "Show all installed apps",
      "showFewer": "Show recommended only",
      "loading": "Looking for installed apps…",
      "emptyTitle": "No apps found",
      "emptyBody": "You can add apps later from the App actions page.",
      "loadError": "Couldn't load your apps",
      "fallbackNote": "Showing names and types. App icons and detection arrive with the next update."
    },
    "models": {
      "eyebrow": "Models",
      "title": "Choose your models",
      "body": "The models run on your computer. Pick what fits — you can add or remove them later from the Models page.",
      "recommendedTitle": "Recommended",
      "recommendedBody": "The best balance of speed and accuracy for this computer.",
      "minimalTitle": "Minimal",
      "minimalBody": "The smallest download. Good if you're short on space.",
      "skipTitle": "Skip for now",
      "skipBody": "Use the built-in rules and download models later.",
      "badge": "Recommended",
      "total": "About {size} to download",
      "includes": "Includes",
      "willFetch": "Fetched by the engine on first use.",
      "installed": "Already installed",
      "sizeUnknown": "Size unknown",
      "progress": "Downloading {done} of {total}",
      "done": "Models are ready.",
      "failed": "Download failed: {error}",
      "detectFailed": "Couldn't check this computer, so the recommendation may be a guess.",
      "stt": "Speech recognition · {model}",
      "decision": "Decision model · {model}",
      "vision": "Screen vision · {model}",
      "rules": "Built-in rules only",
      "runtimeTitle": "Install what Utter needs",
      "runtimeBody": "Screen vision, planning and the speech model. Utter downloads and sets them up for you.",
      "runtimeSize": "About 8 GB in total",
      "required": "Required",
      "sttRequiredNote": "The speech model is required. Utter can't listen without it, so it can't be skipped.",
      "installNow": "Install and continue",
      "installLater": "Install later",
      "installLaterHint": "If you install later, setup stays unfinished until the speech model is ready.",
      "runtimePlanner": "Planner: {backend} · {model}"
    },
    "firstAction": {
      "eyebrow": "One more thing",
      "title": "Try your first command",
      "body": "Hold {key}, say one of these, then let go.",
      "example1": "open youtube",
      "example2": "search for a coffee shop",
      "example3": "type hello world",
      "tip": "A short chime tells you Utter is listening."
    },
    "done": {
      "eyebrow": "All set",
      "title": "You're ready to talk",
      "body": "Hold {key} and say what you want to do.",
      "summaryLanguage": "Language",
      "summaryKeys": "Keys",
      "summaryApps": "Apps",
      "summaryModels": "Models",
      "modelsRecommended": "Recommended",
      "modelsMinimal": "Minimal",
      "modelsSkip": "Built-in rules"
    }
  },
  "engine": {
    "missing": {
      "eyebrow": "Get the engine",
      "title": "Install the Utter engine",
      "body": "This app is only the settings shell. Install the engine to hear you, decide and act. Copy the command below, or open it in a terminal for me.",
      "short": "Utter's engine isn't installed yet — install it below.",
      "openTerminal": "Open installer in terminal",
      "opened": "Opening your terminal…",
      "copyFailed": "Couldn't copy the command",
      "openFailed": "Couldn't open a terminal: {error}"
    }
  },
  "status": {
    "checking": "Checking…",
    "online": "Assistant running",
    "offline": "Assistant stopped",
    "plugins": {
      "one": "{count} plugin",
      "other": "{count} plugins"
    }
  },
  "titlebar": {
    "minimize": "Minimise",
    "maximize": "Maximise",
    "close": "Close"
  },
  "privacy": {
    "badge": "Offline",
    "badgeRemote": "Remote server in use",
    "badgeTitle": "Everything runs on your computer",
    "title": "Completely offline",
    "body": "Your voice, your screen and everything you ask stay on your computer. Nothing is uploaded, ever.",
    "points": {
      "voice": "Speech is recognised here",
      "screen": "Screenshots never leave",
      "account": "No account, no tracking"
    },
    "fine": "Utter only goes online when you download a model.",
    "remoteTitle": "Almost offline",
    "remoteBody": "You've pointed {list} at a server outside your computer, so those requests leave it.",
    "review": "Review",
    "parts": {
      "llm": "the AI model",
      "vision": "screen vision",
      "stt": "speech recognition"
    }
  },
  "splash": {
    "loading": "Getting ready…",
    "promise": "Private by design · runs entirely on your computer"
  },
  "states": {
    "configLoading": "Loading your settings…",
    "configErrorTitle": "Your settings couldn't be loaded",
    "configErrorBody": "The settings file may be missing or damaged. Try again, or check the Troubleshooting page."
  },
  "general": {
    "title": "General",
    "description": "Start the assistant, choose how you talk to it, and make it yours.",
    "hero": {
      "runningTitle": "The assistant is running",
      "runningBody": "Hold your assistant key and say what you want to do.",
      "stoppedTitle": "The assistant isn't running",
      "stoppedBody": "Start it to use voice commands. It only listens while you hold a key.",
      "checkingTitle": "Checking the assistant…",
      "checkingBody": "This takes a second.",
      "start": "Start assistant",
      "restart": "Restart",
      "socket": "Connection"
    },
    "startup": {
      "title": "Startup",
      "description": "What happens when you log in.",
      "login": "Start when I log in",
      "loginOn": "The assistant starts automatically with your desktop.",
      "loginOff": "You'll need to start the assistant yourself.",
      "loginMissing": "The assistant service isn't installed yet.",
      "loginState": "Current state: {state}"
    },
    "trigger": {
      "title": "How you talk to it",
      "description": "Choose what starts listening.",
      "label": "Listening method",
      "hint": "Hold a key to talk.",
      "hotkey": "Hold a key to talk"
    },
    "sleep": {
      "title": "Sleep mode",
      "description": "Free your graphics card when you're not using Utter. Hold either key to wake it.",
      "enable": "Sleep on command",
      "enableHint": "Say a trigger phrase in assistant mode to unload the AI models.",
      "trigger": "Trigger phrases",
      "triggerHint": "Say one exactly, e.g. “go to sleep”. Separate phrases with commas.",
      "speech": "Unload speech too",
      "speechHint": "Frees the most memory. Speech reloads in a fraction of a second on wake.",
      "idle": "Sleep when idle",
      "idleHint": "Go to sleep by itself when you haven't used Utter for a while. Typing or clicking elsewhere doesn't count.",
      "idleMinutes": "Idle time",
      "idleMinutesHint": "Minutes without a push-to-talk key or a spoken command before Utter sleeps.",
      "minutesUnit": "min"
    },
    "appearance": {
      "title": "Appearance",
      "description": "Colours follow your desktop when a Matugen palette is available.",
      "theme": "Theme",
      "themeHint": "Light, dark, or follow your system."
    },
    "services": {
      "title": "Background services",
      "description": "The pieces that run the assistant. Updated live.",
      "control": "Manage {name}",
      "start": "Start",
      "restart": "Restart",
      "stop": "Stop",
      "notInstalled": "Not installed",
      "active": "Running",
      "failed": "Stopped with an error",
      "starting": "Starting…",
      "inactive": "Stopped",
      "checking": "Checking…",
      "readError": "Couldn't read the service status: {error}",
      "done": "{action}: {name}",
      "failedAction": "Couldn't {action} {name}: {detail}"
    },
    "serviceNames": {
      "runner": "Assistant core",
      "runnerDesc": "Runs plugins and enforces your safety rules",
      "vision": "Screen vision",
      "visionDesc": "Finds things on screen from a screenshot",
      "planner": "Planner",
      "plannerDesc": "Small AI model that plans multi-step actions",
      "audio": "Audio setup",
      "audioDesc": "Applies your microphone and speaker choice"
    },
    "footer": "Changes are saved straight away to {path}. Your comments in that file are kept."
  },
  "apps": {
    "title": "App actions",
    "description": "What the assistant can do inside each app. Change a key combination if you've customised an app.",
    "pendingTitle": "Your edits are saved, but not used yet",
    "pendingBody": "Changes are stored in {path}. The assistant starts using them after its next update.",
    "search": "Search apps",
    "filters": {
      "all": "All installed",
      "edited": "Edited",
      "curated": "Main apps"
    },
    "listTitle": {
      "one": "{count} app",
      "other": "{count} apps"
    },
    "listDescription": "Common apps and your own. Click one to see and edit its actions, or switch to “All installed”.",
    "actions": {
      "one": "{count} action",
      "other": "{count} actions"
    },
    "edited": "Edited",
    "yours": "Yours",
    "curated": "Hand-tuned",
    "emptyTitle": "No apps match",
    "emptyBody": "Try a different name, or clear the filter.",
    "loadError": "Couldn't load the app list",
    "editor": {
      "title": "{name}",
      "description": "Say “{example}” and the assistant presses the matching keys in this app.",
      "names": "Names you can say",
      "namesHint": "Separate names with commas.",
      "actions": "Actions",
      "actionsHint": "Each action is a key combination, like ctrl+t or alt+left.",
      "action": "Action",
      "keys": "Keys",
      "changed": "Changed",
      "added": "Added",
      "remove": "Remove {name}",
      "add": "Add action",
      "newName": "action_name",
      "newKeys": "ctrl+shift+k",
      "searchUrl": "Search address",
      "searchUrlHint": "Used for “search … in this app”. Must contain {q}.",
      "launch": "Opens with",
      "reset": "Restore built-in",
      "saved": "Saved actions for {name}",
      "saveFailed": "Couldn't save: {detail}",
      "resetDone": "Restored built-in actions for {name}",
      "noActions": "This app has no key actions yet. Add one below."
    },
    "kinds": {
      "browser": "Browser",
      "editor": "Editor",
      "media": "Media",
      "chat": "Chat",
      "terminal": "Terminal",
      "game": "Game",
      "filemanager": "Files",
      "other": "App"
    }
  },
  "voice": {
    "title": "Voice",
    "description": "The keys you hold to talk, how speech is recognised, and which microphone is used.",
    "keys": {
      "title": "Push-to-talk keys",
      "description": "Hold a key, speak, then let go.",
      "dictation": "Dictation key",
      "dictationHint": "Types what you say into the focused field.",
      "assistant": "Assistant key",
      "assistantHint": "Turns what you say into an action.",
      "change": "Change",
      "modifier": "Modifier",
      "notSet": "Not set",
      "modalTitle": "Set the {name}",
      "press": "Press any key",
      "current": "Current key",
      "escape": "Press Esc to cancel. Modifier keys like Ctrl work too.",
      "unmapped": "That key can't be used ({code}). Try another one."
    },
    "stt": {
      "title": "Speech recognition",
      "description": "Runs on your computer — your voice never leaves it.",
      "engine": "Engine",
      "engineHint": "Faster-whisper is a good default on most machines.",
      "model": "Model",
      "modelHint": "Bigger models are more accurate but slower.",
      "language": "Language",
      "languageHint": "A code like en-GB or de-DE, or auto to follow your system language.",
      "mismatch": {
        "title": "This model only understands English",
        "body": "Your spoken language is {language}, but {model} is an English-only model. Pick a multilingual model to switch to:",
        "use": "Use {model} ({size})",
        "downloadHint": "The model is downloaded by your speech engine on first use; nothing is fetched until you choose."
      },
      "device": "Run on",
      "deviceHint": "Use your graphics card (CUDA) if you have one.",
      "none": "None (transcription disabled)",
      "remote": "Remote server",
      "getEngine": "Get {name}"
    },
    "mic": {
      "title": "Microphone",
      "description": "Pick the microphone and check that it hears you.",
      "device": "Input device",
      "deviceHint": "“Default” follows your system sound settings.",
      "defaultInput": "Default microphone",
      "noList": "Couldn't list microphones, so your system default will be used.",
      "level": "Input level",
      "levelIdle": "Start the test and speak — the bar should move.",
      "levelLive": "Listening… speak normally.",
      "startTest": "Test microphone",
      "stopTest": "Stop test",
      "startError": "Couldn't open the microphone"
    },
    "tip": {
      "title": "Try it",
      "body": "Click into any text field, hold your dictation key, say a sentence and let go."
    },
    "mac": {
      "description": "The keys you hold to talk and how speech is recognised, using your Mac's own frameworks.",
      "keysDescription": "Hold a key, speak, then let go. Right ⌘ and Right ⌥ are good defaults because nothing else uses them alone.",
      "escape": "Press Esc to cancel. A single modifier such as Right ⌥ works best.",
      "hotkeyBackend": "Key listener",
      "hotkeyBackendHint": "Quartz is built in; pynput is a fallback if the event tap can't be created.",
      "quartz": "Quartz event tap (recommended)",
      "sttDescription": "Apple's recogniser runs on the device; whisper.cpp is the offline fallback.",
      "engineHint": "Apple Speech needs no model download and is fast. whisper.cpp is more accurate for long sentences.",
      "appleSpeech": "Apple Speech (on device)",
      "fallback": "Fallback engine",
      "fallbackHint": "Used when the first engine can't start, for example before Speech Recognition is granted.",
      "locale": "Language",
      "localeHint": "A locale such as en-US or es-ES with an on-device dictation model installed.",
      "onDevice": "Keep recognition on this Mac",
      "onDeviceHint": "Never send audio to Apple's servers. Needs the language downloaded in Keyboard → Dictation.",
      "modelHint": "A whisper.cpp model name such as small.en, or a path to a ggml file.",
      "micDescription": "Which microphone to record from.",
      "deviceHint": "Leave empty for the system default input, or paste a device name from Audio MIDI Setup.",
      "tip": "Click into any text field, hold Right ⌥, say a sentence and let go."
    }
  },
  "dictation": {
    "title": "Where should this go?",
    "description": "No text field was selected, so your dictation wasn't typed anywhere.",
    "transcriptLabel": "You said",
    "windowsLabel": "Send to a window",
    "focused": "Focused",
    "unknownApp": "Unknown app",
    "noWindows": "No open windows were found. You can copy the text instead.",
    "windowsError": "Couldn't list open windows.",
    "typeSelected": "Type into selected",
    "dismiss": "Dismiss",
    "typeFailed": "Couldn't type into that window. It may have closed — try another.",
    "copyFailed": "Couldn't copy to the clipboard",
    "typed": "Typed into the selected window"
  },
  "setup": {
    "title": "Set up your Mac",
    "description": "Utter needs a few permissions before it can listen, type and act. Grant them once; this page checks them live.",
    "linuxTitle": "Set up Linux",
    "linuxDescription": "The installer sets up the Utter runner as a background service. Check it here and start it if it isn't running.",
    "linuxNote": "If the runner won't start here, run this in a terminal: systemctl --user enable --now utter-runner.service",
    "linuxInstallBody": "Utter is installed and updated from the project repo with install/install.sh.",
    "hero": {
      "title": "A few permissions to go",
      "body": "macOS asks for each one the first time. If a prompt doesn't appear, open System Settings from the row and switch Utter on.",
      "doneTitle": "You're all set",
      "doneBody": "Hold {assistant} and say what you want to do, or hold {dictation} to dictate into any text field.",
      "progress": "{granted} of {total} granted"
    },
    "permissions": {
      "title": "Permissions",
      "description": "System Settings → Privacy & Security. Each one unlocks one thing.",
      "unavailable": "Couldn't check permissions",
      "microphone": "Microphone",
      "microphoneWhy": "Hear you while a push-to-talk key is held. Nothing is recorded otherwise.",
      "speech": "Speech Recognition",
      "speechWhy": "Turn your voice into text with Apple's on-device recogniser.",
      "inputMonitoring": "Input Monitoring",
      "inputMonitoringWhy": "Notice when you press and release the push-to-talk keys.",
      "accessibility": "Accessibility",
      "accessibilityWhy": "Type dictated text, press shortcuts and read the focused window's title.",
      "screenRecording": "Screen Recording",
      "screenRecordingWhy": "Take a screenshot only when an action has to find something on screen.",
      "other": "Permission",
      "otherWhy": "Needed by the assistant."
    },
    "status": {
      "granted": "Granted",
      "denied": "Not granted",
      "notAsked": "Not asked yet",
      "unknown": "Unknown",
      "installed": "Installed"
    },
    "runtime": {
      "sectionTitle": "Assistant",
      "sectionDescription": "The assistant and its Python runtime live inside this app and are unpacked into your Library folder.",
      "title": "Assistant runtime",
      "installing": "Installing…",
      "installed": "Version {version}, installed in {dir}.",
      "notInstalled": "Not installed yet. This takes a few seconds.",
      "notBundled": "This build has no bundled runtime; it uses the checkout at {repo}.",
      "updateAvailable": "Version {current} installed; this app ships {next}.",
      "install": "Install",
      "update": "Update",
      "reinstall": "Reinstall",
      "done": "Assistant installed and started.",
      "failed": "Install failed: {error}"
    },
    "actions": {
      "grant": "Grant access",
      "openSettings": "Open System Settings",
      "requestFailed": "Couldn't ask for the permission: {error}"
    },
    "agent": {
      "title": "Background agents",
      "description": "Two small launchd agents run at login: the plugin runner and the voice assistant.",
      "runner": "Plugin runner",
      "assistant": "Voice assistant",
      "running": "Running.",
      "stopped": "Installed but not running.",
      "notInstalled": "Not installed yet. Install it to run at login.",
      "startFailed": "Couldn't start it: {detail}"
    },
    "note": {
      "process": "Permissions are granted to Utter (this app). The assistant runs inside it, so one grant covers the prompts, the background agent and this page.",
      "install": "If a permission stays off after you switch it on, restart the assistant from the row above."
    }
  },
  "models": {
    "title": "Models",
    "description": "The AI models stored on your computer. Download, check and remove them here.",
    "installed": {
      "title": "Installed",
      "description": "Stored in {path}.",
      "emptyTitle": "No models yet",
      "emptyBody": "The assistant still works with built-in rules. Add a recommended model below for smarter results.",
      "meta": "{size} · {files}",
      "files": {
        "one": "{count} file",
        "other": "{count} files"
      },
      "remove": "Remove",
      "removeTitle": "Remove this model?",
      "removeBody": "{name} will be deleted from your computer. You can download it again later.",
      "removed": "Removed {name}",
      "removeFailed": "Couldn't remove it: {detail}",
      "loadError": "Couldn't read the model list"
    },
    "recommended": {
      "title": "Recommended for your computer",
      "description": "Based on your processor, memory and graphics card. Nothing is installed without you.",
      "detect": "Check again",
      "detecting": "Looking at your hardware…",
      "ram": "{ram} GB memory",
      "noGpu": "No graphics card found",
      "stt": "Speech recognition",
      "decision": "Decision model",
      "vision": "Screen vision",
      "zero": "Works without models",
      "zeroBody": "Built-in rules, window info and accessibility always work — no download needed.",
      "ready": "Ready",
      "applied": "Settings updated",
      "decisionApplied": "Model name updated — match it to the name your server uses",
      "visionApplied": "Screen vision model updated",
      "visionOff": "Screen vision turned off (accessibility only)",
      "getIt": "Get it",
      "browse": "Browse models",
      "unavailable": "Couldn't check your hardware"
    },
    "pull": {
      "title": "Add a model",
      "description": "Downloads can be resumed and are checked for integrity.",
      "source": "Where from",
      "sourceHint": "A Hugging Face repo (hf:org/name), a web link or a local file.",
      "tag": "Version label",
      "tagHint": "Optional. “latest” is fine.",
      "start": "Download",
      "downloading": "Downloading…",
      "cancel": "Stop",
      "needSource": "Enter where to download from, like hf:org/name",
      "failed": "Download failed: {error}",
      "starting": "Starting…",
      "done": "Download complete",
      "exitFailed": "Download stopped (code {code})",
      "progress": "{done} of {total}",
      "prefilled": "Ready to download {name} — press Download to start.",
      "browseHf": "Browse Hugging Face"
    },
    "inference": {
      "title": "Vision + planner models",
      "description": "The screen-understanding and planning models. They aren't in the model store, so Utter downloads and sets them up for you.",
      "requiredTitle": "Required models",
      "requiredDescription": "Utter needs the speech model, plus screen vision and planning. It downloads and sets them up for you.",
      "required": "Required",
      "repair": "Install / repair",
      "speech": "Speech recognition",
      "speechModel": "whisper.cpp · ggml-small.en.bin",
      "speechSize": "~470 MB",
      "vision": "Screen vision",
      "visionModel": "UI-TARS-2B-SFT",
      "visionSize": "~4.5 GB",
      "planner": "Planner",
      "plannerModel": "Planner model",
      "plannerSize": "~3 GB",
      "totalSize": "7.5 GB",
      "ready": "Ready",
      "missing": "Not downloaded",
      "checking": "Checking…",
      "readyTitle": "Vision + planning ready",
      "readyBody": "Utter can see your screen and plan actions.",
      "check": "Check server",
      "checkOk": "The planner server is responding.",
      "checkFailed": "The planner server didn't respond. Try Install / repair.",
      "download": "Download vision + planner models",
      "redownload": "Download them again",
      "consentTitle": "Download the vision and planner models?",
      "consentBody": "Utter downloads these models to your computer and sets them up. About {size} in total.",
      "willDownload": "What will be downloaded",
      "commandLabel": "Command",
      "note": "The download can be resumed and is checked for integrity. Nothing runs until you press Download.",
      "start": "Download",
      "starting": "Starting…",
      "downloading": "Downloading…",
      "activity": "Activity",
      "cancel": "Stop",
      "doneTitle": "Models ready",
      "doneBody": "Screen vision and planning are ready to use.",
      "done": "Done",
      "failedTitle": "Download failed",
      "failedBody": "The download didn't finish. Check your connection and try again.",
      "retry": "Try again",
      "notNow": "Not now",
      "exitFailed": "Download stopped (code {code})",
      "website": "Project website"
    },
    "storage": {
      "title": "Storage",
      "description": "How much space your models use.",
      "location": "Location",
      "usage": "Space used",
      "usageValue": "{size} across {models}",
      "modelsCount": {
        "one": "{count} model",
        "other": "{count} models"
      },
      "cleanup": "Clean up",
      "cleanupHint": "Remove unfinished downloads and leftover files.",
      "cleaned": {
        "one": "Cleaned up {count} item",
        "other": "Cleaned up {count} items"
      },
      "cleanFailed": "Clean-up failed"
    }
  },
  "llm": {
    "title": "AI model",
    "description": "The AI that works out what you mean when no built-in shortcut matches.",
    "badge": "Runs locally",
    "provider": {
      "title": "AI server",
      "description": "Any OpenAI-compatible server, on your computer or elsewhere.",
      "label": "Server",
      "remote": "Other server (OpenAI-compatible)",
      "getIt": "Get {name}",
      "url": "Address",
      "urlHint": "Where the server is listening, usually ending in /v1.",
      "model": "Model name",
      "modelHint": "The name your server uses for the model, e.g. qwen3-4b.",
      "test": "Test connection",
      "testHint": "Checks {url}",
      "noUrl": "Add an address first",
      "ok": "Connected ({code})",
      "failed": "Couldn't connect: {detail}"
    },
    "behaviour": {
      "title": "Behaviour",
      "description": "When the AI is asked, and how sure it must be.",
      "fallback": "Ask the AI when unsure",
      "fallbackHint": "Only used when built-in rules and window info can't work it out.",
      "head": "Double-check actions",
      "headHint": "The AI picks from safe, prepared options. It can never invent its own commands.",
      "threshold": "Confidence needed",
      "thresholdHint": "Higher means fewer mistakes but more “I'm not sure”."
    }
  },
  "tts": {
    "title": "Spoken replies",
    "description": "Let the assistant confirm what it did out loud. The voice runs on your computer.",
    "output": {
      "title": "Voice output",
      "description": "What you hear back.",
      "enable": "Speak confirmations",
      "enableHint": "Say a short confirmation when an action finishes.",
      "engine": "Voice engine",
      "engineHint": "Pick one that's installed, or install one with the link.",
      "missing": "{name} isn't installed",
      "getIt": "Get {name}",
      "voice": "Voice",
      "voiceHint": "An espeak voice like en-gb or de, or a Piper .onnx model. Empty derives it from the spoken language.",
      "language": "Spoken language",
      "languageHint": "auto follows your system language. This is independent of the settings UI language."
    },
    "test": {
      "title": "Try it",
      "description": "Hear the selected voice.",
      "phrase": "Phrase",
      "defaultPhrase": "Hi, I'm ready when you are.",
      "speak": "Play",
      "spoken": "Played",
      "failed": "{name} didn't work: {detail}",
      "couldNotRun": "Couldn't start {name}: {detail}"
    },
    "mac": {
      "description": "Let the assistant confirm what it did out loud, with the voices built into macOS.",
      "engineHint": "say is the system voice command; AVSpeechSynthesizer uses the same voices in-process.",
      "say": "System voice (say)",
      "voiceHint": "A voice name such as Samantha. Run `say -v ?` in Terminal to list them; empty uses the default.",
      "rate": "Speaking rate",
      "rateHint": "Words per minute. 0 keeps the system default."
    }
  },
  "perception": {
    "title": "Screen",
    "description": "How the assistant finds buttons and fields on your screen — and the rules that keep that safe.",
    "order": {
      "title": "How it looks for things",
      "description": "Cheapest and most reliable first. Screenshots are the last resort.",
      "t0": "Window info",
      "t0Body": "Which app and window are open.",
      "t1": "Accessibility",
      "t1Body": "Buttons and labels the app exposes.",
      "t2": "Shortcuts",
      "t2Body": "Known keyboard shortcuts.",
      "t3": "Screen vision",
      "t3Body": "Looks at a screenshot."
    },
    "a11y": {
      "title": "Accessibility",
      "description": "Reads the labels apps expose, without taking screenshots.",
      "enable": "Use accessibility info",
      "enableHint": "Fast and private. Recommended."
    },
    "vision": {
      "title": "Screen vision",
      "description": "Only used when nothing else can find what you asked for.",
      "badge": "Last resort",
      "enable": "Use screen vision",
      "enableHint": "Takes a screenshot and asks a vision model where to click.",
      "model": "Vision model",
      "modelHint": "UI-TARS works well.",
      "getModel": "Get UI-TARS",
      "endpoint": "Vision server address",
      "width": "Screenshot size",
      "widthHint": "Smaller is faster. 1344 is a good balance.",
      "gpu": "Graphics card",
      "gpuHint": "Which GPU the vision server uses (0 is the first)."
    },
    "planner": {
      "title": "Planning",
      "description": "The separate model that turns your words into actions. It's set up with screen vision.",
      "runtime": "Planner runtime"
    },
    "trust": {
      "title": "Why it's safe",
      "description": "What's on your screen can guide the assistant — it can never tell it what to do.",
      "selectTitle": "Screen text can only choose",
      "selectBody": "Text from the screen, window titles or the clipboard can only pick between actions prepared in advance. It can never write a new command.",
      "blockTitle": "Unsafe actions are blocked",
      "blockBody": "If an action was built from screen content, the assistant refuses it before it runs.",
      "orderTitle": "Screenshots come last",
      "orderBody": "Vision is only tried after window info, accessibility and shortcuts."
    }
  },
  "plugins": {
    "title": "Plugins",
    "description": "Add-ons that give the assistant its abilities, and the tools they rely on.",
    "check": "Check again",
    "restart": "Restart assistant",
    "restarted": "Assistant restarted",
    "restartFailed": "Restart failed: {detail}",
    "runner": {
      "title": "Assistant core",
      "description": "Versions agreed between the assistant and its plugins.",
      "version": "Version",
      "protocol": "Protocol",
      "health": "Health check",
      "healthy": "All good",
      "issues": "Needs attention",
      "drift": "Out-of-date files",
      "driftItems": {
        "one": "{count} item",
        "other": "{count} items"
      }
    },
    "list": {
      "title": "Installed plugins",
      "description": "Turning a plugin off takes effect after the assistant restarts.",
      "offlineTitle": "The assistant isn't running",
      "offlineBody": "Start it on the General page, then check again.",
      "emptyTitle": "No plugins loaded",
      "emptyBody": "The assistant didn't report any plugins.",
      "toggle": "Turn {name} on or off",
      "expand": "Show details",
      "collapse": "Hide details",
      "enabledToast": "{name} turned on — restart the assistant to apply",
      "disabledToast": "{name} turned off — restart the assistant to apply",
      "unknownCap": "Unknown ability",
      "missingReq": "Missing requirement",
      "kind": "Type",
      "state": "State",
      "provides": "Provides",
      "requires": "Needs",
      "negotiated": "Protocol",
      "error": "Error",
      "permissions": {
        "one": "Review {count} permission",
        "other": "Review {count} permissions"
      }
    },
    "permissions": {
      "title": "Permissions — {name}",
      "description": "Enforced permissions are blocked by the assistant. Advisory ones are a promise from the plugin.",
      "none": "This plugin doesn't ask for any permissions.",
      "enforced": "Enforced",
      "advisory": "Advisory",
      "unknownCap": "Unknown ability: {name}",
      "missingReq": "Missing requirement: {name}"
    },
    "deps": {
      "title": "System tools",
      "description": "Programs the assistant uses. Install a missing one here, or open its project page.",
      "emptyTitle": "No tool information",
      "emptyBody": "The health check didn't report any tools.",
      "ok": "Available",
      "missing": "Missing",
      "fix": "Copy fix",
      "fixCopied": "Command copied — paste it into a terminal",
      "install": "Install",
      "confirmTitle": "Install {name}?",
      "confirmBody": "This opens your terminal and runs the command below. Nothing runs until you confirm.",
      "run": "Open terminal & run",
      "opened": "Opening your terminal…"
    }
  },
  "safety": {
    "title": "Safety",
    "description": "Decide what the assistant may do on its own. Risky abilities stay off unless you turn them on.",
    "banner": {
      "title": {
        "one": "{count} risky ability is on",
        "other": "{count} risky abilities are on"
      },
      "body": "{list}. Turn them off when you don't need them."
    },
    "confirm": {
      "title": "Ask before acting",
      "description": "Important actions wait for you to say yes.",
      "enable": "Confirm important actions",
      "enableHint": "For example sending, deleting or buying.",
      "words": "Always confirm when I say",
      "wordsHint": "Words or phrases, separated by commas.",
      "placeholder": "send, submit, delete, buy"
    },
    "risky": {
      "title": "Risky abilities",
      "description": "Off by default. Your safety rules are always enforced by the assistant itself.",
      "terminal": "Run terminal commands",
      "terminalHint": "Types and runs commands in your terminal.",
      "input": "Control keyboard and mouse",
      "inputHint": "Sends key presses and clicks to any app.",
      "confirmTitle": "Turn on “{name}”?",
      "confirmBody": "This lets the assistant do things that are hard to undo. Only turn it on if you understand the risk.",
      "confirm": "Turn on",
      "enabledToast": "{name} turned on",
      "disabledToast": "{name} turned off"
    },
    "targeting": {
      "title": "App targeting",
      "description": "Send typing or key presses to a specific app instead of wherever the cursor is. For example, “codex type ok” types into Codex even while you look elsewhere.",
      "mode": "Targeted input",
      "modeHint": "Round-trip focuses the app, acts, then returns. Stay leaves it focused. Off refuses targeted typing.",
      "modes": {
        "round_trip": "Round-trip (focus, act, return)",
        "leave": "Stay on target",
        "off": "Off"
      },
      "restore": "Restore focus",
      "restoreHint": "After acting, return to the window you were using.",
      "restores": {
        "if_unchanged": "Only if I haven't moved",
        "always": "Always return",
        "never": "Never return"
      },
      "timeout": "Focus time-out",
      "timeoutHint": "How long to wait for the target window to take focus. Advanced.",
      "macNote": "On macOS, the assistant posts keys directly to the target app's process without changing focus. This is keyboard-only.",
      "otherNote": "App targeting is available on both Linux and macOS.",
      "wayland": {
        "title": "Wayland",
        "description": "With compositor animations on, targeting an app on another workspace briefly scrolls; turn animations off in your compositor for a near-instant switch.",
        "crossWorkspace": "Cross-workspace targeting",
        "crossWorkspaceHint": "Whether targeting an app on another workspace is allowed.",
        "crossWorkspaces": {
          "auto": "Automatic",
          "ask": "Ask first",
          "allow": "Allow",
          "refuse": "Refuse"
        },
        "animationsOff": "Compositor animations are off",
        "animationsOffHint": "Lets automatic cross-workspace targeting skip the prompt."
      }
    }
  },
  "diagnostics": {
    "title": "Troubleshooting",
    "description": "Check the assistant's health, read its logs and create a report for bug reports.",
    "health": {
      "title": "Health check",
      "description": "Tests the assistant, its plugins and the tools it needs.",
      "run": "Run check",
      "overall": "Overall",
      "allGood": "Everything looks good",
      "issues": "Some things need attention",
      "core": "Assistant core",
      "coreDetail": "Version {version} · protocol {protocol}",
      "raw": "Technical report",
      "rawHint": "The full JSON, for bug reports."
    },
    "desktop": {
      "title": "Desktop",
      "description": "Which compositor was detected and which backend drives windows, workspaces and screenshots.",
      "detected": "Detected compositor",
      "backend": "Active backend",
      "session": "Session",
      "unknown": "Not recognised",
      "unknownHint": "Window actions are unavailable; dictation, typing and launching still work.",
      "override": "Set by [general] compositor",
      "capabilities": "What this backend can do",
      "available": "Available",
      "unavailable": "Not available",
      "hideUnavailable": "Hide unavailable",
      "names": {
        "niri": "niri",
        "kwin": "KDE Plasma (KWin)",
        "unknown": "Unknown"
      },
      "caps": {
        "focused_window": "Focused window",
        "list_windows": "Window list",
        "activate": "Focus a window",
        "close": "Close a window",
        "minimize": "Minimise",
        "maximize": "Maximise",
        "move_to_workspace": "Move to workspace / desktop",
        "switch_workspace": "Switch workspace / desktop",
        "screenshot": "Screenshots",
        "compositor_action": "Compositor commands"
      }
    },
    "logs": {
      "title": "Activity log",
      "description": "What a background service is doing, live.",
      "service": "Service",
      "follow": "Live",
      "waiting": "Waiting for activity…",
      "paused": "Live updates are paused.",
      "lines": {
        "one": "{count} line",
        "other": "{count} lines"
      },
      "copied": "Log copied",
      "copyFailed": "Couldn't copy to the clipboard",
      "tailFailed": "Couldn't read the log: {error}"
    },
    "bundle": {
      "title": "Support report",
      "description": "A zip with the health check, settings and recent logs.",
      "export": "Create report",
      "exportHint": "Saved to your Downloads folder, or your home folder if there isn't one.",
      "done": "Report saved to {path}",
      "failed": "Couldn't create the report: {error}"
    }
  },
  "about": {
    "title": "About",
    "description": "Version, where things live, and credits.",
    "tagline": "A private voice assistant that runs on your computer.",
    "runtime": {
      "title": "On your computer",
      "description": "Where the app reads and writes.",
      "repo": "App folder",
      "python": "Python",
      "config": "Settings file",
      "socket": "Connection"
    },
    "appearance": {
      "title": "Appearance",
      "palette": "Desktop colours",
      "paletteActive": "Using your desktop colours",
      "paletteMismatch": "Available for the other theme",
      "paletteBuiltIn": "Using built-in colours"
    },
    "credits": {
      "title": "Credits",
      "stack": "Built with",
      "licence": "Licence",
      "project": "Project page"
    }
  },
  "deps": {
    "wtype": "Keyboard typing (wtype)",
    "ydotool": "Input control (ydotool)",
    "ydotoold": "Input control service (ydotoold)",
    "grim": "Screenshots (grim)",
    "dbus_cli": "D-Bus command line (gdbus or qdbus6)",
    "spectacle": "Screenshots (Spectacle)",
    "kdotool": "Window control (kdotool)",
    "wl_copy": "Clipboard (wl-clipboard)",
    "pw_play": "Audio playback (PipeWire)",
    "systemd_user": "Background services (systemd)",
    "input_group": "Keyboard access (input group)",
    "uinput": "Virtual input device (uinput)",
    "webkit2gtk": "Web view (WebKitGTK)",
    "gtk3": "GTK 3"
  }
};
