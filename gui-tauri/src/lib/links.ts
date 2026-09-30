import { api } from "./api";

/**
 * Where to get each installable thing the UI mentions. Every entry is an
 * https project page — the backend refuses anything else.
 */

/** Set once the project has a public home; links to it stay hidden until then. */
export const PROJECT_URL = "";

export const HF_MODELS = "https://huggingface.co/models";

export const LINKS = {
  // speech recognition
  faster_whisper: "https://github.com/SYSTRAN/faster-whisper",
  whisper_cpp: "https://github.com/ggml-org/whisper.cpp",
  vosk: "https://alphacephei.com/vosk/",
  parakeet: "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2",
  vocalinux: "https://github.com/jatinkrmalik/vocalinux",
  // AI servers
  vllm: "https://docs.vllm.ai/en/latest/getting_started/installation/",
  ollama: "https://ollama.com/download",
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

/** A ready-to-pull model source for recommendations the store can fetch. */
export const PULL_SOURCES: Record<string, string> = {
  "UI-TARS-7B": "hf:ByteDance-Seed/UI-TARS-1.5-7B",
};

/** System tools reported by `doctor` — a project page, or a fix to copy. */
export const DEP_HELP: Record<string, { url?: string; fix?: string }> = {
  wtype: { url: "https://github.com/atx/wtype" },
  ydotool: { url: "https://github.com/ReimuNotMoe/ydotool" },
  ydotoold: {
    url: "https://github.com/ReimuNotMoe/ydotool",
    fix: "systemctl --user enable --now ydotool",
  },
  grim: { url: "https://gitlab.freedesktop.org/emersion/grim" },
  wl_copy: { url: "https://github.com/bugaevc/wl-clipboard" },
  pw_play: { url: "https://pipewire.org/" },
  systemd_user: { fix: "systemctl --user daemon-reload" },
  input_group: { fix: "sudo usermod -aG input $USER" },
  uinput: { fix: "sudo modprobe uinput" },
  webkit2gtk: { url: "https://webkitgtk.org/" },
  gtk3: { url: "https://www.gtk.org/" },
};

export function openLink(url: string): void {
  void api.openUrl(url).catch(() => {
    window.open(url, "_blank", "noopener");
  });
}
