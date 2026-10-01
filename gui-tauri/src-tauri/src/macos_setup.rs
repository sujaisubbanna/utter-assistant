//! macOS self-install: the drag-and-drop path.
//!
//! The `.app` ships a relocatable Python runtime plus the assistant core as a
//! single resource (`runtime.tar.gz`, assembled by `scripts/build-macos-runtime.sh`
//! in CI). On first launch the Set up page calls [`macos_install`], which:
//!
//! 1. unpacks the tarball into `~/Library/Application Support/utter/runtime/`
//!    (atomically: into a temp dir, then renamed);
//! 2. writes the two launchd agents (`com.utter.runner`, `com.utter.assistant`)
//!    to `~/Library/LaunchAgents/` with the runtime's python and bootstraps them;
//! 3. points the app's own `python`/`repo` at the runtime so every other
//!    command (status, permissions, profiles…) uses it immediately.
//!
//! No terminal, no scripts. Everything shells out with list arguments and only
//! to `/usr/bin` tools that exist on every Mac (`tar`, `launchctl`, `id`).
//! On Linux every entry point reports `supported: false` and does nothing.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State};

use crate::state::AppState;

const RUNTIME_TARBALL: &str = "runtime.tar.gz";
const RUNTIME_VERSION: &str = "runtime.version";
const ASSISTANT_LABEL: &str = "com.utter.assistant";
const RUNNER_LABEL: &str = "com.utter.runner";
const ASSISTANT_PLIST: &str = include_str!("../../../macos/com.utter.assistant.plist");
const RUNNER_PLIST: &str = include_str!("../../../macos/com.utter.runner.plist");

pub const IS_MACOS: bool = cfg!(target_os = "macos");

fn home() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/"))
}

pub fn app_support() -> PathBuf {
    home().join("Library/Application Support/utter")
}

pub fn runtime_root() -> PathBuf {
    app_support().join("runtime")
}

fn log_dir() -> PathBuf {
    home().join("Library/Logs/utter")
}

fn agents_dir() -> PathBuf {
    home().join("Library/LaunchAgents")
}

fn runtime_python(root: &Path) -> PathBuf {
    root.join("python/bin/python3")
}

fn runtime_core(root: &Path) -> PathBuf {
    root.join("core")
}

/// `(core, python)` of an installed runtime, if it looks complete.
pub fn installed_runtime() -> Option<(PathBuf, String)> {
    if !IS_MACOS {
        return None;
    }
    let root = runtime_root();
    let core = runtime_core(&root);
    let python = runtime_python(&root);
    if core.join("assistant").is_dir() && python.exists() {
        Some((core, python.to_string_lossy().into_owned()))
    } else {
        None
    }
}

fn installed_version() -> Option<String> {
    fs::read_to_string(runtime_root().join("VERSION"))
        .ok()
        .map(|text| text.trim().to_string())
        .filter(|text| !text.is_empty())
}

fn resource(app: &AppHandle, name: &str) -> Option<PathBuf> {
    let dir = app.path().resource_dir().ok()?;
    let path = dir.join(name);
    path.exists().then_some(path)
}

fn bundled_version(app: &AppHandle) -> Option<String> {
    let path = resource(app, RUNTIME_VERSION)?;
    fs::read_to_string(path)
        .ok()
        .map(|text| text.trim().to_string())
        .filter(|text| !text.is_empty())
}

fn uid() -> String {
    Command::new("id")
        .arg("-u")
        .output()
        .ok()
        .map(|out| String::from_utf8_lossy(&out.stdout).trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "501".to_string())
}

pub fn agents_installed() -> bool {
    let dir = agents_dir();
    dir.join(format!("{ASSISTANT_LABEL}.plist")).exists()
        && dir.join(format!("{RUNNER_LABEL}.plist")).exists()
}

#[derive(Serialize, Clone)]
pub struct InstallStatus {
    pub supported: bool,
    pub bundled: bool,
    pub bundled_version: Option<String>,
    pub installed: bool,
    pub installed_version: Option<String>,
    pub update_available: bool,
    pub agents_installed: bool,
    pub python: String,
    pub repo: String,
    pub runtime_dir: String,
}

fn status(app: &AppHandle, state: &AppState) -> InstallStatus {
    let bundled_version = bundled_version(app);
    let bundled = IS_MACOS && resource(app, RUNTIME_TARBALL).is_some();
    let installed = installed_runtime().is_some();
    let installed_version = installed_version();
    let update_available = installed
        && bundled
        && bundled_version.is_some()
        && bundled_version != installed_version;
    InstallStatus {
        supported: IS_MACOS,
        bundled,
        bundled_version,
        installed,
        installed_version,
        update_available,
        agents_installed: IS_MACOS && agents_installed(),
        python: state.python(),
        repo: state.repo().to_string_lossy().into_owned(),
        runtime_dir: runtime_root().to_string_lossy().into_owned(),
    }
}

#[tauri::command]
pub fn macos_install_status(app: AppHandle, state: State<AppState>) -> InstallStatus {
    status(&app, &state)
}

fn emit_progress(app: &AppHandle, stage: &str, message: &str) {
    let _ = app.emit(
        "setup://progress",
        serde_json::json!({ "stage": stage, "message": message }),
    );
}

fn run(cmd: &mut Command) -> Result<String, String> {
    let out = cmd.output().map_err(|error| format!("{:?}: {error}", cmd.get_program()))?;
    if out.status.success() {
        Ok(String::from_utf8_lossy(&out.stdout).into_owned())
    } else {
        let stderr = String::from_utf8_lossy(&out.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
        Err(if stderr.is_empty() { stdout } else { stderr })
    }
}

/// Unpack the bundled runtime into place. Returns `(core, python)`.
fn unpack_runtime(app: &AppHandle) -> Result<(PathBuf, String), String> {
    let tarball = resource(app, RUNTIME_TARBALL)
        .ok_or_else(|| "this build has no bundled runtime (built from source?)".to_string())?;
    let support = app_support();
    fs::create_dir_all(&support).map_err(|error| error.to_string())?;
    let tmp = support.join(format!(".runtime-{}", std::process::id()));
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(&tmp).map_err(|error| error.to_string())?;

    emit_progress(app, "unpack", "Unpacking the assistant and its Python runtime…");
    run(Command::new("/usr/bin/tar")
        .arg("-xzf")
        .arg(&tarball)
        .arg("-C")
        .arg(&tmp))?;
    let extracted = tmp.join("runtime");
    if !runtime_python(&extracted).exists() || !runtime_core(&extracted).join("assistant").is_dir() {
        let _ = fs::remove_dir_all(&tmp);
        return Err("the bundled runtime is incomplete".to_string());
    }

    // Swap in atomically; keep the previous runtime until the new one is in place.
    let root = runtime_root();
    let old = support.join(format!(".runtime-old-{}", std::process::id()));
    if root.exists() {
        fs::rename(&root, &old).map_err(|error| format!("could not move the old runtime aside: {error}"))?;
    }
    if let Err(error) = fs::rename(&extracted, &root) {
        if old.exists() {
            let _ = fs::rename(&old, &root);
        }
        let _ = fs::remove_dir_all(&tmp);
        return Err(format!("could not install the runtime: {error}"));
    }
    let _ = fs::remove_dir_all(&tmp);
    let _ = fs::remove_dir_all(&old);

    // The quarantine flag the .app carries must not follow the python binary
    // around, or every helper it spawns gets a Gatekeeper dialog.
    let _ = Command::new("/usr/bin/xattr")
        .args(["-dr", "com.apple.quarantine"])
        .arg(&root)
        .output();

    Ok((runtime_core(&root), runtime_python(&root).to_string_lossy().into_owned()))
}

fn render_plist(template: &str, python: &str, repo: &Path, logs: &Path) -> String {
    template
        .replace("@PYTHON@", python)
        .replace("@REPO@", &repo.to_string_lossy())
        .replace("@LOGDIR@", &logs.to_string_lossy())
}

/// Write + bootstrap the two launchd agents for the given runtime.
fn install_agents(app: &AppHandle, core: &Path, python: &str) -> Result<(), String> {
    emit_progress(app, "agents", "Installing the background agents…");
    let logs = log_dir();
    let dir = agents_dir();
    fs::create_dir_all(&logs).map_err(|error| error.to_string())?;
    fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let domain = format!("gui/{}", uid());
    for (label, template) in [(RUNNER_LABEL, RUNNER_PLIST), (ASSISTANT_LABEL, ASSISTANT_PLIST)] {
        let path = dir.join(format!("{label}.plist"));
        fs::write(&path, render_plist(template, python, core, &logs))
            .map_err(|error| format!("could not write {}: {error}", path.display()))?;
        // bootout fails harmlessly when the agent was not loaded yet.
        let _ = Command::new("/bin/launchctl")
            .args(["bootout", &format!("{domain}/{label}")])
            .output();
        run(Command::new("/bin/launchctl")
            .args(["bootstrap", &domain])
            .arg(&path))
        .map_err(|error| format!("launchctl bootstrap {label}: {error}"))?;
    }
    Ok(())
}

/// Unpack the bundled runtime (if newer or missing), install the agents and
/// repoint the app at the runtime. Safe to call again: it re-installs.
#[tauri::command]
pub async fn macos_install(app: AppHandle, state: State<'_, AppState>) -> Result<InstallStatus, String> {
    if !IS_MACOS {
        return Err("self-install only exists on macOS".to_string());
    }
    let handle = app.clone();
    let (core, python) = tauri::async_runtime::spawn_blocking(move || {
        let (core, python) = unpack_runtime(&handle)?;
        install_agents(&handle, &core, &python)?;
        emit_progress(&handle, "done", "Installed.");
        Ok::<_, String>((core, python))
    })
    .await
    .map_err(|error| error.to_string())??;
    state.set_runtime(core, python);
    let _ = crate::config::ensure(&state);
    Ok(status(&app, &state))
}

/// Re-write + restart the agents without touching the runtime (after a repair).
#[tauri::command]
pub async fn macos_reinstall_agents(app: AppHandle, state: State<'_, AppState>) -> Result<InstallStatus, String> {
    if !IS_MACOS {
        return Err("launchd agents only exist on macOS".to_string());
    }
    let (core, python) = installed_runtime().ok_or_else(|| "the runtime is not installed yet".to_string())?;
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || install_agents(&handle, &core, &python))
        .await
        .map_err(|error| error.to_string())??;
    Ok(status(&app, &state))
}
