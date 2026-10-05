//! Windows self-install: per-user Scheduled Tasks instead of launchd/systemd.
//!
//! The small analog of [`crate::macos_setup`]. Windows has no `.app` bundle to
//! unpack, so the installer only has to register the two background services as
//! logon-triggered Scheduled Tasks (`schtasks /Create … /SC ONLOGON`). Each task
//! runs this app binary (`utter.exe --runner` / `--daemon`), which supervises
//! the Python child — the same mechanism the launchd agents use, so the service
//! rows on the General/Setup pages keep working.
//!
//! On every non-Windows platform each entry point reports `supported: false`
//! (status) or a readable error (install/uninstall), mirroring `macos_setup`.

use std::path::PathBuf;
use std::process::Command;

use serde::Serialize;
use tauri::State;

use crate::state::AppState;

/// Task name -> flag passed to this binary. The names are the systemd unit
/// labels the UI already shows, reused verbatim as Scheduled Task names.
const TASKS: &[(&str, &str)] = &[("utter-runner", "--runner"), ("utter.service", "--daemon")];

pub const IS_WINDOWS: bool = cfg!(target_os = "windows");

fn launcher() -> Option<PathBuf> {
    std::env::current_exe().ok()
}

fn run(cmd: &mut Command) -> Result<String, String> {
    let out = cmd
        .output()
        .map_err(|error| format!("{:?}: {error}", cmd.get_program()))?;
    if out.status.success() {
        Ok(String::from_utf8_lossy(&out.stdout).into_owned())
    } else {
        let stderr = String::from_utf8_lossy(&out.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
        Err(if stderr.is_empty() { stdout } else { stderr })
    }
}

#[derive(Serialize, Clone)]
pub struct WindowsInstallStatus {
    pub supported: bool,
    pub installed: bool,
    pub tasks: Vec<String>,
    pub python: String,
    pub repo: String,
}

fn status(state: &AppState) -> WindowsInstallStatus {
    let installed = IS_WINDOWS && TASKS.iter().all(|(name, _)| crate::service::task_installed(name));
    WindowsInstallStatus {
        supported: IS_WINDOWS,
        installed,
        tasks: TASKS.iter().map(|(name, _)| (*name).to_string()).collect(),
        python: state.python(),
        repo: state.repo().to_string_lossy().into_owned(),
    }
}

#[tauri::command]
pub fn windows_install_status(state: State<AppState>) -> WindowsInstallStatus {
    status(&state)
}

/// Create (or overwrite) both Scheduled Tasks. `/SC ONLOGON` starts them on
/// every interactive logon; `/F` makes a re-run idempotent.
fn install_service() -> Result<(), String> {
    let exe = launcher().ok_or_else(|| "cannot determine the app's own path".to_string())?;
    let exe = exe.to_string_lossy().into_owned();
    for (name, flag) in TASKS {
        // The task runs a single command line: `"<exe>" --runner`.
        let task_run = format!("\"{exe}\" {flag}");
        run(Command::new("schtasks").args([
            "/Create", "/TN", name, "/TR", &task_run, "/SC", "ONLOGON", "/F",
        ]))
        .map_err(|error| format!("schtasks create {name}: {error}"))?;
        // `/Create` enables by default; make the intent explicit.
        let _ = Command::new("schtasks")
            .args(["/Change", "/TN", name, "/ENABLE"])
            .output();
    }
    Ok(())
}

/// Delete both Scheduled Tasks. A task that is already gone counts as success.
fn uninstall_service() -> Result<(), String> {
    for (name, _) in TASKS {
        let out = Command::new("schtasks")
            .args(["/Delete", "/TN", name, "/F"])
            .output()
            .map_err(|error| format!("schtasks delete {name}: {error}"))?;
        if !out.status.success() {
            let stderr = String::from_utf8_lossy(&out.stderr).trim().to_string();
            // "cannot find the file specified" means it was never installed.
            if !stderr.is_empty() && !stderr.to_lowercase().contains("cannot find") {
                return Err(format!("schtasks delete {name}: {stderr}"));
            }
        }
    }
    Ok(())
}

#[tauri::command]
pub async fn windows_install_service(
    state: State<'_, AppState>,
) -> Result<WindowsInstallStatus, String> {
    if !IS_WINDOWS {
        return Err("scheduled tasks only exist on Windows".to_string());
    }
    tauri::async_runtime::spawn_blocking(install_service)
        .await
        .map_err(|error| error.to_string())??;
    Ok(status(&state))
}

#[tauri::command]
pub async fn windows_uninstall_service(
    state: State<'_, AppState>,
) -> Result<WindowsInstallStatus, String> {
    if !IS_WINDOWS {
        return Err("scheduled tasks only exist on Windows".to_string());
    }
    tauri::async_runtime::spawn_blocking(uninstall_service)
        .await
        .map_err(|error| error.to_string())??;
    Ok(status(&state))
}
