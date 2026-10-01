//! utter settings — a Tauri v2 desktop app.
//!
//! The window is a *client*: it reads and writes configuration and asks the
//! `assistant` CLI / runner to do the real work. No business logic lives here.

mod commands;
mod config;
mod macos_setup;
mod process;
mod profiles;
mod state;
mod theme;
mod zip;

use std::path::{Path, PathBuf};

use state::AppState;

/// Find the utter checkout. In development the binary lives in
/// `<repo>/gui-tauri/src-tauri`; a packaged build falls back to env/dotdirs.
fn locate_repo() -> PathBuf {
    if let Ok(value) = std::env::var("UTTER_REPO") {
        let path = PathBuf::from(value);
        if path.join("assistant").is_dir() {
            return path;
        }
    }
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    if let Some(repo) = manifest.parent().and_then(|path| path.parent()) {
        if repo.join("assistant").is_dir() {
            return repo.to_path_buf();
        }
    }
    // Packaged builds: where the installers put the core. A .app launched from
    // Finder inherits no shell environment, so these are checked by path.
    let home = home_dir();
    for candidate in [
        data_home().join("utter"),                              // Linux: $PREFIX/share/utter
        home.join("Library/Application Support/utter/core"),    // macOS: macos/setup.sh symlink
        home.join("utter-assistant"),
    ] {
        if candidate.join("assistant").is_dir() {
            return candidate;
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

/// Resolve the interpreter that can run `python -m assistant`.
fn locate_python(repo: &Path) -> String {
    if let Ok(value) = std::env::var("UTTER_PYTHON") {
        if !value.is_empty() && Path::new(&value).exists() {
            return value;
        }
    }
    for candidate in [
        repo.join(".venv-agent/bin/python"),
        repo.join(".venv-macos/bin/python"),
        repo.join(".venv/bin/python"),
    ] {
        if candidate.exists() {
            return candidate.to_string_lossy().into_owned();
        }
    }
    "python3".to_string()
}

fn home_dir() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/"))
}

fn config_path() -> PathBuf {
    if let Ok(value) = std::env::var("XDG_CONFIG_HOME") {
        if !value.is_empty() {
            return PathBuf::from(value).join("utter/config.toml");
        }
    }
    home_dir().join(".config/utter/config.toml")
}

fn data_home() -> PathBuf {
    if let Ok(value) = std::env::var("XDG_DATA_HOME") {
        if !value.is_empty() {
            return PathBuf::from(value);
        }
    }
    home_dir().join(".local/share")
}

fn theme_path() -> PathBuf {
    if let Ok(value) = std::env::var("UTTER_THEME_CSS") {
        if !value.is_empty() {
            return PathBuf::from(value);
        }
    }
    data_home().join("utter/colors.css")
}

/// Headless supervisor used by the launchd agents (see main.rs).
pub fn supervise(mode: &str) -> i32 {
    let mut repo = locate_repo();
    let mut python = locate_python(&repo);
    if std::env::var("UTTER_REPO").is_err() {
        if let Some((core, runtime_python)) = macos_setup::installed_runtime() {
            repo = core;
            python = runtime_python;
        }
    }
    macos_setup::supervise_python(mode, &repo, &python)
}

pub fn run() {
    let mut repo = locate_repo();
    let mut python = locate_python(&repo);
    // macOS drag-and-drop install: prefer the runtime the app unpacked itself,
    // unless the developer pointed UTTER_REPO somewhere explicitly.
    if std::env::var("UTTER_REPO").is_err() {
        if let Some((core, runtime_python)) = macos_setup::installed_runtime() {
            repo = core;
            python = runtime_python;
        }
    }
    let state = AppState::new(repo, python, config_path(), theme_path());
    // Make sure a config exists before the UI starts editing it.
    let _ = config::ensure(&state);

    tauri::Builder::default()
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            commands::app_info,
            commands::boot_params,
            commands::get_config,
            commands::set_config,
            commands::set_config_many,
            commands::status,
            commands::doctor,
            commands::recommend,
            commands::models_list,
            commands::models_show,
            commands::models_remove,
            commands::models_prune,
            commands::start_models_pull,
            commands::cancel_models_pull,
            commands::systemctl_show,
            commands::systemctl,
            commands::pactl_sources,
            commands::tts_test,
            commands::test_endpoint,
            commands::open_url,
            commands::app_profiles_list,
            commands::app_profile_save,
            commands::app_profile_reset,
            commands::which_many,
            commands::start_mic,
            commands::stop_mic,
            commands::start_log_tail,
            commands::stop_log_tail,
            commands::get_theme_palette,
            commands::export_bundle,
            commands::platform_info,
            commands::open_settings_pane,
            commands::macos_permissions,
            commands::macos_request_permission,
            macos_setup::macos_install_status,
            macos_setup::macos_install,
            macos_setup::macos_reinstall_agents,
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            if let Err(error) = theme::start_watcher(handle) {
                eprintln!("utter-gui: theme watcher unavailable: {error}");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the utter settings app");
}
