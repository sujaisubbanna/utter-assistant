//! Tauri commands — the whole backend contract.
//!
//! Everything that can block runs off the UI thread. Subprocesses are always
//! spawned from a **list of arguments** (never a shell string), and streaming
//! output is forwarded to the frontend with `emit`.

use std::io::{BufRead, BufReader, Read};
use std::path::PathBuf;

use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, State};

use crate::config;
use crate::profiles;
use crate::process::{Cmd, CmdResult};
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
    pub runner_sock: String,
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
        repo: state.repo.to_string_lossy().into_owned(),
        python: state.python.clone(),
        config_path: state.config_path.to_string_lossy().into_owned(),
        theme_path: state.theme_path.to_string_lossy().into_owned(),
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
// assistant CLI passthroughs
// --------------------------------------------------------------------------- //
#[tauri::command]
pub async fn status(state: State<'_, AppState>) -> Result<Value, String> {
    let cmd = state.assistant(&["status", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| error.to_string())?;
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
        let out = cmd.output().map_err(|error| error.to_string())?;
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
        let out = cmd.output().map_err(|error| error.to_string())?;
        Ok(parse_json_lossy(
            &String::from_utf8_lossy(&out.stdout),
            &String::from_utf8_lossy(&out.stderr),
        ))
    })
    .await
}

#[tauri::command]
pub async fn models_list(state: State<'_, AppState>) -> Result<Value, String> {
    let cmd = state.assistant(&["models", "list", "--json"]);
    blocking(move || {
        let out = cmd.output().map_err(|error| error.to_string())?;
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
        let out = cmd.output().map_err(|error| error.to_string())?;
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
    let mut child = cmd.spawn_piped().map_err(|error| error.to_string())?;
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
    let voice = if voice.trim().is_empty() {
        "en".to_string()
    } else {
        voice
    };
    let cmd = match engine.as_str() {
        "espeak-ng" => Cmd::new("espeak-ng").arg("-v").arg(voice).arg(text),
        "espeak" => Cmd::new("espeak").arg("-v").arg(voice).arg(text),
        "spd-say" => Cmd::new("spd-say").arg("-v").arg(voice).arg(text),
        "piper" => Cmd::new("piper").arg("--output-raw").arg("--model").arg(voice).arg(text),
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
    let repo = state.repo.to_string_lossy().into_owned();
    Cmd::new(&state.python)
        .args(["-c", script])
        .cwd(&state.repo)
        .env("PYTHONPATH", repo)
}

/// Every app profile as the assistant's loader sees it, plus any user override.
#[tauri::command]
pub async fn app_profiles_list(state: State<'_, AppState>) -> Result<Value, String> {
    let dir = user_profiles_dir(&state).to_string_lossy().into_owned();
    let cmd = profile_python(&state, profiles::LIST_SCRIPT).arg(dir);
    blocking(move || {
        let out = cmd.output().map_err(|error| error.to_string())?;
        let stdout = String::from_utf8_lossy(&out.stdout);
        if !out.status.success() {
            return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
        }
        serde_json::from_str(stdout.trim()).map_err(|error| error.to_string())
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

    let cmd = Cmd::new("journalctl").args([
        "--user",
        "-u",
        &unit,
        "-n",
        "200",
        "-o",
        "short-iso",
        "--no-pager",
        "-f",
    ]);
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
    let python = state.python.clone();
    let repo = state.repo.clone();
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
