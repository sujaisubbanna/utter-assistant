//! Shared application state: paths, the interpreter and running child processes.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Child;
use std::sync::{Arc, Mutex, RwLock};

use crate::process::Cmd;

/// Child processes we may need to stop again (log tails, mic monitor, pulls).
pub type Children = Arc<Mutex<HashMap<String, Child>>>;

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

    pub fn python(&self) -> String {
        self.python.read().unwrap().clone()
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
        Cmd::new(self.python())
            .args(["-m", "assistant"])
            .args(args.iter().copied())
            .cwd(&repo)
            .env("PYTHONPATH", repo.to_string_lossy().into_owned())
    }

    /// `systemctl --user …` (the runner is a user service).
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
