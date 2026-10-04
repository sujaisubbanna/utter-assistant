export type ThemeMode = "light" | "dark" | "system";

export interface Palette {
  tokens: Record<string, string>;
  dark: boolean;
  source: string;
  available: boolean;
}

export interface AppInfo {
  name: string;
  version: string;
  tauri: string;
  protocol: string;
  repo: string;
  python: string;
  config_path: string;
  theme_path: string;
  /** The real model store (`$XDG_DATA_HOME/utter/models`). */
  models_path: string;
  runner_sock: string;
}

export interface PlatformInfo {
  os: string;
  arch: string;
  macos: boolean;
  /** Wayland compositor id: "niri" | "kwin" | "unknown". */
  compositor: string;
}

export interface PermissionItem {
  id: string;
  label: string;
  why: string;
  status: "granted" | "denied" | "not_determined" | "unknown" | string;
  settings_url: string;
}

export interface InstallStatus {
  supported: boolean;
  bundled: boolean;
  bundled_version?: string | null;
  installed: boolean;
  installed_version?: string | null;
  update_available: boolean;
  agents_installed: boolean;
  python: string;
  repo: string;
  runtime_dir: string;
}

export interface PermissionReport {
  ok?: boolean;
  error?: string;
  platform?: string;
  process?: string;
  all_granted?: boolean;
  permissions: PermissionItem[];
  ts?: number;
}

export interface BootParams {
  route?: string | null;
  theme?: string | null;
  lang?: string | null;
}

export interface UnitStatus {
  id: string;
  load_state: string;
  active_state: string;
  sub_state: string;
  unit_file_state: string;
}

export interface CmdResult {
  code: number;
  stdout: string;
  stderr: string;
  ok: boolean;
}

export interface AudioSource {
  name: string;
  description: string;
}

export interface PluginPermission {
  name?: string;
  enforced?: boolean;
  advisory?: boolean;
}

export interface Plugin {
  id?: string;
  kind?: string;
  epoch?: number;
  status?: string;
  negotiated?: { protocol?: string; abi?: number };
  unknown_capabilities?: string[];
  missing_requires?: string[];
  permissions?: PluginPermission[];
  deprecations?: unknown[];
  error?: string;
  provides?: string[];
  requires?: string[];
}

export interface RunnerInfo {
  protocol?: string;
  abi?: number;
  version?: string;
}

export interface CompositorInfo {
  platform?: string;
  requested?: string;
  detected?: string;
  session_type?: string;
  desktop?: string;
  plasma_version?: string;
  evidence?: string[];
  active?: string;
  reason?: string;
  available?: boolean;
  capabilities?: Record<string, boolean>;
  tools?: Record<string, string | null>;
  error?: string;
}

export interface RuntimeRole {
  provider?: string;
  endpoint?: string;
  model?: string;
  available?: boolean;
  status?: string;
  message?: string;
}

export interface RuntimeInfo {
  platform?: string;
  device?: string;
  gpu?: { available?: boolean; name?: string; runtime?: string; unified_memory_gb?: number };
  llm?: RuntimeRole;
  vision?: RuntimeRole;
  stt?: RuntimeRole;
  tts?: RuntimeRole;
}

export interface DoctorReport {
  ok?: boolean;
  connected?: boolean;
  error?: string;
  runner?: RunnerInfo;
  plugins?: Plugin[];
  drift?: unknown[];
  deps?: Record<string, boolean>;
  compositor?: CompositorInfo;
  runtime?: RuntimeInfo;
}

export interface StatusReport {
  ok?: boolean;
  connected?: boolean;
  error?: string;
  plugins?: Plugin[];
}

export interface ModelEntry {
  name?: string;
  tag?: string;
  host?: string;
  ns?: string;
  bytes?: number;
  files?: number;
  manifest?: string;
}

export interface Recommendation {
  hardware?: {
    cpu?: { model?: string; cores?: number };
    ram_gb?: number;
    session?: string;
    gpus?: { name?: string; vendor?: string; vram_gb?: number }[];
  };
  suggestions?: {
    stt?: Record<string, unknown>;
    decision_llm?: Record<string, unknown>;
    planner_llm?: Record<string, unknown>;
    vision?: Record<string, unknown>;
    zero_model_mode?: boolean;
    reason?: string;
  };
}

export type Config = Record<string, Record<string, unknown>>;

export interface BundleResult {
  path: string;
  entries: number;
}

export interface ProfileOverride {
  aliases?: string[];
  shortcuts?: Record<string, string>;
  search_url?: string | null;
  enabled?: boolean;
}

export interface AppProfile {
  id: string;
  name: string;
  kind: string;
  aliases: string[];
  launch: string[] | string;
  search_url?: string | null;
  shortcuts: Record<string, string>;
  builtin_shortcuts: Record<string, string>;
  app_ids: string[];
  curated: boolean;
  /** Per-app opt-in gate: false means Utter ignores the app entirely. */
  enabled: boolean;
  /** True for the shipped curated default set. */
  preselected: boolean;
  user: (ProfileOverride & { id?: string }) | null;
  own?: boolean;
}

export interface ProfileList {
  profiles: AppProfile[];
  user_dir: string;
  loader_reads_user: boolean;
}

/**
 * One entry in the app catalogue the onboarding picker shows. `icon` is an
 * optional data/URL the backend may supply (a real desktop-entry or bundle
 * icon); when absent the UI falls back to the kind icon. `enabled` and
 * `preselected` come from the per-app opt-in backend — until that ships the
 * picker derives both from the curated profile list.
 */
export interface AppCatalogEntry {
  id: string;
  name: string;
  kind: string;
  icon?: string | null;
  enabled?: boolean;
  preselected?: boolean;
}

export interface AppCatalog {
  apps: AppCatalogEntry[];
  /** False when the rich catalogue isn't available and the list was derived. */
  detected?: boolean;
}

/** The runner's risky-action allow-list (`[policy] enabled_ops`). */
export interface RunnerPolicy {
  /** The runner config file the policy is read from / written to. */
  path: string;
  enabled_ops: string[];
  /** True when the runner unit was restarted so the change took effect. */
  restarted: boolean;
}
