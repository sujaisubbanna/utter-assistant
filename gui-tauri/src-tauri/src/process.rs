//! A tiny, dependency-free subprocess builder.
//!
//! Every command is built from a **list of arguments** — never a shell string —
//! so nothing here can be turned into shell injection by a value that came out
//! of the UI or a config file.

use std::io;
use std::path::PathBuf;
use std::process::{Child, Command, Output, Stdio};

use serde::Serialize;

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
                }
            }
            Err(err) => Self {
                code: 127,
                stdout: String::new(),
                stderr: err.to_string(),
                ok: false,
            },
        }
    }
}
