// Prevents an extra console window on Windows in release. No effect on Linux.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // `utter --daemon` / `utter --runner`: headless modes used by the macOS
    // launchd agents. The app binary stays the parent of the python process so
    // macOS shows "utter" (with its icon) in permission prompts and the settings
    // window shares the same grants. Everything else opens the window.
    let mode = std::env::args().nth(1);
    match mode.as_deref() {
        Some("--daemon") => std::process::exit(utter_lib::supervise("daemon")),
        Some("--runner") => std::process::exit(utter_lib::supervise("runner")),
        _ => utter_lib::run(),
    }
}
