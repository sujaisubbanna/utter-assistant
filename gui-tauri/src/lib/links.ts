import { api } from "./api";

/**
 * Where to get each installable thing the UI mentions. Every entry is an
 * https project page — the backend refuses anything else.
 */

export const PROJECT_URL = "https://github.com/sujaisubbanna/utter-assistant";

export const HF_MODELS = "https://huggingface.co/models";

export const LINKS = {
  // speech recognition
  faster_whisper: "https://github.com/SYSTRAN/faster-whisper",
  whisper_cpp: "https://github.com/ggml-org/whisper.cpp",
  vosk: "https://alphacephei.com/vosk/",
  parakeet: "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2",
  vocamac: "https://github.com/VocaHQ/vocamac",
  // AI servers
  vllm: "https://docs.vllm.ai/en/latest/getting_started/installation/",
  ollama: "https://ollama.com/download",
  lm_studio: "https://lmstudio.ai/",
  llamacpp: "https://github.com/ggml-org/llama.cpp",
  // voices
  "espeak-ng": "https://github.com/espeak-ng/espeak-ng",
  espeak: "https://espeak.sourceforge.net/",
  "spd-say": "https://github.com/brailcom/speechd",
  piper: "https://github.com/OHF-Voice/piper1-gpl",
  // vision
  uitars: "https://github.com/bytedance/UI-TARS",
} as const satisfies Record<string, string>;

export type LinkId = keyof typeof LINKS;

export function linkFor(id: string): string | undefined {
  return (LINKS as Record<string, string>)[id];
}

/** A ready-to-pull model source for recommendations the store can fetch.
 *
 *  Keep this empty while every recommendation is un-pullable: the UI-TARS
 *  vision repos are sharded safetensors, so a single-file pull fails at HEAD.
 *  Vision models are provisioned with `scripts/install_inference.sh`; the UI
 *  falls back to the "Get it" project link when a tier has no source here. */
export const PULL_SOURCES: Record<string, string> = {};

/** System tools reported by `doctor` — a project page, or a fix to copy. */
export const DEP_HELP: Record<string, { url?: string; fix?: string }> = {
  wtype: { url: "https://github.com/atx/wtype" },
  ydotool: { url: "https://github.com/ReimuNotMoe/ydotool" },
  ydotoold: {
    url: "https://github.com/ReimuNotMoe/ydotool",
    fix: "systemctl --user enable --now ydotool",
  },
  grim: { url: "https://gitlab.freedesktop.org/emersion/grim" },
  // KDE Plasma (KWin backend)
  dbus_cli: { url: "https://docs.gtk.org/gio/", fix: "sudo pacman -S glib2  # or: qt6-tools (qdbus6)" },
  spectacle: { url: "https://apps.kde.org/spectacle/" },
  kdotool: { url: "https://github.com/jinliu/kdotool" },
  wl_copy: { url: "https://github.com/bugaevc/wl-clipboard" },
  pw_play: { url: "https://pipewire.org/" },
  systemd_user: { fix: "systemctl --user daemon-reload" },
  input_group: { fix: "sudo usermod -aG input $USER" },
  uinput: { fix: "sudo modprobe uinput" },
  webkit2gtk: { url: "https://webkitgtk.org/" },
  gtk3: { url: "https://www.gtk.org/" },
  // macOS tools
  ollama: { url: "https://ollama.com/", fix: "brew install ollama && brew services start ollama" },
  vocamac: { url: "https://github.com/VocaHQ/vocamac", fix: "brew install --cask vocamac" },
  screencapture: { url: "https://ss64.com/osx/screencapture.html" },
  pbpaste: { url: "https://ss64.com/osx/pbpaste.html" },
  pbcopy: { url: "https://ss64.com/osx/pbcopy.html" },
  say: { url: "https://ss64.com/osx/say.html" },
  afplay: { url: "https://ss64.com/osx/afplay.html" },
  osascript: { url: "https://ss64.com/osx/osascript.html" },
};

export function openLink(url: string): void {
  void api.openUrl(url).catch(() => {
    window.open(url, "_blank", "noopener");
  });
}
