//! Comment-preserving edits to `~/.config/utter/config.toml`.
//!
//! Reads go through a real TOML parser. Writes are line-based: only the target
//! key's line changes, so comments, ordering and unknown keys survive untouched
//! — the same contract the GTK4 app had.

use std::fs;

use serde_json::Value;

use crate::state::AppState;

pub fn ensure(state: &AppState) -> std::io::Result<()> {
    let path = &state.config_path;
    if path.exists() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    if state.default_config.exists() {
        fs::copy(&state.default_config, path)?;
    } else {
        fs::write(path, "# utter configuration (created by utter-gui)\n")?;
    }
    Ok(())
}

pub fn read_text(state: &AppState) -> String {
    fs::read_to_string(&state.config_path).unwrap_or_default()
}

pub fn read_json(state: &AppState) -> Value {
    let text = read_text(state);
    match toml::from_str::<toml::Value>(&text) {
        Ok(value) => serde_json::to_value(value).unwrap_or_else(|_| Value::Object(Default::default())),
        Err(_) => Value::Object(Default::default()),
    }
}

/// Serialise the small subset of JSON the settings UI writes to TOML.
fn toml_value(value: &Value) -> Result<String, String> {
    Ok(match value {
        Value::Bool(flag) => flag.to_string(),
        Value::Number(num) => {
            if let Some(int) = num.as_i64() {
                int.to_string()
            } else if let Some(uint) = num.as_u64() {
                uint.to_string()
            } else if let Some(float) = num.as_f64() {
                format!("{float}")
            } else {
                "0".to_string()
            }
        }
        // JSON string escaping is a valid subset of TOML basic strings.
        Value::String(text) => serde_json::to_string(text).map_err(|err| err.to_string())?,
        Value::Array(items) => {
            let mut parts = Vec::with_capacity(items.len());
            for item in items {
                parts.push(toml_value(item)?);
            }
            format!("[{}]", parts.join(", "))
        }
        Value::Null => "\"\"".to_string(),
        Value::Object(_) => {
            return Err("nested tables are not supported by the line editor".to_string())
        }
    })
}

/// Split `value  # comment` into (`value`, `comment`), ignoring `#` in strings.
fn split_comment(rest: &str) -> (String, String) {
    let mut in_string = false;
    let mut escape = false;
    for (index, ch) in rest.char_indices() {
        if escape {
            escape = false;
            continue;
        }
        if ch == '\\' && in_string {
            escape = true;
            continue;
        }
        if ch == '"' {
            in_string = !in_string;
        } else if ch == '#' && !in_string {
            return (rest[..index].trim_end().to_string(), rest[index..].to_string());
        }
    }
    (rest.trim().to_string(), String::new())
}

fn parse_assignment(line: &str) -> Option<(String, String, String)> {
    let trimmed = line.trim_start();
    if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with('[') {
        return None;
    }
    let indent = line[..line.len() - trimmed.len()].to_string();
    let eq = trimmed.find('=')?;
    let key = trimmed[..eq].trim();
    if key.is_empty()
        || !key
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-')
    {
        return None;
    }
    let rest = trimmed[eq + 1..].trim_start().to_string();
    let (_value, comment) = split_comment(&rest);
    Some((indent, key.to_string(), comment))
}

fn write_atomic(state: &AppState, text: &str) -> Result<(), String> {
    let path = &state.config_path;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let file_name = path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| "config.toml".to_string());
    let tmp = path.with_file_name(format!(".{file_name}.tmp"));
    fs::write(&tmp, text).map_err(|err| err.to_string())?;
    fs::rename(&tmp, path).map_err(|err| err.to_string())?;
    Ok(())
}

/// Set `[section] key = value`, preserving the rest of the file byte-for-byte.
pub fn set_key(state: &AppState, section: &str, key: &str, value: &Value) -> Result<(), String> {
    ensure(state).map_err(|err| err.to_string())?;
    let mut text = read_text(state);
    if !text.is_empty() && !text.ends_with('\n') {
        text.push('\n');
    }
    let serialised = toml_value(value)?;
    let mut lines: Vec<String> = text.split('\n').map(|line| line.to_string()).collect();
    let header = format!("[{section}]");

    let mut section_start: Option<usize> = None;
    for (index, line) in lines.iter().enumerate() {
        let stripped = line.split('#').next().unwrap_or("").trim();
        if stripped == header {
            section_start = Some(index);
            break;
        }
    }

    let Some(start) = section_start else {
        // Brand new section: drop trailing blanks, then append.
        while lines.last().map(|line| line.trim().is_empty()).unwrap_or(false) {
            lines.pop();
        }
        lines.push(String::new());
        lines.push(header);
        lines.push(format!("{key} = {serialised}"));
        return write_atomic(state, &lines.join("\n"));
    };

    let mut section_end = lines.len();
    for index in (start + 1)..lines.len() {
        if lines[index].trim_start().starts_with('[') {
            section_end = index;
            break;
        }
    }

    for index in (start + 1)..section_end {
        if let Some((indent, existing_key, comment)) = parse_assignment(&lines[index]) {
            if existing_key == key {
                let suffix = if comment.trim().is_empty() {
                    String::new()
                } else {
                    format!("  {}", comment.trim_start())
                };
                lines[index] = format!("{indent}{key} = {serialised}{suffix}");
                return write_atomic(state, &lines.join("\n"));
            }
        }
    }

    let mut insert_at = section_end;
    while insert_at > start + 1 && lines[insert_at - 1].trim().is_empty() {
        insert_at -= 1;
    }
    lines.insert(insert_at, format!("{key} = {serialised}"));
    write_atomic(state, &lines.join("\n"))
}

pub fn set_many(state: &AppState, section: &str, values: &Value) -> Result<(), String> {
    let object = values
        .as_object()
        .ok_or_else(|| "values must be a JSON object".to_string())?;
    for (key, value) in object {
        set_key(state, section, key, value)?;
    }
    Ok(())
}
