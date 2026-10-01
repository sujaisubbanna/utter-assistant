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

/// How each agent is launched: through this app binary, which supervises the
/// python child. launchd then attributes the python's permission requests to
/// utter.app (the "responsible process"), so prompts show "utter" and the
/// settings window, the daemon and the prompts share one grant. Pointing
/// launchd straight at python would make the grants belong to "Python 3.12".
const AGENTS: &[(&str, &str, &str)] = &[
    (RUNNER_LABEL, "--runner", "runner.log"),
    (ASSISTANT_LABEL, "--daemon", "utter.log"),
];

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

fn launcher() -> Option<PathBuf> {
    std::env::current_exe().ok()
}

/// True when both agents exist *and* point at this app binary (older installs
/// that launched python directly count as outdated and get rewritten).
pub fn agents_installed() -> bool {
    let dir = agents_dir();
    let Some(launcher) = launcher() else {
        return false;
    };
    let launcher = launcher.to_string_lossy().into_owned();
    AGENTS.iter().all(|(label, _, _)| {
        fs::read_to_string(dir.join(format!("{label}.plist")))
            .map(|text| text.contains(&launcher))
            .unwrap_or(false)
    })
}

fn xml_escape(text: &str) -> String {
    text.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
}

/// A launchd user-agent plist: `<launcher> <flag>` at login, kept alive, logging
/// to ~/Library/Logs/utter. The core path travels in the environment so the
/// supervisor does not depend on the app's current directory.
fn plist_xml(label: &str, launcher: &Path, flag: &str, core: &Path, log: &Path) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!-- Written by utter.app (Set up page). Re-created by "Reinstall" there. -->
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{launcher}</string>
    <string>{flag}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>{core}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>UTTER_REPO</key>
    <string>{core}</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>5</integer>
  <key>ProcessType</key>
  <string>Interactive</string>
  <key>StandardOutPath</key>
  <string>{log}</string>
  <key>StandardErrorPath</key>
  <string>{log}</string>
</dict>
</plist>
"#,
        label = xml_escape(label),
        launcher = xml_escape(&launcher.to_string_lossy()),
        flag = xml_escape(flag),
        core = xml_escape(&core.to_string_lossy()),
        log = xml_escape(&log.to_string_lossy()),
    )
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

/// Write + bootstrap the two launchd agents, launched through this app binary.
fn install_agents(app: &AppHandle, core: &Path, _python: &str) -> Result<(), String> {
    emit_progress(app, "agents", "Installing the background agents…");
    let launcher = launcher().ok_or_else(|| "cannot determine the app's own path".to_string())?;
    let logs = log_dir();
    let dir = agents_dir();
    fs::create_dir_all(&logs).map_err(|error| error.to_string())?;
    fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let domain = format!("gui/{}", uid());
    for (label, flag, log_name) in AGENTS {
        let path = dir.join(format!("{label}.plist"));
        fs::write(&path, plist_xml(label, &launcher, flag, core, &logs.join(log_name)))
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

// --------------------------------------------------------------------------- //
// `utter --daemon` / `utter --runner`: supervise the python child
// --------------------------------------------------------------------------- //
#[cfg(unix)]
mod signals {
    use std::sync::atomic::{AtomicBool, Ordering};

    static STOP: AtomicBool = AtomicBool::new(false);

    extern "C" fn on_signal(_signum: libc::c_int) {
        STOP.store(true, Ordering::SeqCst);
    }

    pub fn install() {
        // SAFETY: installing a plain async-signal-safe handler that only flips an atomic.
        unsafe {
            libc::signal(libc::SIGTERM, on_signal as extern "C" fn(libc::c_int) as libc::sighandler_t);
            libc::signal(libc::SIGINT, on_signal as extern "C" fn(libc::c_int) as libc::sighandler_t);
            libc::signal(libc::SIGHUP, on_signal as extern "C" fn(libc::c_int) as libc::sighandler_t);
        }
    }

    pub fn stopping() -> bool {
        STOP.load(Ordering::SeqCst)
    }

    pub fn terminate(pid: u32) {
        // SAFETY: plain kill(2) on our own child.
        unsafe {
            libc::kill(pid as libc::pid_t, libc::SIGTERM);
        }
    }
}

/// Run the python module for `mode` as a child, forward SIGTERM/SIGINT to it,
/// and return its exit code. The app binary stays alive as the parent so macOS
/// treats utter.app as the process responsible for the python's permissions.
pub fn supervise_python(mode: &str, repo: &Path, python: &str) -> i32 {
    let args: Vec<String> = match mode {
        "daemon" => vec!["-m".into(), "utter.daemon".into()],
        "runner" => {
            let config = std::env::var("UTTER_CONFIG")
                .ok()
                .filter(|value| !value.is_empty())
                .or_else(|| {
                    // Prefer the production M3 config (real `plugins/utter_py`),
                    // not the echo test plugins in runner/config.example.toml.
                    // Fall back to the example only if the M3 config is absent,
                    // matching scripts/utter-wayland-ready.sh.
                    let m3 = repo.join("config.m3.toml");
                    if m3.is_file() {
                        return Some(m3.to_string_lossy().into_owned());
                    }
                    let example = repo.join("runner/config.example.toml");
                    if example.is_file() {
                        eprintln!(
                            "utter: {} not found; falling back to example runner config",
                            m3.display()
                        );
                        return Some(example.to_string_lossy().into_owned());
                    }
                    None
                })
                .unwrap_or_else(|| repo.join("config.m3.toml").to_string_lossy().into_owned());
            vec!["-m".into(), "runner".into(), "--config".into(), config]
        }
        other => {
            eprintln!("utter: unknown supervise mode {other:?}");
            return 2;
        }
    };
    eprintln!("utter: supervising {python} {} (cwd {})", args.join(" "), repo.display());
    #[cfg(unix)]
    signals::install();
    let mut child = match Command::new(python)
        .args(&args)
        .current_dir(repo)
        .env("PYTHONPATH", repo)
        .env("PYTHONUNBUFFERED", "1")
        .env("UTTER_PERMISSIONS_PROCESS", "utter.app")
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .spawn()
    {
        Ok(child) => child,
        Err(error) => {
            eprintln!("utter: could not start {python}: {error}");
            return 1;
        }
    };
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return status.code().unwrap_or(1),
            Ok(None) => {}
            Err(error) => {
                eprintln!("utter: wait failed: {error}");
                return 1;
            }
        }
        #[cfg(unix)]
        if signals::stopping() {
            signals::terminate(child.id());
            let _ = child.wait();
            return 0;
        }
        std::thread::sleep(std::time::Duration::from_millis(200));
    }
}
