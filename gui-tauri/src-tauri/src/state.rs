//! Shared application state: paths, the interpreter and running child processes.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Child;
use std::sync::{Arc, Mutex, RwLock};

use crate::process::Cmd;

/// Child processes we may need to stop again (log tails, mic monitor, pulls).
pub type Children = Arc<Mutex<HashMap<String, Child>>>;

/// Pick the interpreter used to run `python -m assistant`.
///
/// The GUI's `python` setting is empty on a fresh install (or points at a path
/// that has since gone away). Spawning `""` then fails with `ENOENT` — the raw
/// `No such file or directory (os error 2)` users saw. Fall back to the
/// checkout's virtualenvs, then to `python3` on `$PATH`, so a missing setting
/// never produces an empty program.
pub fn resolve_python(configured: &str, repo: &Path) -> String {
    let configured = configured.trim();
    if !configured.is_empty() && Path::new(configured).exists() {
        return configured.to_string();
    }
    for candidate in [".venv-agent/bin/python", ".venv/bin/python"] {
        let path = repo.join(candidate);
        if path.exists() {
            return path.to_string_lossy().into_owned();
        }
    }
    "python3".to_string()
}

pub struct AppState {
    /// The utter checkout, used as the working directory / PYTHONPATH. On
    /// macOS the self-installer repoints it at the unpacked runtime.
    repo: RwLock<PathBuf>,
    /// Interpreter that can run `python -m assistant`.
    python: RwLock<String>,
    pub config_path: PathBuf,
    /// matugen palette (`~/.local/share/utter/colors.css`).
    pub theme_path: PathBuf,
    pub children: Children,
    /// Kept alive for the lifetime of the app so the file watcher stays active.
    pub watcher: Mutex<Option<notify::RecommendedWatcher>>,
}

impl AppState {
    pub fn new(repo: PathBuf, python: String, config_path: PathBuf, theme_path: PathBuf) -> Self {
        Self {
            repo: RwLock::new(repo),
            python: RwLock::new(python),
            config_path,
            theme_path,
            children: Arc::new(Mutex::new(HashMap::new())),
            watcher: Mutex::new(None),
        }
    }

    pub fn repo(&self) -> PathBuf {
        self.repo.read().unwrap().clone()
    }

    /// The interpreter exactly as configured (may be empty or stale).
    pub fn python(&self) -> String {
        self.python.read().unwrap().clone()
    }

    /// The interpreter actually safe to spawn: the configured one if it exists,
    /// else a checkout virtualenv, else `python3`. Never empty.
    pub fn interpreter(&self) -> String {
        resolve_python(&self.python(), &self.repo())
    }

    /// `config.default.toml` shipped next to the core.
    pub fn default_config(&self) -> PathBuf {
        self.repo().join("config.default.toml")
    }

    /// Switch to a freshly installed runtime (macOS self-install).
    pub fn set_runtime(&self, repo: PathBuf, python: String) {
        *self.repo.write().unwrap() = repo;
        *self.python.write().unwrap() = python;
    }

    /// `python -m assistant …` with the repo on PYTHONPATH.
    pub fn assistant(&self, args: &[&str]) -> Cmd {
        let repo = self.repo();
        Cmd::new(resolve_python(&self.python(), &repo))
            .args(["-m", "assistant"])
            .args(args.iter().copied())
            .cwd(&repo)
            .env("PYTHONPATH", repo.to_string_lossy().into_owned())
    }

    /// `systemctl --user …` (the Linux runner is a user service). Kept for the
    /// call sites that historically restarted the runner this way; the
    /// platform-aware path is `crate::service::control`.
    pub fn systemctl(&self, args: &[&str]) -> Cmd {
        Cmd::new("systemctl").arg("--user").args(args.iter().copied())
    }

    pub fn kill_child(&self, id: &str) {
        if let Some(mut child) = self.children.lock().unwrap().remove(id) {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A repo path that cannot contain a virtualenv.
    fn empty_repo() -> PathBuf {
        std::env::temp_dir().join("utter-resolve-python-test-no-repo")
    }

    #[test]
    fn empty_configured_python_never_resolves_to_empty() {
        let resolved = resolve_python("", &empty_repo());
        assert!(!resolved.trim().is_empty(), "an empty setting must not spawn \"\"");
        assert_eq!(resolved, "python3");
    }

    #[test]
    fn configured_python_wins_when_it_exists() {
        let me = std::env::current_exe().unwrap();
        let resolved = resolve_python(&me.to_string_lossy(), &empty_repo());
        assert_eq!(resolved, me.to_string_lossy());
    }

    #[test]
    fn stale_configured_python_falls_back() {
        let resolved = resolve_python("/does/not/exist/python", &empty_repo());
        assert_ne!(resolved, "/does/not/exist/python");
        assert!(!resolved.trim().is_empty());
    }
}
