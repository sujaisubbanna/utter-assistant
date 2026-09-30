//! Shared application state: paths, the interpreter and running child processes.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Child;
use std::sync::{Arc, Mutex};

use crate::process::Cmd;

/// Child processes we may need to stop again (log tails, mic monitor, pulls).
pub type Children = Arc<Mutex<HashMap<String, Child>>>;

pub struct AppState {
    /// The utter checkout, used as the working directory / PYTHONPATH.
    pub repo: PathBuf,
    /// Interpreter that can run `python -m assistant`.
    pub python: String,
    pub config_path: PathBuf,
    pub default_config: PathBuf,
    /// matugen palette (`~/.local/share/utter/colors.css`).
    pub theme_path: PathBuf,
    pub children: Children,
    /// Kept alive for the lifetime of the app so the file watcher stays active.
    pub watcher: Mutex<Option<notify::RecommendedWatcher>>,
}

impl AppState {
    pub fn new(
        repo: PathBuf,
        python: String,
        config_path: PathBuf,
        default_config: PathBuf,
        theme_path: PathBuf,
    ) -> Self {
        Self {
            repo,
            python,
            config_path,
            default_config,
            theme_path,
            children: Arc::new(Mutex::new(HashMap::new())),
            watcher: Mutex::new(None),
        }
    }

    /// `python -m assistant …` with the repo on PYTHONPATH.
    pub fn assistant(&self, args: &[&str]) -> Cmd {
        let repo = self.repo.to_string_lossy().into_owned();
        Cmd::new(&self.python)
            .args(["-m", "assistant"])
            .args(args.iter().copied())
            .cwd(&self.repo)
            .env("PYTHONPATH", repo)
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
