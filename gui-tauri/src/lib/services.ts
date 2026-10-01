import type { MessageKey } from "../i18n";
import type { LinkId } from "./links";

export interface ServiceDef {
  unit: string;
  labelKey: MessageKey;
  descKey: MessageKey;
}

export const SERVICES: ServiceDef[] = [
  {
    unit: "utter-runner",
    labelKey: "general.serviceNames.runner",
    descKey: "general.serviceNames.runnerDesc",
  },
  {
    unit: "utter-bridge",
    labelKey: "general.serviceNames.bridge",
    descKey: "general.serviceNames.bridgeDesc",
  },
  {
    unit: "utter-vision",
    labelKey: "general.serviceNames.vision",
    descKey: "general.serviceNames.visionDesc",
  },
  {
    unit: "utter-planner",
    labelKey: "general.serviceNames.planner",
    descKey: "general.serviceNames.plannerDesc",
  },
  {
    unit: "utter-audio-defaults",
    labelKey: "general.serviceNames.audio",
    descKey: "general.serviceNames.audioDesc",
  },
];

export const SERVICE_UNITS = SERVICES.map((service) => service.unit);

/** Option labels: brand names stay as-is; generic words carry a `labelKey`. */
export interface OptionDef {
  value: string;
  label?: string;
  labelKey?: MessageKey;
  link?: LinkId;
}

export const TRIGGERS: OptionDef[] = [
  { value: "hotkey", labelKey: "general.trigger.hotkey" },
  { value: "bridge", labelKey: "general.trigger.bridge", link: "vocalinux" },
];

export const STT_BACKENDS: OptionDef[] = [
  { value: "faster_whisper", label: "faster-whisper", link: "faster_whisper" },
  { value: "whisper_cpp", label: "whisper.cpp", link: "whisper_cpp" },
  { value: "vosk", label: "Vosk", link: "vosk" },
  { value: "parakeet", label: "Parakeet", link: "parakeet" },
  { value: "remote", labelKey: "voice.stt.remote" },
  { value: "none", labelKey: "voice.stt.none", link: "vocalinux" },
];

export const STT_DEVICES = ["cuda", "cpu", "auto", "int8"];

/** macOS (`[macos]` section). Apple Speech needs no model; whisper.cpp is the offline fallback. */
export const MAC_STT_BACKENDS: OptionDef[] = [
  { value: "apple_speech", labelKey: "voice.mac.appleSpeech" },
  { value: "whisper_cpp", label: "whisper.cpp", link: "whisper_cpp" },
  { value: "faster_whisper", label: "faster-whisper", link: "faster_whisper" },
  { value: "vocamac", label: "VocaMac", link: "vocamac" },
];

export const MAC_HOTKEY_BACKENDS: OptionDef[] = [
  { value: "quartz", labelKey: "voice.mac.quartz" },
  { value: "pynput", label: "pynput" },
];

export const MAC_TTS_BACKENDS: OptionDef[] = [
  { value: "say", labelKey: "tts.mac.say" },
  { value: "avspeech", label: "AVSpeechSynthesizer" },
  { value: "none", labelKey: "common.none" },
];

export const LLM_PROVIDERS: (OptionDef & { url: string })[] = [
  { value: "vllm", label: "vLLM", url: "http://127.0.0.1:8001/v1", link: "vllm" },
  { value: "ollama", label: "Ollama", url: "http://127.0.0.1:11434/v1", link: "ollama" },
  { value: "llamacpp", label: "llama.cpp", url: "http://127.0.0.1:8080/v1", link: "llamacpp" },
  { value: "remote", labelKey: "llm.provider.remote", url: "" },
];

export const TTS_ENGINES: OptionDef[] = [
  { value: "espeak-ng", label: "eSpeak NG", link: "espeak-ng" },
  { value: "espeak", label: "eSpeak", link: "espeak" },
  { value: "spd-say", label: "Speech Dispatcher", link: "spd-say" },
  { value: "piper", label: "Piper", link: "piper" },
];

export const DANGEROUS_OPS: { op: string; titleKey: MessageKey; descKey: MessageKey }[] = [
  { op: "action.terminal", titleKey: "safety.risky.terminal", descKey: "safety.risky.terminalHint" },
  { op: "action.input", titleKey: "safety.risky.input", descKey: "safety.risky.inputHint" },
];

export function optionLabel(option: OptionDef, t: (key: MessageKey) => string): string {
  return option.labelKey ? t(option.labelKey) : (option.label ?? option.value);
}
