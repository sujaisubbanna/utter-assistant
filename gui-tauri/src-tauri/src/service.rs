//! Platform service control: systemd (Linux), launchd (macOS), `schtasks`
//! (Windows).
//!
//! Every platform exposes the same two operations to the UI:
//!
//! * [`show_units`] — the `systemctl show`-shaped status rows the General and
//!   Setup pages read;
//! * [`control`] — start / stop / restart / enable / disable / is-active /
//!   is-enabled.
//!
//! The [`ServiceBackend`] is resolved from `cfg!` so no caller has to branch on
//! the OS. Linux and macOS keep the exact commands they always used; Windows
//! maps each systemd unit name onto a per-user Scheduled Task of the same name.

use std::process::Command;

use serde::Serialize;

use crate::process::{Cmd, CmdResult};

/// Which service manager the host actually has.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ServiceBackend {
    Systemd,
    Launchd,
    Schtasks,
}

impl ServiceBackend {
    /// Resolve from the compilation target.
    pub fn detect() -> Self {
        if cfg!(target_os = "windows") {
            Self::Schtasks
        } else if cfg!(target_os = "macos") {
            Self::Launchd
        } else {
            Self::Systemd
        }
    }
}

#[derive(Default, Serialize)]
pub struct UnitStatus {
    pub id: String,
    pub load_state: String,
    pub active_state: String,
    pub sub_state: String,
    pub unit_file_state: String,
}

// --------------------------------------------------------------------------- //
// systemd / launchd helpers
// --------------------------------------------------------------------------- //

/// systemd unit -> launchd label. Units with no macOS counterpart map to None
/// and are reported as "not-found", so the General page needs no platform code.
fn launchd_label(unit: &str) -> Option<&'static str> {
    match unit {
        "utter-runner" => Some("com.utter.runner"),
        "utter-bridge" => Some("com.utter.assistant"),
        _ => None,
    }
}

fn current_uid() -> String {
    Command::new("id")
        .arg("-u")
        .output()
        .ok()
        .map(|out| String::from_utf8_lossy(&out.stdout).trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "501".to_string())
}

fn launchd_target(label: &str) -> String {
    format!("gui/{}/{label}", current_uid())
}

/// `launchctl print gui/<uid>/<label>` -> the UnitStatus shape systemd users expect.
fn parse_launchctl_print(unit: &str, text: &str, found: bool) -> UnitStatus {
    if !found {
        return UnitStatus {
            id: unit.to_string(),
            load_state: "not-found".to_string(),
            ..Default::default()
        };
    }
    let mut state = String::new();
    let mut pid: Option<String> = None;
    for raw in text.lines() {
        let line = raw.trim();
        if let Some(value) = line.strip_prefix("state = ") {
            state = value.trim().to_string();
        } else if let Some(value) = line.strip_prefix("pid = ") {
            pid = Some(value.trim().to_string());
        }
    }
    let running = state == "running" || pid.is_some();
    UnitStatus {
        id: unit.to_string(),
        load_state: "loaded".to_string(),
        active_state: if running { "active" } else { "inactive" }.to_string(),
        sub_state: if running { "running" } else { "dead" }.to_string(),
        // launchd agents installed by the installer run at login.
        unit_file_state: "enabled".to_string(),
    }
}

fn parse_systemctl_show(text: &str) -> Vec<UnitStatus> {
    let mut units: Vec<UnitStatus> = Vec::new();
    let mut current: Option<UnitStatus> = None;
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() {
            if let Some(unit) = current.take() {
                units.push(unit);
            }
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        if key == "Id" {
            if let Some(unit) = current.take() {
                units.push(unit);
            }
            // systemctl reports the canonical name (`foo.service`); callers use
            // the bare unit name.
            let id = value.strip_suffix(".service").unwrap_or(value);
            current = Some(UnitStatus {
                id: id.to_string(),
                ..Default::default()
            });
        } else if let Some(unit) = current.as_mut() {
            match key {
                "LoadState" => unit.load_state = value.to_string(),
                "ActiveState" => unit.active_state = value.to_string(),
                "SubState" => unit.sub_state = value.to_string(),
                "UnitFileState" => unit.unit_file_state = value.to_string(),
                _ => {}
            }
        }
    }
    if let Some(unit) = current.take() {
        units.push(unit);
    }
    units
}

// --------------------------------------------------------------------------- //
// Windows Scheduled Tasks
// --------------------------------------------------------------------------- //

/// The task name mirrors the systemd unit name, so the installer can rename the
/// service labels and the scheduler follows.
fn task_name(unit: &str) -> &str {
    unit
}

/// `schtasks /Query /TN <name> /FO CSV /NH /V`. `None` when the task does not
/// exist (or `schtasks` is unavailable).
fn schtasks_query(unit: &str) -> Option<String> {
    let out = Cmd::new("schtasks")
        .args(["/Query", "/TN", task_name(unit), "/FO", "CSV", "/NH", "/V"])
        .output()
        .ok()?;
    out.status
        .success()
        .then(|| String::from_utf8_lossy(&out.stdout).into_owned())
}

/// The `<Enabled>` flag from `schtasks /Query /XML`. `None` when unreadable.
fn schtasks_enabled(unit: &str) -> Option<bool> {
    let out = Cmd::new("schtasks")
        .args(["/Query", "/TN", task_name(unit), "/XML"])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let xml = String::from_utf8_lossy(&out.stdout).to_lowercase();
    let start = xml.find("<enabled>")? + "<enabled>".len();
    let rest = &xml[start..];
    let end = rest.find("</enabled>")?;
    Some(rest[..end].trim() == "true")
}

/// The first CSV data line split into fields, honouring `""` escapes.
fn csv_fields(line: &str) -> Vec<String> {
    let mut fields = Vec::new();
    let mut current = String::new();
    let mut in_quotes = false;
    let mut chars = line.chars().peekable();
    while let Some(ch) = chars.next() {
        match ch {
            '"' if in_quotes => {
                if chars.peek() == Some(&'"') {
                    current.push('"');
                    chars.next();
                } else {
                    in_quotes = false;
                }
            }
            '"' => in_quotes = true,
            ',' if !in_quotes => fields.push(std::mem::take(&mut current)),
            _ => current.push(ch),
        }
    }
    fields.push(current);
    fields
}

/// Unit status for one scheduled task, in the shape the UI already reads.
fn show_schtasks(unit: &str) -> UnitStatus {
    let Some(csv) = schtasks_query(unit) else {
        return UnitStatus {
            id: unit.to_string(),
            load_state: "not-found".to_string(),
            ..Default::default()
        };
    };
    // Field order is fixed regardless of UI language: with /V the fourth field
    // is the status word ("Ready", "Running", "Disabled", …). The word itself is
    // localized, so everything except a positive "running" match is treated as
    // inactive — a running task then shows as inactive on a non-English host.
    let status = csv
        .lines()
        .find(|line| !line.trim().is_empty())
        .map(|line| csv_fields(line).get(3).cloned().unwrap_or_default())
        .unwrap_or_default()
        .to_lowercase();
    let running = status.contains("running");
    let enabled = schtasks_enabled(unit)
        .unwrap_or_else(|| status.contains("ready") || status.contains("running"));
    UnitStatus {
        id: unit.to_string(),
        load_state: "loaded".to_string(),
        active_state: if running { "active" } else { "inactive" }.to_string(),
        sub_state: if running { "running" } else { "dead" }.to_string(),
        unit_file_state: if enabled { "enabled" } else { "disabled" }.to_string(),
    }
}

/// Whether the Scheduled Task backing `unit` exists.
pub fn task_installed(unit: &str) -> bool {
    schtasks_query(unit).is_some()
}

// --------------------------------------------------------------------------- //
// public surface
// --------------------------------------------------------------------------- //

/// Status rows for `units`, in the same order as the request.
pub fn show_units(backend: ServiceBackend, units: &[String]) -> Result<Vec<UnitStatus>, String> {
    match backend {
        ServiceBackend::Systemd => {
            let mut cmd = Cmd::new("systemctl").arg("--user").arg("show");
            for unit in units {
                cmd = cmd.arg(unit.clone());
            }
            cmd = cmd.arg("--property=Id,LoadState,ActiveState,SubState,UnitFileState");
            let out = cmd.output().map_err(|error| error.to_string())?;
            Ok(parse_systemctl_show(&String::from_utf8_lossy(&out.stdout)))
        }
        ServiceBackend::Launchd => Ok(units
            .iter()
            .map(|unit| match launchd_label(unit) {
                None => parse_launchctl_print(unit, "", false),
                Some(label) => {
                    let out = Cmd::new("launchctl")
                        .args(["print", &launchd_target(label)])
                        .output();
                    match out {
                        Ok(out) if out.status.success() => {
                            parse_launchctl_print(unit, &String::from_utf8_lossy(&out.stdout), true)
                        }
                        _ => parse_launchctl_print(unit, "", false),
                    }
                }
            })
            .collect()),
        ServiceBackend::Schtasks => Ok(units.iter().map(|unit| show_schtasks(unit)).collect()),
    }
}

/// Run one allowed `action` against `unit` and return the captured output.
pub fn control(backend: ServiceBackend, action: &str, unit: &str) -> Result<CmdResult, String> {
    let output = match backend {
        ServiceBackend::Systemd => {
            Cmd::new("systemctl").arg("--user").args([action, unit]).output()
        }
        ServiceBackend::Launchd => {
            let label = launchd_label(unit)
                .ok_or_else(|| format!("{unit} has no launchd agent on macOS"))?;
            let target = launchd_target(label);
            let cmd = match action {
                "start" => Cmd::new("launchctl").args(["kickstart", &target]),
                "restart" => Cmd::new("launchctl").args(["kickstart", "-k", &target]),
                "stop" => Cmd::new("launchctl").args(["kill", "SIGTERM", &target]),
                "enable" => Cmd::new("launchctl").args(["enable", &target]),
                "disable" => Cmd::new("launchctl").args(["disable", &target]),
                "is-active" | "is-enabled" => Cmd::new("launchctl").args(["print", &target]),
                other => return Err(format!("action not allowed: {other}")),
            };
            cmd.output()
        }
        ServiceBackend::Schtasks => return schtasks_control(action, unit),
    };
    Ok(CmdResult::from_output(output))
}

fn schtasks_control(action: &str, unit: &str) -> Result<CmdResult, String> {
    let task = task_name(unit);
    let cmd = match action {
        "start" => Cmd::new("schtasks").args(["/Run", "/TN", task]),
        "stop" => Cmd::new("schtasks").args(["/End", "/TN", task]),
        "restart" => {
            // Best-effort stop, then start; report the start result.
            let _ = Cmd::new("schtasks").args(["/End", "/TN", task]).output();
            Cmd::new("schtasks").args(["/Run", "/TN", task])
        }
        "enable" => Cmd::new("schtasks").args(["/Change", "/TN", task, "/ENABLE"]),
        "disable" => Cmd::new("schtasks").args(["/Change", "/TN", task, "/DISABLE"]),
        "is-active" => Cmd::new("schtasks").args(["/Query", "/TN", task]),
        // The UI compares this text against "enabled"; mirror systemd's words.
        "is-enabled" => {
            return Ok(match schtasks_query(unit) {
                None => CmdResult {
                    code: 1,
                    stdout: "not-found".to_string(),
                    stderr: String::new(),
                    ok: false,
                    kind: None,
                },
                Some(_) => CmdResult {
                    code: 0,
                    stdout: if schtasks_enabled(unit).unwrap_or(true) {
                        "enabled".to_string()
                    } else {
                        "disabled".to_string()
                    },
                    stderr: String::new(),
                    ok: true,
                    kind: None,
                },
            });
        }
        other => return Err(format!("action not allowed: {other}")),
    };
    Ok(CmdResult::from_output(cmd.output()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backend_is_resolved_from_the_platform() {
        let backend = ServiceBackend::detect();
        #[cfg(target_os = "macos")]
        assert_eq!(backend, ServiceBackend::Launchd);
        #[cfg(target_os = "windows")]
        assert_eq!(backend, ServiceBackend::Schtasks);
        #[cfg(not(any(target_os = "macos", target_os = "windows")))]
        assert_eq!(backend, ServiceBackend::Systemd);
    }

    #[test]
    fn csv_fields_handles_quotes_and_commas() {
        assert_eq!(
            csv_fields("\"a,b\",\"say \"\"hi\"\"\",c"),
            vec!["a,b".to_string(), "say \"hi\"".to_string(), "c".to_string()]
        );
    }
}
