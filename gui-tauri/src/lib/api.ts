import { invoke } from "@tauri-apps/api/core";

import type {
  AppInfo,
  AppCatalog,
  AudioSource,
  BootParams,
  BundleResult,
  CmdResult,
  Config,
  DoctorReport,
  ModelEntry,
  Palette,
  InstallStatus,
  PermissionReport,
  PlatformInfo,
  ProfileList,
  ProfileOverride,
  Recommendation,
  RunnerPolicy,
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

  // Risky-op gate: read/write where the runner reads (`[policy] enabled_ops`),
  // not the GUI config the runner ignores.
  getRunnerPolicy: () => invoke<RunnerPolicy>("get_runner_policy"),
  setRunnerPolicy: (enabledOps: string[]) =>
    invoke<RunnerPolicy>("set_runner_policy", { enabledOps }),

  // Plugin opt-out is read by the runner's own config, not the GUI config.
  getRunnerPlugins: () => invoke<string[]>("get_runner_plugins"),
  setRunnerPlugins: (disabled: string[]) =>
    invoke<string[]>("set_runner_plugins", { disabled }),

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
  /**
   * The app catalogue for the onboarding picker. This is the seam for the
   * per-app opt-in work: the backend command delegates to
   * `assistant apps list --json` (`{apps:[…]}`) and falls back to the profile
   * loader. Callers must tolerate `{ok:false}` / a missing `apps` array.
   */
  appsList: () => invoke<AppCatalog | { ok?: boolean; error?: string }>("apps_list"),
  appProfileSave: (id: string, profile: ProfileOverride) =>
    invoke<CmdResult>("app_profile_save", { id, profile }),
  /** Bulk opt-in gate: enable/disable the given app profiles in one call. */
  appProfilesSetEnabled: (ids: string[], enabled: boolean) =>
    invoke<CmdResult>("app_profiles_set_enabled", { ids, enabled }),
  appProfileReset: (id: string) => invoke<void>("app_profile_reset", { id }),
  openUrl: (url: string) => invoke<void>("open_url", { url }),
  whichMany: (names: string[]) => invoke<Record<string, boolean>>("which_many", { names }),

  startMic: () => invoke<void>("start_mic"),
  stopMic: () => invoke<void>("stop_mic"),

  startLogTail: (unit: string, tailId: string) =>
    invoke<void>("start_log_tail", { unit, tailId }),
  stopLogTail: (tailId: string) => invoke<void>("stop_log_tail", { tailId }),

  platformInfo: () => invoke<PlatformInfo>("platform_info"),
  // macOS onboarding: permission probes run in the daemon's python; the pane
  // deep-link is allow-listed in the backend.
  macosPermissions: () => invoke<PermissionReport>("macos_permissions"),
  macosRequestPermission: (name: string) =>
    invoke<PermissionReport>("macos_request_permission", { name }),
  openSettingsPane: (pane: string) => invoke<void>("open_settings_pane", { pane }),
  // macOS drag-and-drop install: unpack the bundled runtime + launchd agents.
  macosInstallStatus: () => invoke<InstallStatus>("macos_install_status"),
  macosInstall: () => invoke<InstallStatus>("macos_install"),
  macosReinstallAgents: () => invoke<InstallStatus>("macos_reinstall_agents"),
  // Restart the agents when a TCC grant transitions to granted: those only
  // take effect for newly started processes.
  macosRestartAgents: () => invoke<InstallStatus>("macos_restart_agents"),

  getThemePalette: () => invoke<Palette>("get_theme_palette"),
  exportBundle: (dest?: string) =>
    invoke<BundleResult>("export_bundle", { dest: dest ?? null }),
};
