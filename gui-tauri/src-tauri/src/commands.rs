//! Tauri commands — the whole backend contract.
//!
//! Everything that can block runs off the UI thread. Subprocesses are always
//! spawned from a **list of arguments** (never a shell string), and streaming
//! output is forwarded to the frontend with `emit`.

use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, State};

use crate::config;
use crate::profiles;
use crate::process::{io_message, Cmd, CmdResult};
use crate::service::{self, ServiceBackend, UnitStatus};
use crate::state::AppState;
use crate::theme::{self, Palette};
use crate::zip;

/// Service units the GUI is allowed to control. Linux uses systemd unit names;
/// macOS maps them onto launchd labels (see `service::launchd_label`); Windows
/// reuses the same strings as Scheduled Task names.
const UNITS: &[&str] = &[
    "utter-runner",
    "utter.service",
    "utter-bridge",
    "utter-vision",
    "utter-planner",
    "utter-audio-defaults",
];

/// Whether `unit` may be controlled on `backend`. Every backend accepts the
/// shared unit names above.
fn unit_allowed(unit: &str, _backend: ServiceBackend) -> bool {
    UNITS.contains(&unit)
}

const SYSTEMCTL_ACTIONS: &[&str] = &[
    "start",
    "stop",
    "restart",
    "enable",
    "disable",
    "is-active",
    "is-enabled",
];

// --------------------------------------------------------------------------- //
// helpers
// --------------------------------------------------------------------------- //
async fn blocking<T, F>(func: F) -> Result<T, String>
where
    F: FnOnce() -> Result<T, String> + Send + 'static,
    T: Send + 'static,
{
    tauri::async_runtime::spawn_blocking(func)
        .await
        .map_err(|err| err.to_string())?
}

fn parse_json_lossy(stdout: &str, stderr: &str) -> Value {
    let text = stdout.trim();
    if let Ok(value) = serde_json::from_str::<Value>(text) {
        return value;
    }
    if let Some(index) = text.find(['{', '[']) {
        if let Ok(value) = serde_json::from_str::<Value>(&text[index..]) {
            return value;
        }
    }
    let error = if stderr.trim().is_empty() {
        "command produced no output"
    } else {
        stderr.trim()
    };
    serde_json::json!({ "ok": false, "connected": false, "error": error })
}

fn err(message: impl Into<String>) -> String {
    message.into()
}

// --------------------------------------------------------------------------- //
// platform (macOS vs Linux)
// --------------------------------------------------------------------------- //
pub const IS_MACOS: bool = cfg!(target_os = "macos");

fn launchd_log(unit: &str) -> Option<&'static str> {
    match unit {
        "utter-runner" => Some("runner.log"),
        "utter.service" | "utter-bridge" => Some("utter.log"),
        _ => None,
    }
}

#[derive(Serialize)]
pub struct PlatformInfo {
    pub os: String,
    pub arch: String,
    pub macos: bool,
    /// Wayland compositor id: "niri" | "kwin" | "unknown". Mirrors
    /// `utter/context/compositor.py::detect` so the UI can gate
    /// compositor-specific settings (e.g. the `[wayland]` app-target knobs).
    pub compositor: String,
}

/// Detect the compositor from the same environment signals the Python side
/// uses (`XDG_CURRENT_DESKTOP`, `KDE_FULL_SESSION`, `KDE_SESSION_VERSION`,
/// `XDG_SESSION_DESKTOP`, `DESKTOP_SESSION`, `NIRI_SOCKET`).
fn detect_compositor() -> String {
    let env = |k: &str| std::env::var(k).unwrap_or_default();
    let desktop = env("XDG_CURRENT_DESKTOP").to_lowercase();
    let tokens: Vec<&str> = desktop.split([':', ';']).map(str::trim).collect();
    if tokens.contains(&"niri") {
        return "niri".to_string();
    }
    if tokens.contains(&"kde") {
        return "kwin".to_string();
    }
    let full = env("KDE_FULL_SESSION").trim().to_lowercase();
    if matches!(full.as_str(), "true" | "1" | "yes") {
        return "kwin".to_string();
    }
    if !env("KDE_SESSION_VERSION").trim().is_empty() {
        return "kwin".to_string();
    }
    for var in ["XDG_SESSION_DESKTOP", "DESKTOP_SESSION"] {
        let low = env(var).trim().to_lowercase();
        if low.is_empty() {
            continue;
        }
        if low.contains("niri") {
            return "niri".to_string();
        }
        if low == "plasma" || low.starts_with("plasma") {
            return "kwin".to_string();
        }
    }
    if !env("NIRI_SOCKET").is_empty() {
        return "niri".to_string();
    }
    "unknown".to_string()
}

#[tauri::command]
pub fn platform_info() -> PlatformInfo {
    PlatformInfo {
        os: std::env::consts::OS.to_string(),
        arch: std::env::consts::ARCH.to_string(),
        macos: IS_MACOS,
        compositor: detect_compositor(),
    }
}

/// Privacy panes the Setup page may deep-link to (System Settings -> Privacy & Security).
const SETTINGS_PANES: &[&str] = &[
    "Privacy_Microphone",
    "Privacy_SpeechRecognition",
    "Privacy_ListenEvent",
    "Privacy_Accessibility",
    "Privacy_ScreenCapture",
    "Privacy",
];

/// Open a System Settings privacy pane (macOS only; the pane is allow-listed).
#[tauri::command]
pub fn open_settings_pane(pane: String) -> Result<(), String> {
    if !IS_MACOS {
        return Err("System Settings deep links only exist on macOS".to_string());
    }
    if !SETTINGS_PANES.contains(&pane.as_str()) {
        return Err(format!("pane not allowed: {pane}"));
    }
    let url = format!("x-apple.systempreferences:com.apple.preference.security?{pane}");
    std::process::Command::new("open")
        .arg(url)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map(|mut child| {
            std::thread::spawn(move || {
                let _ = child.wait();
            });
        })
        .map_err(|error| error.to_string())
}

/// Status of the macOS privacy permissions, probed by the daemon's own python
/// (`assistant macos-permissions --json`) so the result reflects the binary
/// launchd runs, not this app.
#[tauri::command]
pub async fn macos_permissions(state: State<'_, AppState>) -> Result<Value, String> {
    let cmd = state.assistant(&["macos-permissions", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        Ok(parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        ))
    })
    .await
}

/// Trigger the system prompt for one permission (or "all") from the daemon's python.
#[tauri::command]
pub async fn macos_request_permission(
    state: State<'_, AppState>,
    name: String,
) -> Result<Value, String> {
    const ALLOWED: &[&str] = &[
        "all",
        "microphone",
        "speech_recognition",
        "input_monitoring",
        "accessibility",
        "screen_recording",
    ];
    if !ALLOWED.contains(&name.as_str()) {
        return Err(format!("permission not allowed: {name}"));
    }
    let cmd = state.assistant(&["macos-permissions", "--json", "--request", name.as_str()]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        Ok(parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        ))
    })
    .await
}

// --------------------------------------------------------------------------- //
// app / environment
// --------------------------------------------------------------------------- //
#[derive(Serialize)]
pub struct AppInfo {
    pub name: String,
    pub version: String,
    pub tauri: String,
    pub protocol: String,
    pub repo: String,
    pub python: String,
    pub config_path: String,
    pub theme_path: String,
    /// The real model store (`assistant.models` layout), not `<repo>/models`.
    pub models_path: String,
    pub runner_sock: String,
}

/// `$UTTER_MODELS`, else `$XDG_DATA_HOME/utter-models` on Linux/macOS and
/// `%LOCALAPPDATA%\utter\models` on Windows — mirrors
/// `assistant/util.py::models_root`.
fn models_path() -> PathBuf {
    if let Ok(value) = std::env::var("UTTER_MODELS") {
        if !value.is_empty() {
            return PathBuf::from(value);
        }
    }
    if cfg!(target_os = "windows") {
        return crate::data_home().join("utter/models");
    }
    let data_home = std::env::var("XDG_DATA_HOME")
        .ok()
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            std::env::var("HOME")
                .map(|home| PathBuf::from(home).join(".local/share"))
                .unwrap_or_else(|_| PathBuf::from(".local/share"))
        });
    data_home.join("utter-models")
}

#[tauri::command]
pub fn app_info(state: State<AppState>) -> AppInfo {
    let runner_sock = std::env::var("UTTER_RUNNER_SOCK")
        .ok()
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| {
            if cfg!(target_os = "windows") {
                return crate::data_home()
                    .join("utter/runtime/runner.sock")
                    .to_string_lossy()
                    .into_owned();
            }
            let runtime = std::env::var("XDG_RUNTIME_DIR")
                .unwrap_or_else(|_| format!("/run/user/{}", fallback_uid()));
            format!("{runtime}/utter/runner.sock")
        });
    AppInfo {
        name: "utter".to_string(),
        version: env!("CARGO_PKG_VERSION").to_string(),
        tauri: tauri::VERSION.to_string(),
        protocol: "1.0".to_string(),
        repo: state.repo().to_string_lossy().into_owned(),
        python: state.python(),
        config_path: state.config_path.to_string_lossy().into_owned(),
        theme_path: state.theme_path.to_string_lossy().into_owned(),
        models_path: models_path().to_string_lossy().into_owned(),
        runner_sock,
    }
}

fn fallback_uid() -> u32 {
    // Avoid a libc dependency for a single call.
    std::env::var("UID")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(1000)
}

#[derive(Default, Serialize)]
pub struct BootParams {
    pub route: Option<String>,
    pub theme: Option<String>,
    pub lang: Option<String>,
}

/// Dev/screenshot affordance: force an initial route and theme via the
/// environment (`UTTER_GUI_ROUTE`, `UTTER_GUI_THEME`, `UTTER_GUI_LANG`).
#[tauri::command]
pub fn boot_params() -> BootParams {
    let read = |key: &str| {
        std::env::var(key)
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
    };
    BootParams {
        route: read("UTTER_GUI_ROUTE"),
        theme: read("UTTER_GUI_THEME"),
        lang: read("UTTER_GUI_LANG"),
    }
}

#[tauri::command]
pub fn get_config(state: State<AppState>) -> Result<Value, String> {
    let _ = config::ensure(&state);
    Ok(config::read_json(&state))
}

#[tauri::command]
pub fn set_config(
    state: State<AppState>,
    section: String,
    key: String,
    value: Value,
) -> Result<(), String> {
    config::set_key(&state, &section, &key, &value)
}

#[tauri::command]
pub fn set_config_many(state: State<AppState>, section: String, values: Value) -> Result<(), String> {
    config::set_many(&state, &section, &values)
}

// --------------------------------------------------------------------------- //
// runner policy (the risky-action gate lives in the runner's own config)
// --------------------------------------------------------------------------- //

/// Path of the config the **runner** loads, mirroring
/// `scripts/utter-wayland-ready.sh`: `$UTTER_CONFIG`, else `<repo>/config.runner.toml`,
/// else the older `<repo>/config.m3.toml`, else `<repo>/runner/config.example.toml`.
fn runner_config_path(state: &AppState) -> PathBuf {
    if let Ok(value) = std::env::var("UTTER_CONFIG") {
        if !value.is_empty() {
            return PathBuf::from(value);
        }
    }
    let repo = state.repo();
    for name in ["config.runner.toml", "config.m3.toml"] {
        let candidate = repo.join(name);
        if candidate.is_file() {
            return candidate;
        }
    }
    repo.join("runner/config.example.toml")
}

fn read_runner_policy(path: &Path) -> Vec<String> {
    let text = std::fs::read_to_string(path).unwrap_or_default();
    let value: toml::Value = match toml::from_str(&text) {
        Ok(value) => value,
        Err(_) => return Vec::new(),
    };
    value
        .get("policy")
        .and_then(|policy| policy.get("enabled_ops"))
        .and_then(|ops| ops.as_array())
        .map(|ops| {
            ops.iter()
                .filter_map(|op| op.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

/// Restart the runner so a config change takes effect, on whichever service
/// manager the host actually has (systemd / launchd / Scheduled Task).
fn restart_runner(_state: &AppState) -> bool {
    service::control(ServiceBackend::detect(), "restart", "utter-runner")
        .map(|result| result.ok)
        .unwrap_or(false)
}

#[derive(Serialize)]
pub struct RunnerPolicy {
    /// The runner config file the policy was read from / written to.
    pub path: String,
    pub enabled_ops: Vec<String>,
    /// True when the runner unit was restarted so the change takes effect.
    pub restarted: bool,
}

/// Read the risky-op allow-list from the file the runner actually loads — not
/// from the GUI's `~/.config/utter/config.toml`, which the runner never reads.
#[tauri::command]
pub fn get_runner_policy(state: State<AppState>) -> Result<RunnerPolicy, String> {
    let path = runner_config_path(&state);
    Ok(RunnerPolicy {
        path: path.display().to_string(),
        enabled_ops: read_runner_policy(&path),
        restarted: false,
    })
}

/// Write `[policy] enabled_ops` where the runner reads it, then restart the unit
/// so the toggle is effective. Only the two ops the Safety page exposes are
/// accepted; the runner still demands confirmation when they are invoked.
#[tauri::command(rename_all = "camelCase")]
pub fn set_runner_policy(
    state: State<AppState>,
    enabled_ops: Vec<String>,
) -> Result<RunnerPolicy, String> {
    const ALLOWED: [&str; 4] = ["action.terminal", "action.input", "terminal", "input"];
    for op in &enabled_ops {
        if !ALLOWED.contains(&op.as_str()) {
            return Err(format!("unsupported policy op: {op}"));
        }
    }
    let path = runner_config_path(&state);
    let default_config = state.repo().join("runner/config.example.toml");
    let value = Value::Array(
        enabled_ops
            .iter()
            .map(|op| Value::String(op.clone()))
            .collect(),
    );
    config::set_key_at(&path, &default_config, "policy", "enabled_ops", &value)?;
    // The runner reads policy once at startup: restart so the change applies.
    let restarted = restart_runner(&state);
    Ok(RunnerPolicy {
        path: path.display().to_string(),
        enabled_ops,
        restarted,
    })
}

fn read_runner_disabled_plugins(path: &Path) -> Vec<String> {
    let text = std::fs::read_to_string(path).unwrap_or_default();
    let value: toml::Value = match toml::from_str(&text) {
        Ok(value) => value,
        Err(_) => return Vec::new(),
    };
    value
        .get("plugins")
        .and_then(|plugins| plugins.get("disabled"))
        .and_then(|disabled| disabled.as_array())
        .map(|ids| {
            ids.iter()
                .filter_map(|id| id.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

fn valid_plugin_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 64
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.'))
}

/// Plugin ids disabled via `[plugins] disabled` in the runner config.
#[tauri::command]
pub fn get_runner_plugins(state: State<AppState>) -> Result<Vec<String>, String> {
    Ok(read_runner_disabled_plugins(&runner_config_path(&state)))
}

/// Enable/disable plugins where the runner reads it, then restart the unit.
/// `disabled` is the full set of disabled ids (the inverse of the UI toggle).
#[tauri::command(rename_all = "camelCase")]
pub fn set_runner_plugins(
    state: State<AppState>,
    disabled: Vec<String>,
) -> Result<Vec<String>, String> {
    for id in &disabled {
        if !valid_plugin_id(id) {
            return Err(format!("invalid plugin id: {id}"));
        }
    }
    let path = runner_config_path(&state);
    let default_config = state.repo().join("runner/config.example.toml");
    let value = Value::Array(
        disabled
            .iter()
            .map(|id| Value::String(id.clone()))
            .collect(),
    );
    config::set_key_at(&path, &default_config, "plugins", "disabled", &value)?;
    // Plugin enablement is read once at startup.
    let _ = restart_runner(&state);
    Ok(disabled)
}

// --------------------------------------------------------------------------- //
// assistant CLI passthroughs
// --------------------------------------------------------------------------- //
#[tauri::command]
pub async fn status(state: State<'_, AppState>) -> Result<Value, String> {
    let cmd = state.assistant(&["status", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        Ok(parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        ))
    })
    .await
}

#[tauri::command]
pub async fn doctor(state: State<'_, AppState>, timeout: Option<f64>) -> Result<Value, String> {
    let timeout = timeout.unwrap_or(10.0).clamp(1.0, 60.0);
    let cmd = state.assistant(&["doctor", "--json", "--timeout", &format!("{timeout}")]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        Ok(parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        ))
    })
    .await
}

#[tauri::command]
pub async fn recommend(state: State<'_, AppState>) -> Result<Value, String> {
    let cmd = state.assistant(&["recommend", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        Ok(parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        ))
    })
    .await
}

/// One open window as `assistant windows --json` reports it, for the dictation
/// target picker. `id` passes through untouched because compositors may report
/// it as a number or a string; the UI turns it into a pin spec.
#[derive(Serialize)]
pub struct WindowInfo {
    pub id: Value,
    pub pid: i64,
    pub app_id: String,
    pub title: String,
    pub focused: bool,
}

fn parse_windows(value: &Value) -> Vec<WindowInfo> {
    value
        .get("windows")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| {
                    Some(WindowInfo {
                        id: item.get("id")?.clone(),
                        pid: item.get("pid").and_then(Value::as_i64).unwrap_or(0),
                        app_id: item
                            .get("app_id")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                        title: item
                            .get("title")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                        focused: item.get("focused").and_then(Value::as_bool).unwrap_or(false),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

/// The open windows the dictation target picker can pin. Empty when the
/// compositor reports none; a stale backend surfaces as a readable error.
#[tauri::command]
pub async fn context_windows(state: State<'_, AppState>) -> Result<Vec<WindowInfo>, String> {
    let cmd = state.assistant(&["windows", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        let value = parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        );
        if value.get("ok").and_then(Value::as_bool) == Some(false) {
            let message = value
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("windows are unavailable");
            return Err(message.to_string());
        }
        Ok(parse_windows(&value))
    })
    .await
}

// --------------------------------------------------------------------------- //
// dictation target picker
// --------------------------------------------------------------------------- //

/// A dictation that couldn't be delivered because no text field was focused,
/// as `assistant dictation --pending --json` reports it. Absent = `null`.
#[derive(Serialize)]
pub struct PendingDictation {
    pub text: String,
    pub reason: String,
    pub ts: i64,
}

fn parse_pending(value: &Value) -> Option<PendingDictation> {
    let text = value.get("text").and_then(Value::as_str)?.trim();
    if text.is_empty() {
        return None;
    }
    Some(PendingDictation {
        text: text.to_string(),
        reason: value
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        ts: value.get("ts").and_then(Value::as_i64).unwrap_or(0),
    })
}

/// The pending dictation, or `null` when there is nothing waiting. Polling this
/// is cheap and safe on every page.
#[tauri::command]
pub async fn dictation_pending(
    state: State<'_, AppState>,
) -> Result<Option<PendingDictation>, String> {
    let cmd = state.assistant(&["dictation", "--pending", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        let value = parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        );
        Ok(parse_pending(&value))
    })
    .await
}

/// Outcome of `assistant dictation --deliver`, which prints `{ok, detail}`.
#[derive(Serialize)]
pub struct DictationResult {
    pub ok: bool,
    pub detail: String,
}

fn parse_dictation_result(value: &Value) -> DictationResult {
    DictationResult {
        ok: value.get("ok").and_then(Value::as_bool).unwrap_or(false),
        detail: value
            .get("detail")
            .and_then(Value::as_str)
            .or_else(|| value.get("error").and_then(Value::as_str))
            .unwrap_or_default()
            .to_string(),
    }
}

/// Type `text` into the window named by `target` (`<window-id>` | `pid:<n>` |
/// `app_id:<s>`). The result is always returned, even on a failed delivery, so
/// the UI can report it without surfacing a raw error.
#[tauri::command]
pub async fn dictation_deliver(
    state: State<'_, AppState>,
    text: String,
    target: String,
) -> Result<DictationResult, String> {
    let cmd = state.assistant(&[
        "dictation",
        "--deliver",
        "--text",
        text.as_str(),
        "--target",
        target.as_str(),
        "--json",
    ]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        let value = parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        );
        Ok(parse_dictation_result(&value))
    })
    .await
}

/// Clear the pending dictation record. Best-effort: a failure here still lets
/// the UI close the picker.
#[tauri::command]
pub async fn dictation_dismiss(state: State<'_, AppState>) -> Result<(), String> {
    let cmd = state.assistant(&["dictation", "--dismiss", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        if out.status.success() {
            return Ok(());
        }
        Err("could not clear the pending dictation".to_string())
    })
    .await
}

#[tauri::command]
pub async fn models_list(state: State<'_, AppState>) -> Result<Value, String> {
    let cmd = state.assistant(&["models", "list", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        Ok(parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        ))
    })
    .await
}

#[tauri::command]
pub async fn models_show(state: State<'_, AppState>, name: String) -> Result<Value, String> {
    let cmd = state.assistant(&["models", "show", &name, "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        Ok(parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        ))
    })
    .await
}

#[tauri::command]
pub async fn models_remove(state: State<'_, AppState>, name: String) -> Result<CmdResult, String> {
    let cmd = state.assistant(&["models", "rm", &name, "--json"]);
    blocking(move || Ok(CmdResult::from_output(cmd.output()))).await
}

#[tauri::command]
pub async fn models_prune(state: State<'_, AppState>) -> Result<CmdResult, String> {
    let cmd = state.assistant(&["models", "prune", "--json"]);
    blocking(move || Ok(CmdResult::from_output(cmd.output()))).await
}

/// Pull a model, streaming NDJSON progress as `models://progress`.
#[tauri::command(rename_all = "camelCase")]
pub fn start_models_pull(
    app: AppHandle,
    state: State<AppState>,
    pull_id: String,
    source: String,
    tag: String,
) -> Result<(), String> {
    let cmd = state.assistant(&["models", "pull", &source, "--tag", &tag, "--json"]);
    let mut child = cmd.spawn_piped().map_err(|error| io_message(&error))?;
    let stdout = child.stdout.take().ok_or_else(|| err("no stdout pipe"))?;
    let stderr = child.stderr.take();
    let children = state.children.clone();
    children.lock().unwrap().insert(pull_id.clone(), child);

    // Drain stderr in its own thread so a chatty child can never deadlock.
    if let Some(stderr) = stderr {
        let app_err = app.clone();
        let id = pull_id.clone();
        std::thread::spawn(move || {
            let reader = BufReader::new(stderr);
            let mut text = String::new();
            for line in reader.lines().map_while(Result::ok) {
                if text.len() < 8192 {
                    text.push_str(&line);
                    text.push('\n');
                }
            }
            if !text.trim().is_empty() {
                let _ = app_err.emit("models://stderr", serde_json::json!({ "pullId": id, "text": text }));
            }
        });
    }

    let app_handle = app.clone();
    let id = pull_id.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            if !line.trim().is_empty() {
                let _ = app_handle.emit(
                    "models://progress",
                    serde_json::json!({ "pullId": id.clone(), "line": line }),
                );
            }
        }
        let code = if let Some(mut child) = children.lock().unwrap().remove(&id) {
            child.wait().ok().and_then(|status| status.code()).unwrap_or(-1)
        } else {
            -1
        };
        let _ = app_handle.emit("models://done", serde_json::json!({ "pullId": id, "code": code }));
    });

    Ok(())
}

#[tauri::command(rename_all = "camelCase")]
pub fn cancel_models_pull(state: State<AppState>, pull_id: String) -> Result<(), String> {
    state.kill_child(&pull_id);
    Ok(())
}

/// Whether the sharded vision + planner models are provisioned, and where.
///
/// `assistant inference status --json` reports `{vision, planner, *_path}`.
#[tauri::command]
pub async fn inference_status(state: State<'_, AppState>) -> Result<Value, String> {
    let cmd = state.assistant(&["inference", "status", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        Ok(parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        ))
    })
    .await
}

/// Smoke-test the planner endpoint: `assistant inference check --json`.
///
/// The command emits a JSON report (`{ok, reachable, base_url, detail, errors}`)
/// and exits non-zero when the check fails, so the exit status is merged in as
/// the authoritative `ok`.
#[tauri::command]
pub async fn inference_check(state: State<'_, AppState>) -> Result<Value, String> {
    let cmd = state.assistant(&["inference", "check", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        let stdout = String::from_utf8_lossy(&out.stdout);
        let stderr = String::from_utf8_lossy(&out.stderr);
        let mut value = parse_json_lossy(&stdout, &stderr);
        if let Some(object) = value.as_object_mut() {
            object.insert("ok".into(), Value::Bool(out.status.success()));
        }
        Ok(value)
    })
    .await
}

/// Download the sharded vision + planner models, streaming NDJSON progress as
/// `inference://progress` and a final `inference://done`.
///
/// Mirrors `start_models_pull`. The CLI (`assistant inference install --json`)
/// now provisions on every platform (torch + transformers on Windows/macOS,
/// vLLM on Linux), so this spawns the same way everywhere.
#[tauri::command(rename_all = "camelCase")]
pub fn start_inference_install(
    app: AppHandle,
    state: State<AppState>,
    id: String,
) -> Result<(), String> {
    let cmd = state.assistant(&["inference", "install", "--json"]);
    let mut child = cmd.spawn_piped().map_err(|error| io_message(&error))?;
    let stdout = child.stdout.take().ok_or_else(|| err("no stdout pipe"))?;
    let stderr = child.stderr.take();
    let children = state.children.clone();
    children.lock().unwrap().insert(id.clone(), child);

    // Drain stderr in its own thread so a chatty installer can never deadlock.
    if let Some(stderr) = stderr {
        let app_err = app.clone();
        let id_err = id.clone();
        std::thread::spawn(move || {
            let reader = BufReader::new(stderr);
            let mut text = String::new();
            for line in reader.lines().map_while(Result::ok) {
                if text.len() < 8192 {
                    text.push_str(&line);
                    text.push('\n');
                }
            }
            if !text.trim().is_empty() {
                let _ = app_err.emit(
                    "inference://stderr",
                    serde_json::json!({ "id": id_err, "text": text }),
                );
            }
        });
    }

    let app_handle = app.clone();
    let id_done = id.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            if line.trim().is_empty() {
                continue;
            }
            // Forward the raw line plus its `event` name when parseable, so the
            // UI can react without re-parsing (it still keeps the raw line).
            let name = serde_json::from_str::<Value>(&line)
                .ok()
                .and_then(|value| value.get("event").and_then(|v| v.as_str()).map(str::to_string));
            let _ = app_handle.emit(
                "inference://progress",
                serde_json::json!({ "id": id_done.clone(), "line": line, "event": name }),
            );
        }
        let code = if let Some(mut child) = children.lock().unwrap().remove(&id_done) {
            child.wait().ok().and_then(|status| status.code()).unwrap_or(-1)
        } else {
            -1
        };
        let _ = app_handle.emit("inference://done", serde_json::json!({ "id": id_done, "code": code }));
    });

    Ok(())
}

#[tauri::command(rename_all = "camelCase")]
pub fn cancel_inference_install(state: State<AppState>, id: String) -> Result<(), String> {
    state.kill_child(&id);
    Ok(())
}

// --------------------------------------------------------------------------- //
// services (systemd | launchd | schtasks)
// --------------------------------------------------------------------------- //
// The frontend has always called `systemctl_show` / `systemctl`; those names stay
// as thin aliases so the TypeScript surface is unchanged. The real work lives
// behind `service_show` / `service_control`, dispatched by the platform backend.
async fn show_impl(units: Vec<String>) -> Result<Vec<UnitStatus>, String> {
    let backend = ServiceBackend::detect();
    blocking(move || service::show_units(backend, &units)).await
}

async fn control_impl(action: String, unit: String) -> Result<CmdResult, String> {
    if !SYSTEMCTL_ACTIONS.contains(&action.as_str()) {
        return Err(format!("action not allowed: {action}"));
    }
    let backend = ServiceBackend::detect();
    if !unit_allowed(&unit, backend) {
        return Err(format!("unit not allowed: {unit}"));
    }
    blocking(move || service::control(backend, &action, &unit)).await
}

/// Status of the service rows on the resolved platform backend.
#[tauri::command]
pub async fn service_show(units: Vec<String>) -> Result<Vec<UnitStatus>, String> {
    show_impl(units).await
}

/// Start/stop/restart/enable/disable a service on the resolved platform backend.
#[tauri::command]
pub async fn service_control(action: String, unit: String) -> Result<CmdResult, String> {
    control_impl(action, unit).await
}

/// Back-compat alias used by the existing UI.
#[tauri::command]
pub async fn systemctl_show(units: Vec<String>) -> Result<Vec<UnitStatus>, String> {
    show_impl(units).await
}

/// Back-compat alias used by the existing UI.
#[tauri::command]
pub async fn systemctl(action: String, unit: String) -> Result<CmdResult, String> {
    control_impl(action, unit).await
}

// --------------------------------------------------------------------------- //
// audio / tts
// --------------------------------------------------------------------------- //
#[derive(Serialize)]
pub struct AudioSource {
    pub name: String,
    pub description: String,
}

fn parse_pactl_sources(text: &str) -> Vec<AudioSource> {
    let mut sources = Vec::new();
    for line in text.lines() {
        let parts: Vec<&str> = line.split('\t').collect();
        if parts.len() < 2 {
            continue;
        }
        let name = parts[1];
        if name.ends_with(".monitor") {
            continue;
        }
        let description = if parts.len() > 2 { parts[2] } else { name };
        sources.push(AudioSource {
            name: name.to_string(),
            description: description.to_string(),
        });
    }
    sources
}

#[tauri::command]
pub async fn pactl_sources() -> Result<Vec<AudioSource>, String> {
    let cmd = Cmd::new("pactl").args(["list", "short", "sources"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| error.to_string())?;
        Ok(parse_pactl_sources(&String::from_utf8_lossy(&out.stdout)))
    })
    .await
}

#[tauri::command]
pub async fn tts_test(
    engine: String,
    voice: String,
    text: String,
) -> Result<CmdResult, String> {
    // Empty voice = engine default, derived from [tts] language elsewhere.
    // Never hardcode a language here.
    let voice = voice.trim();
    // `auto` (the config default) and `none` are not binaries. Resolve `auto`
    // to the first engine actually installed, mirroring
    // `utter.voice.tts.select_engine`.
    let engine = if engine.trim().is_empty() || engine.trim() == "auto" {
        ["espeak-ng", "espeak", "spd-say", "piper"]
            .into_iter()
            .find(|name| binary_exists(name))
            .unwrap_or("")
            .to_string()
    } else {
        engine.trim().to_string()
    };
    if engine == "none" {
        return Err("speech output is turned off (engine = none)".to_string());
    }
    if engine.is_empty() {
        return Err("no speech engine found (install espeak-ng, espeak, spd-say or piper)".to_string());
    }
    let cmd = match engine.as_str() {
        "espeak-ng" | "espeak" | "spd-say" => {
            let mut cmd = Cmd::new(engine.as_str());
            if !voice.is_empty() {
                cmd = cmd.arg("-v").arg(voice);
            }
            cmd.arg(text)
        }
        "piper" => {
            if voice.is_empty() {
                return Err("piper needs a voice model (set [tts] voice)".to_string());
            }
            Cmd::new("piper").arg("--output-raw").arg("--model").arg(voice).arg(text)
        }
        // macOS: the system `say` CLI.
        "say" | "avspeech" if voice.is_empty() => Cmd::new("say").arg("--").arg(text),
        "say" | "avspeech" => Cmd::new("say").arg("-v").arg(voice).arg("--").arg(text),
        other => return Err(format!("unsupported engine: {other}")),
    };
    blocking(move || Ok(CmdResult::from_output(cmd.output()))).await
}

// --------------------------------------------------------------------------- //
// per-app action profiles
// --------------------------------------------------------------------------- //
fn user_profiles_dir(state: &AppState) -> PathBuf {
    state
        .config_path
        .parent()
        .map(|dir| dir.join("profiles"))
        .unwrap_or_else(|| PathBuf::from("profiles"))
}

fn profile_python(state: &AppState, script: &str) -> Cmd {
    let repo = state.repo();
    Cmd::new(state.interpreter())
        .args(["-c", script])
        .cwd(&repo)
        .env("PYTHONPATH", repo.to_string_lossy().into_owned())
}

/// Every app profile as the assistant's loader sees it, plus any user override.
#[tauri::command]
pub async fn app_profiles_list(state: State<'_, AppState>) -> Result<Value, String> {
    let dir = user_profiles_dir(&state).to_string_lossy().into_owned();
    let cmd = profile_python(&state, profiles::LIST_SCRIPT).arg(dir);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        let stdout = String::from_utf8_lossy(&out.stdout);
        if !out.status.success() {
            return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
        }
        serde_json::from_str(stdout.trim()).map_err(|error| error.to_string())
    })
    .await
}

/// The app catalogue for the onboarding picker.
///
/// Seam for the per-app opt-in work: `assistant apps list --json` returns
/// `{apps:[{id,name,kind,icon?,enabled,preselected}]}`. Until that subcommand
/// ships the assistant exits non-zero and this returns `{ok:false}`, which the
/// UI notices and fills in from the profile loader. No opt-in state is written
/// here — the backend gate is owned by a separate lane.
#[tauri::command]
pub async fn apps_list(state: State<'_, AppState>) -> Result<Value, String> {
    let cmd = state.assistant(&["apps", "list", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| io_message(&error))?;
        Ok(parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        ))
    })
    .await
}

/// Save a user override (aliases, shortcuts, search address) for one app.
#[tauri::command]
pub async fn app_profile_save(
    state: State<'_, AppState>,
    id: String,
    profile: Value,
) -> Result<CmdResult, String> {
    if !profiles::valid_id(&id) {
        return Err("invalid profile id".to_string());
    }
    let dir = user_profiles_dir(&state).to_string_lossy().into_owned();
    let cmd = profile_python(&state, profiles::SAVE_SCRIPT)
        .arg(dir)
        .arg(id)
        .arg(profile.to_string());
    blocking(move || Ok(CmdResult::from_output(cmd.output()))).await
}

/// Enable/disable a set of apps in one call (writes override files).
///
/// Bulk opt-in for the picker/onboarding: each id is validated exactly like
/// `app_profile_save`, existing override fields are preserved, and only the
/// `enabled` gate changes.
#[tauri::command]
pub async fn app_profiles_set_enabled(
    state: State<'_, AppState>,
    ids: Vec<String>,
    enabled: bool,
) -> Result<CmdResult, String> {
    if ids.len() > 1000 {
        return Err("too many ids".to_string());
    }
    for id in &ids {
        if !profiles::valid_id(id) {
            return Err(format!("invalid profile id: {id}"));
        }
    }
    let dir = user_profiles_dir(&state).to_string_lossy().into_owned();
    let payload = Value::Array(ids.iter().map(|id| Value::String(id.clone())).collect());
    let cmd = profile_python(&state, profiles::SET_ENABLED_SCRIPT)
        .arg(dir)
        .arg(payload.to_string())
        .arg(if enabled { "true" } else { "false" });
    blocking(move || Ok(CmdResult::from_output(cmd.output()))).await
}

/// Drop the user override for one app, restoring the built-in actions.
#[tauri::command]
pub fn app_profile_reset(state: State<AppState>, id: String) -> Result<(), String> {
    if !profiles::valid_id(&id) {
        return Err("invalid profile id".to_string());
    }
    let path = user_profiles_dir(&state).join(profiles::override_file(&id));
    match std::fs::remove_file(&path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.to_string()),
    }
}

/// Open an https project/repo page in the default browser. Only `https://`
/// URLs are accepted, and the launcher (`xdg-open`, or `open` on macOS) gets
/// the URL as a single argument.
#[tauri::command]
pub fn open_url(url: String) -> Result<(), String> {
    let valid = url.starts_with("https://")
        && url.len() < 2048
        && !url.chars().any(|c| c.is_whitespace() || c.is_control());
    if !valid {
        return Err("only https:// links can be opened".to_string());
    }
    let launcher = if cfg!(target_os = "macos") { "open" } else { "xdg-open" };
    std::process::Command::new(launcher)
        .arg(&url)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map(|mut child| {
            // Reap the launcher so it never lingers as a zombie.
            std::thread::spawn(move || {
                let _ = child.wait();
            });
        })
        .map_err(|error| error.to_string())
}

/// The official installer the project publishes, as a single fixed string.
///
/// This is the *only* shell text the GUI ever hands to a shell. It is a
/// compile-time constant — never assembled from the UI, config or any other
/// input — so it cannot become a shell-injection vector.
const INSTALL_COMMAND: &str =
    "curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash";

/// Terminal emulators we know how to drive, in the order the project prefers
/// them. Each entry is `(program, args-before-the-command)`; the shell command
/// is appended as `sh -lc <INSTALL_COMMAND>`.
#[cfg(not(target_os = "macos"))]
fn terminal_candidates() -> Vec<(String, Vec<String>)> {
    let mut candidates: Vec<(String, Vec<String>)> = Vec::new();
    // $TERMINAL is the user's own choice, so it goes first.
    if let Ok(value) = std::env::var("TERMINAL") {
        let value = value.trim();
        if !value.is_empty() {
            let mut parts = value.split_whitespace();
            if let Some(program) = parts.next() {
                let mut prefix: Vec<String> = parts.map(str::to_string).collect();
                prefix.push("-e".to_string());
                candidates.push((program.to_string(), prefix));
            }
        }
    }
    // `xdg-terminal-exec` takes the command directly, with no `-e`.
    candidates.push(("xdg-terminal-exec".to_string(), Vec::new()));
    for (program, prefix) in [
        ("foot", "-e"),
        ("kitty", ""), // kitty runs the trailing command itself
        ("alacritty", "-e"),
        ("wezterm", "start --"),
        ("konsole", "-e"),
        ("gnome-terminal", "--"),
        ("xterm", "-e"),
    ] {
        let args = if prefix.is_empty() {
            Vec::new()
        } else {
            prefix.split_whitespace().map(str::to_string).collect()
        };
        candidates.push((program.to_string(), args));
    }
    candidates
}

/// Launch a shell command in the user's terminal so they can watch and confirm
/// it. We deliberately never run these ourselves: the user sees the command and
/// its output. `command` is always one of the app's compile-time constants — it
/// is never assembled from config or UI text.
#[cfg(not(target_os = "macos"))]
fn launch_terminal_command(command: &str) -> Result<(), String> {
    for (program, prefix) in terminal_candidates() {
        if !binary_exists(&program) {
            continue;
        }
        let mut args = prefix;
        args.push("sh".to_string());
        args.push("-lc".to_string());
        args.push(command.to_string());
        if let Ok(mut child) = std::process::Command::new(&program)
            .args(&args)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
        {
            // Reap it so it never lingers as a zombie once the terminal exits.
            std::thread::spawn(move || {
                let _ = child.wait();
            });
            return Ok(());
        }
    }
    Err("no terminal emulator found".to_string())
}

/// macOS: write the command to a temporary script and open it with Terminal
/// (`open -a Terminal <script>`), so the user sees and confirms it.
#[cfg(target_os = "macos")]
fn launch_terminal_command(command: &str) -> Result<(), String> {
    use std::io::Write;
    use std::os::unix::fs::PermissionsExt;

    let path = std::env::temp_dir().join(format!("utter-install-{}.command", std::process::id()));
    let script = format!(
        "#!/bin/sh\nset -e\n{command}\nprintf '\\nFinished. You can close this window.\\n'\n"
    );
    let mut file = std::fs::File::create(&path).map_err(|error| error.to_string())?;
    file.write_all(script.as_bytes()).map_err(|error| error.to_string())?;
    drop(file);
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755))
        .map_err(|error| error.to_string())?;

    std::process::Command::new("open")
        .arg("-a")
        .arg("Terminal")
        .arg(&path)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map(|mut child| {
            std::thread::spawn(move || {
                let _ = child.wait();
            });
        })
        .map_err(|error| format!("could not open Terminal: {error}"))
}

/// True when the `assistant` engine can actually run. A GUI-only AppImage/deb/
/// rpm ships no Python core, so this is how the UI knows to offer the installer.
#[tauri::command]
pub async fn engine_present(state: State<'_, AppState>) -> Result<bool, String> {
    let cmd = state.assistant(&["--version"]);
    blocking(move || Ok(cmd.output().map(|out| out.status.success()).unwrap_or(false))).await
}

/// Open the official installer in the user's terminal (never run it silently).
#[tauri::command]
pub async fn open_installer_terminal() -> Result<(), String> {
    blocking(|| launch_terminal_command(INSTALL_COMMAND)).await
}

/// The platform-appropriate install command for a known missing dependency, or
/// `None` when there is no safe automatic fix. Mirrors `DEP_HELP` in
/// `src/lib/links.ts`; keep the two lists in sync. Only these compile-time
/// constants ever reach a shell.
fn dep_fix(dep: &str) -> Option<&'static str> {
    if cfg!(target_os = "macos") {
        match dep {
            "ollama" => Some("brew install ollama && brew services start ollama"),
            "vocamac" => Some("brew install --cask vocamac"),
            _ => None,
        }
    } else if cfg!(target_os = "windows") {
        match dep {
            "ollama" => Some("winget install Ollama.Ollama"),
            _ => None,
        }
    } else {
        match dep {
            "ydotoold" => Some("systemctl --user enable --now ydotool"),
            "dbus_cli" => Some("sudo pacman -S glib2  # or: qt6-tools (qdbus6)"),
            "systemd_user" => Some("systemctl --user daemon-reload"),
            "input_group" => Some("sudo usermod -aG input $USER"),
            "uinput" => Some("sudo modprobe uinput"),
            _ => None,
        }
    }
}

/// Open the platform-appropriate fix for a missing dependency in the user's
/// terminal. The dep id selects a compile-time command (see `dep_fix`); the UI
/// never supplies shell text. Returns an error when there is no known fix.
#[tauri::command]
pub async fn open_dep_fix(dep: String) -> Result<(), String> {
    blocking(move || {
        let command =
            dep_fix(&dep).ok_or_else(|| format!("no automatic install for {dep}"))?;
        launch_terminal_command(command)
    })
    .await
}

/// Probe the planner endpoint — `GET <base>/models`.
#[tauri::command]
pub async fn test_endpoint(url: String) -> Result<CmdResult, String> {
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return Err("URL must start with http:// or https://".to_string());
    }
    let cmd = Cmd::new("curl").args([
        "-sS",
        "-m",
        "5",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        &url,
    ]);
    blocking(move || Ok(CmdResult::from_output(cmd.output()))).await
}

fn binary_exists(name: &str) -> bool {
    if name.contains('/') {
        return std::path::Path::new(name).is_file();
    }
    std::env::var("PATH")
        .unwrap_or_default()
        .split(':')
        .filter(|dir| !dir.is_empty())
        .any(|dir| std::path::Path::new(dir).join(name).is_file())
}

#[tauri::command]
pub fn which_many(names: Vec<String>) -> std::collections::HashMap<String, bool> {
    names
        .into_iter()
        .map(|name| {
            let present = binary_exists(&name);
            (name, present)
        })
        .collect()
}

/// Start recording the default input and emit `mic://level` (0.0–1.0).
#[tauri::command]
pub fn start_mic(app: AppHandle, state: State<AppState>) -> Result<(), String> {
    if state.children.lock().unwrap().contains_key("mic") {
        return Ok(());
    }
    let cmd = Cmd::new("pw-record").args([
        "--rate",
        "16000",
        "--channels",
        "1",
        "--format",
        "s16",
        "-",
    ]);
    let mut child = cmd.spawn_stdout_only().map_err(|error| error.to_string())?;
    let stdout = child.stdout.take().ok_or_else(|| err("no stdout pipe"))?;
    let children = state.children.clone();
    children.lock().unwrap().insert("mic".to_string(), child);

    let app_handle = app.clone();
    std::thread::spawn(move || {
        let mut reader = stdout;
        // ~64 ms of 16 kHz mono s16 audio per chunk keeps the level meter lively.
        let mut buffer = vec![0u8; 2048];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(count) => {
                    let bytes = &buffer[..count];
                    let mut sum = 0.0f64;
                    let mut samples = 0u32;
                    for chunk in bytes.chunks_exact(2) {
                        let sample = i16::from_le_bytes([chunk[0], chunk[1]]) as f64;
                        sum += sample * sample;
                        samples += 1;
                    }
                    if samples > 0 {
                        let rms = (sum / samples as f64).sqrt() / 32768.0;
                        let level = rms.sqrt().clamp(0.0, 1.0) as f32;
                        let _ = app_handle.emit("mic://level", serde_json::json!({ "level": level }));
                    }
                }
            }
        }
        children.lock().unwrap().remove("mic");
        let _ = app_handle.emit("mic://done", serde_json::json!({}));
    });

    Ok(())
}

#[tauri::command]
pub fn stop_mic(state: State<AppState>) -> Result<(), String> {
    state.kill_child("mic");
    Ok(())
}

// --------------------------------------------------------------------------- //
// logs
// --------------------------------------------------------------------------- //
#[tauri::command(rename_all = "camelCase")]
pub fn start_log_tail(
    app: AppHandle,
    state: State<AppState>,
    unit: String,
    tail_id: String,
) -> Result<(), String> {
    if !UNITS.contains(&unit.as_str()) {
        return Err(format!("unit not allowed: {unit}"));
    }
    state.kill_child(&tail_id);

    let cmd = if IS_MACOS {
        let Some(file) = launchd_log(&unit) else {
            return Err(format!("{unit} has no log on macOS"));
        };
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        let path = format!("{home}/Library/Logs/utter/{file}");
        Cmd::new("tail").args(["-n", "200", "-F", &path])
    } else {
        Cmd::new("journalctl").args([
            "--user",
            "-u",
            &unit,
            "-n",
            "200",
            "-o",
            "short-iso",
            "--no-pager",
            "-f",
        ])
    };
    let mut child = cmd.spawn_piped().map_err(|error| error.to_string())?;
    let stdout = child.stdout.take().ok_or_else(|| err("no stdout pipe"))?;
    let children = state.children.clone();
    children.lock().unwrap().insert(tail_id.clone(), child);

    let app_handle = app.clone();
    let id = tail_id.clone();
    let reader = BufReader::new(stdout);
    std::thread::spawn(move || {
        for line in reader.lines().map_while(Result::ok) {
            let _ = app_handle.emit(
                "log://line",
                serde_json::json!({ "tailId": id.clone(), "line": line }),
            );
        }
        let code = if let Some(mut child) = children.lock().unwrap().remove(&id) {
            child.wait().ok().and_then(|status| status.code()).unwrap_or(-1)
        } else {
            -1
        };
        let _ = app_handle.emit("log://done", serde_json::json!({ "tailId": id, "code": code }));
    });

    Ok(())
}

#[tauri::command(rename_all = "camelCase")]
pub fn stop_log_tail(state: State<AppState>, tail_id: String) -> Result<(), String> {
    state.kill_child(&tail_id);
    Ok(())
}

// --------------------------------------------------------------------------- //
// theme
// --------------------------------------------------------------------------- //
#[tauri::command]
pub fn get_theme_palette(state: State<AppState>) -> Palette {
    theme::read_palette(&state.theme_path)
}

// --------------------------------------------------------------------------- //
// support bundle
// --------------------------------------------------------------------------- //
fn timestamp() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(0);
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    // Howard Hinnant's civil-from-days.
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as i64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { year + 1 } else { year };
    format!(
        "{:04}{:02}{:02}-{:02}{:02}{:02}",
        year,
        month,
        day,
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

fn default_bundle_path() -> PathBuf {
    let home = std::env::var("HOME").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("."));
    let downloads = home.join("Downloads");
    let base = if downloads.is_dir() { downloads } else { home };
    base.join(format!("utter-support-{}.zip", timestamp()))
}

#[derive(Serialize)]
pub struct BundleResult {
    pub path: String,
    pub entries: usize,
}

#[tauri::command]
pub async fn export_bundle(
    state: State<'_, AppState>,
    dest: Option<String>,
) -> Result<BundleResult, String> {
    let repo = state.repo();
    let python = state.interpreter();
    let config_text = config::read_text(&state);
    let target = dest
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(default_bundle_path);

    blocking(move || {
        let mut entries: Vec<(String, Vec<u8>)> = Vec::new();
        let meta = serde_json::json!({
            "app": "utter-gui",
            "version": env!("CARGO_PKG_VERSION"),
            "created": timestamp(),
            "python": &python,
            "repo": repo.to_string_lossy(),
        });
        entries.push((
            "meta.json".to_string(),
            serde_json::to_vec_pretty(&meta).unwrap_or_default(),
        ));
        entries.push(("config.toml".to_string(), config_text.into_bytes()));

        let assistant_run = |args: &[&str]| -> String {
            let cmd = Cmd::new(&python)
                .arg("-m")
                .arg("assistant")
                .args(args.iter().copied())
                .cwd(&repo)
                .env("PYTHONPATH", repo.to_string_lossy().into_owned());
            match cmd.output() {
                Ok(out) => {
                    let stdout = String::from_utf8_lossy(&out.stdout).into_owned();
                    if stdout.trim().is_empty() {
                        String::from_utf8_lossy(&out.stderr).into_owned()
                    } else {
                        stdout
                    }
                }
                Err(error) => format!("(failed: {error})\n"),
            }
        };

        entries.push(("doctor.json".to_string(), assistant_run(&["doctor", "--json"]).into_bytes()));
        entries.push(("status.json".to_string(), assistant_run(&["status", "--json"]).into_bytes()));

        for unit in UNITS {
            let cmd = Cmd::new("journalctl").args([
                "--user",
                "-u",
                unit,
                "-n",
                "300",
                "-o",
                "short-iso",
                "--no-pager",
            ]);
            let text = match cmd.output() {
                Ok(out) => String::from_utf8_lossy(&out.stdout).into_owned(),
                Err(error) => format!("(failed: {error})\n"),
            };
            entries.push((format!("logs/{unit}.log"), text.into_bytes()));
        }

        let install_json = if cfg!(target_os = "windows") {
            crate::data_home().join("utter/state/install.json")
        } else {
            std::env::var("XDG_STATE_HOME")
                .map(PathBuf::from)
                .unwrap_or_else(|_| {
                    std::env::var("HOME")
                        .map(|home| PathBuf::from(home).join(".local/state"))
                        .unwrap_or_else(|_| PathBuf::from("."))
                })
                .join("utter/install.json")
        };
        if let Ok(text) = std::fs::read_to_string(&install_json) {
            entries.push(("install.json".to_string(), text.into_bytes()));
        }

        let count = entries.len();
        zip::write_zip(&target, &entries)?;
        Ok(BundleResult {
            path: target.to_string_lossy().into_owned(),
            entries: count,
        })
    })
    .await
}

#[cfg(test)]
mod runner_policy_tests {
    use super::*;

    fn temp_file(name: &str, body: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("utter-runner-policy-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join(name);
        std::fs::write(&path, body).unwrap();
        path
    }

    #[test]
    fn reads_enabled_ops_from_runner_config() {
        let path = temp_file(
            "policy.toml",
            "[policy]\nenabled_ops = [\"action.terminal\"]\ndisabled_ops = []\n",
        );
        assert_eq!(read_runner_policy(&path), vec!["action.terminal".to_string()]);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn missing_or_unparseable_config_yields_no_ops() {
        let missing = std::env::temp_dir().join("utter-runner-policy-absent.toml");
        let _ = std::fs::remove_file(&missing);
        assert!(read_runner_policy(&missing).is_empty());

        let broken = temp_file("broken.toml", "[policy\nenabled_ops = [\n");
        assert!(read_runner_policy(&broken).is_empty());
        let _ = std::fs::remove_file(&broken);
    }

    #[test]
    fn reads_disabled_plugins_and_validates_ids() {
        let path = temp_file("plugins.toml", "[plugins]\ndisabled = [\"b\"]\n");
        assert_eq!(read_runner_disabled_plugins(&path), vec!["b".to_string()]);
        let _ = std::fs::remove_file(&path);

        assert!(valid_plugin_id("utter"));
        assert!(valid_plugin_id("example_quicknote"));
        assert!(!valid_plugin_id(""));
        assert!(!valid_plugin_id("bad id"));
    }
}
