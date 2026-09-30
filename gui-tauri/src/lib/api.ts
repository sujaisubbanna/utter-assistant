import { invoke } from "@tauri-apps/api/core";

import type {
  AppInfo,
  AudioSource,
  BootParams,
  BundleResult,
  CmdResult,
  Config,
  DoctorReport,
  ModelEntry,
  Palette,
  ProfileList,
  ProfileOverride,
  Recommendation,
  StatusReport,
  UnitStatus,
} from "./types";

/**
 * Typed wrappers around the Rust `#[tauri::command]`s. Every command runs off
 * the UI thread and shells out with list arguments — never a shell string.
 */
export const api = {
  appInfo: () => invoke<AppInfo>("app_info"),
  bootParams: () => invoke<BootParams>("boot_params"),

  getConfig: () => invoke<Config>("get_config"),
  setConfig: (section: string, key: string, value: unknown) =>
    invoke<void>("set_config", { section, key, value }),
  setConfigMany: (section: string, values: Record<string, unknown>) =>
    invoke<void>("set_config_many", { section, values }),

  status: () => invoke<StatusReport>("status"),
  doctor: (timeout?: number) => invoke<DoctorReport>("doctor", { timeout }),
  recommend: () => invoke<Recommendation>("recommend"),

  modelsList: () => invoke<{ models?: ModelEntry[] }>("models_list"),
  modelsShow: (name: string) => invoke<unknown>("models_show", { name }),
  modelsRemove: (name: string) => invoke<CmdResult>("models_remove", { name }),
  modelsPrune: () => invoke<CmdResult>("models_prune"),
  startModelsPull: (pullId: string, source: string, tag: string) =>
    invoke<void>("start_models_pull", { pullId, source, tag }),
  cancelModelsPull: (pullId: string) => invoke<void>("cancel_models_pull", { pullId }),

  systemctlShow: (units: string[]) => invoke<UnitStatus[]>("systemctl_show", { units }),
  systemctl: (action: string, unit: string) =>
    invoke<CmdResult>("systemctl", { action, unit }),

  pactlSources: () => invoke<AudioSource[]>("pactl_sources"),
  ttsTest: (engine: string, voice: string, text: string) =>
    invoke<CmdResult>("tts_test", { engine, voice, text }),
  testEndpoint: (url: string) => invoke<CmdResult>("test_endpoint", { url }),
  appProfilesList: () => invoke<ProfileList>("app_profiles_list"),
  appProfileSave: (id: string, profile: ProfileOverride) =>
    invoke<CmdResult>("app_profile_save", { id, profile }),
  appProfileReset: (id: string) => invoke<void>("app_profile_reset", { id }),
  openUrl: (url: string) => invoke<void>("open_url", { url }),
  whichMany: (names: string[]) => invoke<Record<string, boolean>>("which_many", { names }),

  startMic: () => invoke<void>("start_mic"),
  stopMic: () => invoke<void>("stop_mic"),

  startLogTail: (unit: string, tailId: string) =>
    invoke<void>("start_log_tail", { unit, tailId }),
  stopLogTail: (tailId: string) => invoke<void>("stop_log_tail", { tailId }),

  getThemePalette: () => invoke<Palette>("get_theme_palette"),
  exportBundle: (dest?: string) =>
    invoke<BundleResult>("export_bundle", { dest: dest ?? null }),
};
