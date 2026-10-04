# utter installer (M5)

Cross-distro installer for the modular assistant: system dependencies, the
**user** systemd service with a Wayland-readiness wrapper, and a reversible
uninstall. Linux only (Wayland/niri first).

## Quick start

```bash
install/install.sh                 # DRY-RUN (default): print exactly what it would do
install/install.sh --yes           # apply: install deps + enable the runner unit
install/install.sh --yes --no-deps # skip distro packages, only wire the service
install/install.sh --yes --no-service  # deps only, don't touch systemd
```

`--dry-run` is the default. Nothing is changed without `--yes`. If the installer
lacks root/passwordless sudo it **prints** the package command instead of
failing. It never silently changes groups and never removes packages.

## What it does

1. **Distro detection** — `/etc/os-release` (`ID`/`ID_LIKE`) → `pacman` / `apt` /
   `dnf` / `zypper`, falling back to `command -v`.
2. **Dependencies** — name-mapped per distro: `wtype`, `ydotool` (+`ydotoold`),
   `grim`, `wl-clipboard`, `pipewire`, `webkit2gtk`, `libsoup` (the Tauri v2 WebKit
   runtime — the old GTK4/libadwaita window is gone), optional `keyd`
   (availability varies; unmapped packages are noted, not fatal).
3. **Input injection** — checks the `input` group and `/dev/uinput`; prints the
   `usermod -aG input` + udev rule + re-login steps. It does **not** change
   groups for you.
4. **Runner service** — copies `install/utter-runner.service` to
   `~/.config/systemd/user/`, `daemon-reload`, and (with `--yes`)
   `enable --now`. Existing legacy units (`utter-bridge/vision/planner/
   audio-defaults`) are detected and left untouched.
5. **Install state** — records via `python3 -m assistant install-state record`
   (falls back to a minimal `$XDG_STATE_HOME/utter/install.json`).
6. **Verify** — runs `python3 -m assistant doctor --json` if the runner socket is
   up, else `python3 -m assistant recommend --json`.

## Uninstall

```bash
install/uninstall.sh                 # DRY-RUN: print the reverse actions
install/uninstall.sh --yes           # stop/disable units, remove recorded files
install/uninstall.sh --yes --purge   # also remove models + config
```

Package removals are **printed**, never performed automatically.

## The runner service

`install/utter-runner.service` is a **user** unit bound to the graphical
session:

- `After=`/`PartOf=graphical-session.target`, `WantedBy=default.target`
- `ExecStart=%h/.../scripts/utter-wayland-ready.sh`
- `Restart=on-failure`, `TimeoutStopSec=10`, `KillMode=control-group`
- hardening (`NoNewPrivileges=true`, `ProtectSystem=strict`, …)
- **no `PrivateTmp`** — the runner's data plane is tmp-file handles under
  `$XDG_RUNTIME_DIR`, which `PrivateTmp` would hide from clients.

Override the repo/config without editing the unit:

```bash
systemctl --user edit utter-runner.service
# [Service]
# Environment=UTTER_REPO=%h/src/utter
# Environment=UTTER_CONFIG=%h/.config/utter/runner.toml
```

## The Wayland-readiness wrapper

`scripts/utter-wayland-ready.sh` discovers `WAYLAND_DISPLAY`,
`DBUS_SESSION_BUS_ADDRESS`, `NIRI_SOCKET` and `XDG_RUNTIME_DIR` with a short
retry loop, validates the runner socket dir, then `exec`s
`python -m runner --config <config>`.

Config resolution (first match wins): `$UTTER_CONFIG` →
`<repo>/config.m3.toml` → `<repo>/runner/config.example.toml`.

Environment overrides: `UTTER_REPO`, `UTTER_PYTHON`,
`UTTER_CONFIG`, `UTTER_READY_TIMEOUT` (default 30s).

## Requirements

- `python3 -m assistant` (doctor / recommend / install-state) — optional; the
  installer falls back gracefully when it is absent.
- `systemctl --user` for the service steps.
- `UTTER_RUNNER_SOCK` / `UTTER_MODELS` are honoured if set.
