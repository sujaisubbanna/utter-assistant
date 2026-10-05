//! A tiny, dependency-free subprocess builder.
//!
//! Every command is built from a **list of arguments** — never a shell string —
//! so nothing here can be turned into shell injection by a value that came out
//! of the UI or a config file.

use std::io;
use std::path::PathBuf;
use std::process::{Child, Command, Output, Stdio};

use serde::Serialize;

/// Stable marker for a command that could not spawn because its program is
/// missing (`ENOENT`), which in this app almost always means the Python
/// interpreter — empty or uninstalled. The frontend branches on this instead of
/// rendering the raw `No such file or directory (os error 2)`.
pub const ENGINE_MISSING: &str = "engine_missing";

/// Map a spawn failure to a frontend-safe message. A missing program becomes
/// [`ENGINE_MISSING`]; anything else keeps the OS text.
pub fn io_message(error: &io::Error) -> String {
    if error.kind() == io::ErrorKind::NotFound {
        ENGINE_MISSING.to_string()
    } else {
        error.to_string()
    }
}

#[derive(Clone, Debug)]
pub struct Cmd {
    pub program: String,
    pub args: Vec<String>,
    pub cwd: Option<PathBuf>,
    pub env: Vec<(String, String)>,
}

impl Cmd {
    pub fn new(program: impl Into<String>) -> Self {
        Self {
            program: program.into(),
            args: Vec::new(),
            cwd: None,
            env: Vec::new(),
        }
    }

    pub fn arg(mut self, value: impl Into<String>) -> Self {
        self.args.push(value.into());
        self
    }

    pub fn args<I, S>(mut self, values: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        for value in values {
            self.args.push(value.into());
        }
        self
    }

    pub fn cwd(mut self, dir: impl Into<PathBuf>) -> Self {
        self.cwd = Some(dir.into());
        self
    }

    pub fn env(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.env.push((key.into(), value.into()));
        self
    }

    fn command(&self) -> Command {
        let mut command = Command::new(&self.program);
        command.args(&self.args);
        if let Some(dir) = &self.cwd {
            command.current_dir(dir);
        }
        // The AppImage's linuxdeploy AppRun exports PYTHONHOME / PYTHONPATH /
        // LD_LIBRARY_PATH pointing at its read-only mount. Inheriting those
        // breaks the venv Python we spawn ("Failed to import encodings") and can
        // shadow system libraries for any child. Drop them; an explicit env()
        // below (e.g. PYTHONPATH=<repo>) still wins.
        command.env_remove("PYTHONHOME");
        command.env_remove("PYTHONPATH");
        command.env_remove("LD_LIBRARY_PATH");
        for (key, value) in &self.env {
            command.env(key, value);
        }
        command
    }

    pub fn output(&self) -> io::Result<Output> {
        self.command().stdin(Stdio::null()).output()
    }

    pub fn spawn_piped(&self) -> io::Result<Child> {
        self.command()
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
    }

    /// For processes whose stderr is noise (e.g. `pw-record`).
    pub fn spawn_stdout_only(&self) -> io::Result<Child> {
        self.command()
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
    }
}

#[derive(Debug, Serialize)]
pub struct CmdResult {
    pub code: i32,
    pub stdout: String,
    pub stderr: String,
    pub ok: bool,
    /// Set only for a recognizable failure (`"engine_missing"` today), so the
    /// UI can branch without matching on OS text.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kind: Option<String>,
}

impl CmdResult {
    pub fn from_output(result: io::Result<Output>) -> Self {
        match result {
            Ok(out) => {
                let code = out.status.code().unwrap_or(-1);
                Self {
                    code,
                    stdout: String::from_utf8_lossy(&out.stdout).into_owned(),
                    stderr: String::from_utf8_lossy(&out.stderr).into_owned(),
                    ok: out.status.success(),
                    kind: None,
                }
            }
            Err(err) => {
                let missing = err.kind() == io::ErrorKind::NotFound;
                Self {
                    code: 127,
                    stdout: String::new(),
                    stderr: io_message(&err),
                    ok: false,
                    kind: missing.then(|| ENGINE_MISSING.to_string()),
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_program_maps_to_the_engine_missing_sentinel() {
        let err = io::Error::new(io::ErrorKind::NotFound, "No such file or directory (os error 2)");
        assert_eq!(io_message(&err), ENGINE_MISSING);
    }

    #[test]
    fn other_spawn_errors_keep_their_text() {
        let err = io::Error::new(io::ErrorKind::PermissionDenied, "denied");
        assert_eq!(io_message(&err), "denied");
    }

    #[test]
    fn cmd_result_marks_and_labels_a_missing_spawn() {
        let result = CmdResult::from_output(Err(io::Error::new(
            io::ErrorKind::NotFound,
            "No such file or directory (os error 2)",
        )));
        assert_eq!(result.code, 127);
        assert!(!result.ok);
        // The raw OS string is gone, replaced by the stable sentinel.
        assert_eq!(result.stderr, ENGINE_MISSING);
        assert_eq!(result.kind.as_deref(), Some(ENGINE_MISSING));
    }
}
