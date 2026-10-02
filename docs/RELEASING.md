# Releasing utter

Releases are produced by GitHub Actions (`.github/workflows/release.yml`). A
release publishes the Tauri GUI bundles (AppImage, deb, rpm) plus the Python
core tarball, all checksummed in `sha256sums.txt`.

## Cut a release

```bash
# 1. make sure main is green and the version is what you want
git checkout main && git pull

# 2. tag and push (the tag drives the version)
git tag v0.1.1
git push origin v0.1.1
```

Pushing a `v*` tag triggers the `release` workflow, which:

1. resolves the version from the tag (`v0.1.1` → `0.1.0`);
2. installs the Tauri v2 build deps on **`ubuntu-24.04`** (it has
   `webkit2gtk-4.1`; 22.04 does **not** and Tauri v2 requires 4.1);
3. builds the Python core tarball first (`scripts/build-core-tarball.sh`);
4. builds the GUI from `gui-tauri/` with bundle targets `appimage,deb,rpm`;
5. renames the bundles to stable names and writes `sha256sums.txt`;
6. creates/updates the GitHub Release and attaches every asset.

## Run it manually

Actions → **release** → *Run workflow*. Optionally set a `version` input; if
left blank the workflow uses a `0.0.0-dev.<run>` version (useful for testing the
pipeline without tagging).

## Artifact naming convention

| Asset | Name |
|---|---|
| AppImage | `utter-gui_<ver>_amd64.AppImage` |
| Debian | `utter-gui_<ver>_amd64.deb` |
| RPM | `utter-gui-<ver>-1.x86_64.rpm` |
| Core tarball | `utter-core-<ver>.tar.gz` |
| Checksums | `sha256sums.txt` |
| macOS disk image (arm64, unsigned) | `utter-gui_<ver>_aarch64.dmg` |
| macOS app bundle (arm64, unsigned) | `utter-gui_<ver>_aarch64.app.tar.gz` |
| macOS core tarball | `utter-core-<ver>-macos.tar.gz` |
| macOS checksums | `sha256sums-macos.txt` |

The macOS assets come from the separate `build-macos` job (`macos-14`, Apple
Silicon). They are **not code-signed or notarised**; see `docs/MACOS.md`.

`<ver>` is the tag without the leading `v` (e.g. `0.1.0`). The bootstrap
installer (`install.sh`) resolves these names from the release tag.

## What gets published

- **GUI**: the Tauri app for x86_64 Linux (AppImage, deb, rpm).
- **Core**: `utter-core-<ver>.tar.gz` — the Python runner, `assistant` CLI,
  protocol contracts, plugins, systemd unit + Wayland wrapper, the optional
  `widgets/noctalia/` package, and docs. This is what `install.sh` extracts to
  `$PREFIX/share/utter`.
- **Checksums**: `sha256sums.txt` covering every asset.

## Hosted installer (Vercel)

The documentation site is a static Astro build deployed to **Vercel** at
`https://utter.sujaisubbanna.com/`, together with the bootstrap installer. The
root `vercel.json` runs `cd website && corepack pnpm@10.0.0 build` and serves
`website/dist`; a build step copies `install.sh` into that output so it is
served from the site root. GitHub Pages is retired. After deploying:

```bash
# interactive wizard in a terminal
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash

# non-interactive: accept all recommended defaults
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --yes
```

The installer is a step-by-step wizard that offers each component (system deps,
core, systemd units, models, GUI, STT, perception, optional Noctalia widget,
config). Piped with no `--yes` it prints the plan and exits without changing
anything. The release workflow is unchanged: it builds the same stable asset
names (`--appimage`/`--package` and the core tarball), so no workflow edits are
needed when the installer flags change. See
[`INSTALL-FROM-WEB.md`](INSTALL-FROM-WEB.md) for the full flag/env matrix.

## Notes / gaps

- **aarch64 is deferred.** GitHub's arm64 runners do not yet provide the
  webkit2gtk-4.1 / Tauri bundling toolchain. Add a `build-aarch64` job on
  `ubuntu-24.04-arm` when that changes.
- **`gui-tauri/` is owned by another lane.** The workflow builds it if present
  and emits a warning (skipping GUI bundles) if it is absent, so the core
  tarball can still be released.
- **No code signing yet.** Assets are checksummed but not signed; supply-chain
  signing (minisign over the tarball + a signed index) is planned.
- **`actionlint` is not run in CI.** The workflow YAML is validated by parsing
  locally; consider adding `actionlint` as a CI step.
