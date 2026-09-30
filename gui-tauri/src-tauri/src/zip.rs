//! A minimal, dependency-free ZIP writer (stored, no compression).
//!
//! Enough for the support bundle: a handful of small text files that any unzip
//! tool can read. Keeps the dependency tree tiny and the output deterministic.

use std::path::Path;

fn crc32(data: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;
    for &byte in data {
        crc ^= byte as u32;
        for _ in 0..8 {
            let mask = (crc & 1).wrapping_neg();
            crc = (crc >> 1) ^ (0xEDB8_8320 & mask);
        }
    }
    !crc
}

fn push_u16(out: &mut Vec<u8>, value: u16) {
    out.extend_from_slice(&value.to_le_bytes());
}

fn push_u32(out: &mut Vec<u8>, value: u32) {
    out.extend_from_slice(&value.to_le_bytes());
}

/// Write `entries` as a ZIP archive. `name` should be a relative path.
pub fn write_zip(path: &Path, entries: &[(String, Vec<u8>)]) -> Result<(), String> {
    let mut local: Vec<u8> = Vec::new();
    let mut central: Vec<u8> = Vec::new();

    for (name, data) in entries {
        let name_bytes = name.as_bytes();
        let crc = crc32(data);
        let offset = local.len() as u32;

        // Local file header
        push_u32(&mut local, 0x0403_4B50);
        push_u16(&mut local, 20); // version needed
        push_u16(&mut local, 0x0800); // UTF-8 filename flag
        push_u16(&mut local, 0); // method: stored
        push_u16(&mut local, 0); // mod time
        push_u16(&mut local, 0x0021); // mod date: 1980-01-01
        push_u32(&mut local, crc);
        push_u32(&mut local, data.len() as u32);
        push_u32(&mut local, data.len() as u32);
        push_u16(&mut local, name_bytes.len() as u16);
        push_u16(&mut local, 0); // extra length
        local.extend_from_slice(name_bytes);
        local.extend_from_slice(data);

        // Central directory record
        push_u32(&mut central, 0x0201_4B50);
        push_u16(&mut central, 20); // version made by
        push_u16(&mut central, 20); // version needed
        push_u16(&mut central, 0x0800);
        push_u16(&mut central, 0);
        push_u16(&mut central, 0);
        push_u16(&mut central, 0x0021);
        push_u32(&mut central, crc);
        push_u32(&mut central, data.len() as u32);
        push_u32(&mut central, data.len() as u32);
        push_u16(&mut central, name_bytes.len() as u16);
        push_u16(&mut central, 0); // extra
        push_u16(&mut central, 0); // comment
        push_u16(&mut central, 0); // disk number
        push_u16(&mut central, 0); // internal attrs
        push_u32(&mut central, 0); // external attrs
        push_u32(&mut central, offset);
        central.extend_from_slice(name_bytes);
    }

    let central_offset = local.len() as u32;
    let central_size = central.len() as u32;

    let mut out = local;
    out.extend_from_slice(&central);
    // End of central directory
    push_u32(&mut out, 0x0605_4B50);
    push_u16(&mut out, 0);
    push_u16(&mut out, 0);
    push_u16(&mut out, entries.len() as u16);
    push_u16(&mut out, entries.len() as u16);
    push_u32(&mut out, central_size);
    push_u32(&mut out, central_offset);
    push_u16(&mut out, 0);

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    std::fs::write(path, out).map_err(|err| err.to_string())
}
