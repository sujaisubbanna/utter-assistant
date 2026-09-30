//! fake_rs — a minimal fake utter plugin in Rust.
//!
//! Implements the frozen handshake plus `action.capabilities` and
//! `action.invoke` for one op (`ensure_url`). Its framing is hand-rolled from
//! the spec (`Content-Length: <n>\r\n\r\n<json>`); only JSON *parsing* uses
//! serde_json. Terminates on stdin EOF.
//!
//! Determinism contract (asserted by tests/conformance/run.py):
//!   action.capabilities -> ops includes "ensure_url"
//!   action.invoke {op:"ensure_url", args:{url:"https://www.youtube.com"}}
//!       -> { ok: true, op: "ensure_url", detail: "opened https://www.youtube.com" }

use std::io::{self, BufRead, Write};

use serde_json::{json, Value};

const PROTOCOL: &str = "1.0";
const ABI: i64 = 1;
const PLUGIN_NAME: &str = "fake_rs";
const PLUGIN_VERSION: &str = "0.1.0";
const PLUGIN_KIND: &str = "action";

const PROVIDES: &[&str] = &["action.open_url@1", "experimental/fake_rs@1"];
const REQUIRES: &[&str] = &["context.live@1"];
const PERMISSIONS: &[&str] = &["network"];

fn main() {
    let stdin = io::stdin();
    let mut reader = stdin.lock();
    let stdout = io::stdout();
    let mut writer = stdout.lock();

    loop {
        match read_frame(&mut reader) {
            Ok(Some(msg)) => {
                if let Some(reply) = handle(&msg) {
                    if write_frame(&mut writer, &reply).is_err() {
                        break;
                    }
                }
            }
            Ok(None) => break, // EOF -> terminate
            Err(_) => break,   // malformed frame -> terminate
        }
    }
}

/// Read one Content-Length framed message. `Ok(None)` means clean EOF.
fn read_frame<R: BufRead>(reader: &mut R) -> io::Result<Option<Value>> {
    let mut content_length: Option<usize> = None;
    let mut line = String::new();
    loop {
        line.clear();
        let n = reader.read_line(&mut line)?;
        if n == 0 {
            return Ok(None); // EOF
        }
        let trimmed = line.trim_end_matches(['\r', '\n']);
        if trimmed.is_empty() {
            break; // end of headers
        }
        if let Some((key, value)) = trimmed.split_once(':') {
            if key.trim().eq_ignore_ascii_case("content-length") {
                content_length = value.trim().parse::<usize>().ok();
            }
        }
    }
    let len = match content_length {
        Some(l) => l,
        None => return Err(io::Error::new(io::ErrorKind::InvalidData, "no Content-Length")),
    };
    let mut body = vec![0u8; len];
    reader.read_exact(&mut body)?;
    let value: Value = serde_json::from_slice(&body)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    Ok(Some(value))
}

fn write_frame<W: Write>(writer: &mut W, value: &Value) -> io::Result<()> {
    let body = serde_json::to_vec(value)?;
    write!(writer, "Content-Length: {}\r\n\r\n", body.len())?;
    writer.write_all(&body)?;
    writer.flush()
}

fn handle(msg: &Value) -> Option<Value> {
    let method = msg.get("method").and_then(Value::as_str).unwrap_or("");
    let id = msg.get("id").cloned();

    // Notifications (no id) get no reply.
    if id.is_none() {
        return None;
    }
    let id = id.unwrap();

    let result = match method {
        "protocol.hello" => json!({
            "protocol": PROTOCOL,
            "abi": ABI,
            "plugin": {"name": PLUGIN_NAME, "version": PLUGIN_VERSION, "kind": PLUGIN_KIND},
            "transport": "stdio",
            "provides": PROVIDES,
            "requires": REQUIRES,
            "permissions": PERMISSIONS,
        }),
        "plugin.describe" => json!({
            "methods": ["protocol.hello", "plugin.describe", "plugin.health",
                        "action.capabilities", "action.invoke"],
            "streams": [],
        }),
        "plugin.health" => json!({"status": "ok", "detail": "fake_rs ready"}),
        "action.capabilities" => json!({
            "ops": [
                {"op": "ensure_url", "side_effect": "open_url", "needs_confirm": false}
            ]
        }),
        "action.invoke" => {
            let params = msg.get("params").cloned().unwrap_or_else(|| json!({}));
            let op = params.get("op").and_then(Value::as_str).unwrap_or("");
            if op == "ensure_url" {
                let url = params
                    .get("args")
                    .and_then(|a| a.get("url"))
                    .and_then(Value::as_str)
                    .unwrap_or("");
                json!({"ok": true, "op": "ensure_url", "detail": format!("opened {}", url)})
            } else {
                return Some(error_reply(id, -32000, &format!("unknown op: {}", op)));
            }
        }
        _ => return Some(error_reply(id, -32601, &format!("method not found: {}", method))),
    };

    Some(json!({"jsonrpc": "2.0", "id": id, "result": result}))
}

fn error_reply(id: Value, code: i64, message: &str) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})
}
