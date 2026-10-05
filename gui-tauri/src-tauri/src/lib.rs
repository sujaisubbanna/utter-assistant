//! utter settings — a Tauri v2 desktop app.
//!
//! The window is a *client*: it reads and writes configuration and asks the
//! `assistant` CLI / runner to do the real work. No business logic lives here.

mod commands;
mod config;
mod macos_setup;
mod process;
mod profiles;
mod service;
mod state;
mod theme;
mod windows_setup;
mod zip;

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

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

/// True when `candidate` is a runnable Python >= 3.12 that can `import tomllib`.
///
/// The assistant imports `tomllib` at startup, but `pyproject.toml` requires
/// `>=3.12`; on macOS a bare `python3` on `$PATH` is Apple's 3.9 stub, which has
/// neither. One probe answers both questions.
fn interpreter_ok(candidate: &Path) -> bool {
    if !candidate.is_file() {
        return false;
    }
    Command::new(candidate)
        .arg("-c")
        .arg("import sys, tomllib; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

/// Resolve the interpreter that can run `python -m assistant`.
///
/// Every candidate — `$UTTER_PYTHON`, the checkouts' virtualenvs, the bundled
/// runtime and only then `python3` on `$PATH` — must be Python >= 3.12 *and*
/// import `tomllib`. Returning an older interpreter here is what produced the
/// macOS launchd crash loop (Apple's `/usr/bin/python3` is 3.9). Callers choose
/// what to do with the `Err` (the GUI keeps its window so the Set up page can
/// install the runtime; the headless supervisor exits non-zero).
fn locate_python(repo: &Path) -> Result<String, String> {
    if let Ok(value) = std::env::var("UTTER_PYTHON") {
        if !value.is_empty() {
            let path = Path::new(&value);
            if interpreter_ok(path) {
                return Ok(value);
            }
            return Err(format!(
                "UTTER_PYTHON={value} is not a Python >= 3.12 interpreter with tomllib"
            ));
        }
    }
    // The relocatable runtime the app unpacks is the blessed interpreter and
    // comes first: <root>/core is the repo, <root>/python the interpreter
    // (see scripts/build-macos-runtime.sh).
    let mut candidates = vec![
        repo.join("../python/bin/python3"),
        repo.join("python/bin/python3"),
        repo.join(".venv-macos/bin/python"),
        repo.join(".venv-agent/bin/python"),
        repo.join(".venv/bin/python"),
    ];
    if let Ok(path_var) = std::env::var("PATH") {
        for dir in std::env::split_paths(&path_var) {
            candidates.push(dir.join("python3.12"));
            candidates.push(dir.join("python3"));
        }
    }

    let mut rejected = Vec::new();
    for candidate in &candidates {
        if !candidate.exists() {
            continue;
        }
        if interpreter_ok(candidate) {
            return Ok(candidate.to_string_lossy().into_owned());
        }
        rejected.push(candidate.display().to_string());
    }

    let detail = if rejected.is_empty() {
        "no python3 on $PATH".to_string()
    } else {
        format!(
            "found {} but none is Python >= 3.12 with tomllib",
            rejected.join(", ")
        )
    };
    Err(format!("no usable Python interpreter: {detail}"))
}

fn home_dir() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/"))
}

fn config_path() -> PathBuf {
    if cfg!(target_os = "windows") {
        if let Ok(value) = std::env::var("APPDATA") {
            if !value.is_empty() {
                return PathBuf::from(value).join("utter/config.toml");
            }
        }
        return home_dir().join("AppData/Roaming/utter/config.toml");
    }
    if let Ok(value) = std::env::var("XDG_CONFIG_HOME") {
        if !value.is_empty() {
            return PathBuf::from(value).join("utter/config.toml");
        }
    }
    home_dir().join(".config/utter/config.toml")
}

/// Per-user data root. Windows uses `%LOCALAPPDATA%` (so `models`, `runtime`
/// and `state` live under `%LOCALAPPDATA%\utter`); elsewhere the freedesktop
/// `$XDG_DATA_HOME` is unchanged.
pub(crate) fn data_home() -> PathBuf {
    if cfg!(target_os = "windows") {
        if let Ok(value) = std::env::var("LOCALAPPDATA") {
            if !value.is_empty() {
                return PathBuf::from(value);
            }
        }
        return home_dir().join("AppData/Local");
    }
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
    // On macOS the unpacked runtime is the blessed interpreter: it is a
    // relocatable CPython with all deps, while $PATH python3 may be Apple's
    // stub (3.9, no tomllib). Prefer it whenever it is usable.
    if let Some((core, runtime_python)) = macos_setup::installed_runtime() {
        if interpreter_ok(Path::new(&runtime_python)) {
            return macos_setup::supervise_python(mode, &core, &runtime_python);
        }
        eprintln!(
            "utter: bundled interpreter {runtime_python} is not Python >= 3.12 with tomllib; \
             reinstall the runtime from utter.app instead of launching it"
        );
        return 1;
    }
    // An incomplete self-install (runtime core present, bundled python gone)
    // must fail loudly. Falling back to system python3 here is what produced the
    // endless launchd crash loop, because Apple's python3 lacks tomllib.
    if let Some(core) = macos_setup::runtime_core_without_python() {
        eprintln!(
            "utter: found the runtime core at {} but its bundled Python is missing; \
             reinstall the runtime from utter.app (refusing to fall back to system python3)",
            core.display()
        );
        return 1;
    }
    let repo = locate_repo();
    let python = match locate_python(&repo) {
        Ok(python) => python,
        Err(error) => {
            eprintln!("utter: {error}");
            return 1;
        }
    };
    macos_setup::supervise_python(mode, &repo, &python)
}

pub fn run() {
    let mut repo = locate_repo();
    let mut python = match locate_python(&repo) {
        Ok(python) => python,
        Err(error) => {
            // The window must still open: on macOS the Set up page installs the
            // bundled runtime, which fixes the interpreter. Commands that need
            // python report a spawn error until then.
            eprintln!("utter-gui: {error}; open the Set up page to install the runtime");
            String::new()
        }
    };
    // macOS drag-and-drop install: prefer the runtime the app unpacked itself,
    // unless the developer pointed UTTER_REPO somewhere explicitly.
    if std::env::var("UTTER_REPO").is_err() {
        if let Some((core, runtime_python)) = macos_setup::installed_runtime() {
            if interpreter_ok(Path::new(&runtime_python)) {
                repo = core;
                python = runtime_python;
            } else {
                eprintln!(
                    "utter-gui: bundled interpreter {runtime_python} is not Python >= 3.12 \
                     with tomllib; leaving it unused"
                );
            }
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
            commands::get_runner_policy,
            commands::set_runner_policy,
            commands::get_runner_plugins,
            commands::set_runner_plugins,
            commands::status,
            commands::doctor,
            commands::recommend,
            commands::context_windows,
            commands::dictation_pending,
            commands::dictation_deliver,
            commands::dictation_dismiss,
            commands::models_list,
            commands::models_show,
            commands::models_remove,
            commands::models_prune,
            commands::start_models_pull,
            commands::cancel_models_pull,
            commands::inference_status,
            commands::start_inference_install,
            commands::cancel_inference_install,
            commands::systemctl_show,
            commands::systemctl,
            commands::service_show,
            commands::service_control,
            commands::pactl_sources,
            commands::tts_test,
            commands::test_endpoint,
            commands::open_url,
            commands::app_profiles_list,
            commands::apps_list,
            commands::app_profile_save,
            commands::app_profiles_set_enabled,
            commands::app_profile_reset,
            commands::which_many,
            commands::engine_present,
            commands::open_installer_terminal,
            commands::open_dep_fix,
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
            macos_setup::macos_restart_agents,
            windows_setup::windows_install_status,
            windows_setup::windows_install_service,
            windows_setup::windows_uninstall_service,
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
