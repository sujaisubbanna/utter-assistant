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
use crate::state::AppState;
use crate::theme::{self, Palette};
use crate::zip;

/// Systemd user units the GUI is allowed to control.
const UNITS: &[&str] = &[
    "utter-runner",
    "utter-bridge",
    "utter-vision",
    "utter-planner",
    "utter-audio-defaults",
];

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

/// systemd unit -> launchd label. Units with no macOS counterpart map to None
/// and are reported as "not-found", so the General page needs no platform code.
fn launchd_label(unit: &str) -> Option<&'static str> {
    match unit {
        "utter-runner" => Some("com.utter.runner"),
        "utter-bridge" => Some("com.utter.assistant"),
        _ => None,
    }
}

fn launchd_log(unit: &str) -> Option<&'static str> {
    match unit {
        "utter-runner" => Some("runner.log"),
        "utter-bridge" => Some("utter.log"),
        _ => None,
    }
}

fn current_uid() -> String {
    std::process::Command::new("id")
        .arg("-u")
        .output()
        .ok()
        .map(|out| String::from_utf8_lossy(&out.stdout).trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| fallback_uid().to_string())
}

fn launchd_target(label: &str) -> String {
    format!("gui/{}/{label}", current_uid())
}

/// `launchctl print gui/<uid>/<label>` -> the UnitStatus shape systemd users expect.
fn parse_launchctl_print(unit: &str, text: &str, found: bool) -> UnitStatus {
    if !found {
        return UnitStatus {
            id: unit.to_string(),
            load_state: "not-found".to_string(),
            ..Default::default()
        };
    }
    let mut state = String::new();
    let mut pid: Option<String> = None;
    for raw in text.lines() {
        let line = raw.trim();
        if let Some(value) = line.strip_prefix("state = ") {
            state = value.trim().to_string();
        } else if let Some(value) = line.strip_prefix("pid = ") {
            pid = Some(value.trim().to_string());
        }
    }
    let running = state == "running" || pid.is_some();
    UnitStatus {
        id: unit.to_string(),
        load_state: "loaded".to_string(),
        active_state: if running { "active" } else { "inactive" }.to_string(),
        sub_state: if running { "running" } else { "dead" }.to_string(),
        // launchd agents installed by macos/setup.sh run at login.
        unit_file_state: "enabled".to_string(),
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

/// `$UTTER_MODELS`, else `$XDG_DATA_HOME/utter-models` — mirrors
/// `assistant/util.py::models_root`.
fn models_path() -> PathBuf {
    if let Ok(value) = std::env::var("UTTER_MODELS") {
        if !value.is_empty() {
            return PathBuf::from(value);
        }
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
    let restarted = state
        .systemctl(&["restart", "utter-runner"])
        .output()
        .map(|out| out.status.success())
        .unwrap_or(false);
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
    let _ = state.systemctl(&["restart", "utter-runner"]).output();
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

// --------------------------------------------------------------------------- //
// systemd
// --------------------------------------------------------------------------- //
#[derive(Default, Serialize)]
pub struct UnitStatus {
    pub id: String,
    pub load_state: String,
    pub active_state: String,
    pub sub_state: String,
    pub unit_file_state: String,
}

fn parse_systemctl_show(text: &str) -> Vec<UnitStatus> {
    let mut units: Vec<UnitStatus> = Vec::new();
    let mut current: Option<UnitStatus> = None;
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() {
            if let Some(unit) = current.take() {
                units.push(unit);
            }
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        if key == "Id" {
            if let Some(unit) = current.take() {
                units.push(unit);
            }
            // systemctl reports the canonical name (`foo.service`); callers use
            // the bare unit name.
            let id = value.strip_suffix(".service").unwrap_or(value);
            current = Some(UnitStatus {
                id: id.to_string(),
                ..Default::default()
            });
        } else if let Some(unit) = current.as_mut() {
            match key {
                "LoadState" => unit.load_state = value.to_string(),
                "ActiveState" => unit.active_state = value.to_string(),
                "SubState" => unit.sub_state = value.to_string(),
                "UnitFileState" => unit.unit_file_state = value.to_string(),
                _ => {}
            }
        }
    }
    if let Some(unit) = current.take() {
        units.push(unit);
    }
    units
}

#[tauri::command]
pub async fn systemctl_show(
    state: State<'_, AppState>,
    units: Vec<String>,
) -> Result<Vec<UnitStatus>, String> {
    if IS_MACOS {
        return blocking(move || {
            let mut statuses = Vec::new();
            for unit in &units {
                let status = match launchd_label(unit) {
                    None => parse_launchctl_print(unit, "", false),
                    Some(label) => {
                        let out = Cmd::new("launchctl")
                            .args(["print", &launchd_target(label)])
                            .output();
                        match out {
                            Ok(out) if out.status.success() => {
                                parse_launchctl_print(unit, &String::from_utf8_lossy(&out.stdout), true)
                            }
                            _ => parse_launchctl_print(unit, "", false),
                        }
                    }
                };
                statuses.push(status);
            }
            Ok(statuses)
        })
        .await;
    }
    let mut cmd = state.systemctl(&["show"]);
    for unit in &units {
        cmd = cmd.arg(unit.clone());
    }
    cmd = cmd.arg("--property=Id,LoadState,ActiveState,SubState,UnitFileState");
    blocking(move || {
        let out = cmd.output().map_err(|error| error.to_string())?;
        Ok(parse_systemctl_show(&String::from_utf8_lossy(&out.stdout)))
    })
    .await
}

#[tauri::command]
pub async fn systemctl(
    state: State<'_, AppState>,
    action: String,
    unit: String,
) -> Result<CmdResult, String> {
    if !SYSTEMCTL_ACTIONS.contains(&action.as_str()) {
        return Err(format!("action not allowed: {action}"));
    }
    if !UNITS.contains(&unit.as_str()) {
        return Err(format!("unit not allowed: {unit}"));
    }
    if IS_MACOS {
        let Some(label) = launchd_label(&unit) else {
            return Err(format!("{unit} has no launchd agent on macOS"));
        };
        let target = launchd_target(label);
        let cmd = match action.as_str() {
            "start" => Cmd::new("launchctl").args(["kickstart", &target]),
            "restart" => Cmd::new("launchctl").args(["kickstart", "-k", &target]),
            "stop" => Cmd::new("launchctl").args(["kill", "SIGTERM", &target]),
            "enable" => Cmd::new("launchctl").args(["enable", &target]),
            "disable" => Cmd::new("launchctl").args(["disable", &target]),
            "is-active" | "is-enabled" => Cmd::new("launchctl").args(["print", &target]),
            other => return Err(format!("action not allowed: {other}")),
        };
        return blocking(move || Ok(CmdResult::from_output(cmd.output()))).await;
    }
    let cmd = state.systemctl(&[action.as_str(), unit.as_str()]);
    blocking(move || Ok(CmdResult::from_output(cmd.output()))).await
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

/// Launch the installer in the user's terminal so they can watch and confirm it.
///
/// We deliberately never download and run the installer ourselves: the user
/// sees the command and its output.
#[cfg(not(target_os = "macos"))]
fn launch_installer_terminal() -> Result<(), String> {
    for (program, prefix) in terminal_candidates() {
        if !binary_exists(&program) {
            continue;
        }
        let mut args = prefix;
        args.push("sh".to_string());
        args.push("-lc".to_string());
        args.push(INSTALL_COMMAND.to_string());
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

/// macOS: write the fixed installer command to a temporary script and open it
/// with Terminal (`open -a Terminal <script>`), so the user sees and confirms it.
#[cfg(target_os = "macos")]
fn launch_installer_terminal() -> Result<(), String> {
    use std::io::Write;
    use std::os::unix::fs::PermissionsExt;

    let path = std::env::temp_dir().join(format!("utter-install-{}.command", std::process::id()));
    let script = format!(
        "#!/bin/sh\nset -e\n{INSTALL_COMMAND}\nprintf '\\nInstaller finished. You can close this window.\\n'\n"
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
    blocking(launch_installer_terminal).await
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

        let install_json = std::env::var("XDG_STATE_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| {
                std::env::var("HOME")
                    .map(|home| PathBuf::from(home).join(".local/state"))
                    .unwrap_or_else(|_| PathBuf::from("."))
            })
            .join("utter/install.json");
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
