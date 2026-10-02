---
title: "Releasing"
description: "How releases are built and published, the asset naming convention, and how the hosted installer and this documentation site are deployed."
---

Releases are produced by GitHub Actions. A release publishes the settings app bundles (AppImage,
deb, rpm) plus the Python core tarball, all checksummed in `sha256sums.txt`.

## Cut a release

```bash
# 1. make sure main is green and the version is what you want
git checkout main && git pull

# 2. tag and push (the tag drives the version)
git tag v0.1.0
git push origin v0.1.0
```

Pushing a `v*` tag triggers the `release` workflow, which:

1. resolves the version from the tag (`v0.1.0` becomes `0.1.0`);
2. installs the Tauri v2 build dependencies on `ubuntu-24.04` (it has `webkit2gtk-4.1`; 22.04
   does not, and Tauri v2 requires 4.1);
3. builds the Python core tarball first;
4. builds the settings app from `gui-tauri/` with bundle targets `appimage,deb,rpm`;
5. renames the bundles to stable names and writes `sha256sums.txt`;
6. creates or updates the GitHub Release and attaches every asset.

To run it manually: Actions → **release** → *Run workflow*. An optional `version` input
overrides the tag; left blank, the workflow uses a `0.0.0-dev.<run>` version, useful for
testing the pipeline.

## Asset names

| Asset | Name |
|---|---|
| AppImage | `utter-gui_<ver>_amd64.AppImage` |
| Debian | `utter-gui_<ver>_amd64.deb` |
| RPM | `utter-gui-<ver>-1.x86_64.rpm` |
| Core tarball | `utter-core-<ver>.tar.gz` |
| Checksums | `sha256sums.txt` |

`<ver>` is the tag without the leading `v`. The bootstrap installer resolves these names from
the release tag, so the installer flags can change without touching the release workflow.

## What gets published

- **GUI**: the settings app for x86_64 Linux (AppImage, deb, rpm).
- **Core**: the Python runner, `assistant` CLI, protocol contracts, plugins, systemd unit and
  Wayland wrapper, the optional Noctalia widget package, and docs. This is what the installer
  extracts to `$PREFIX/share/utter`.
- **Checksums**: `sha256sums.txt` covering every asset.

## The hosted installer and this site

The site is a static Astro build deployed to **Vercel** at
`https://utter.sujaisubbanna.com/`, together with the bootstrap installer. The
installer keeps its stable address, so the one-liner never changes:

```bash
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash
```

Vercel is configured by the root `vercel.json`: `cd website && corepack
pnpm@10.0.0 build`, output `website/dist`. The build copies `install.sh` into
the build output so it is served from the site root; the old GitHub Pages
`/utter-assistant/*` paths redirect to the new root. Deployments happen on push
to `main`, or with `vercel --prod` by hand. (GitHub Pages is retired.)

To work on the site locally:

```bash
cd website
pnpm install
pnpm dev        # live reload
pnpm build      # production build into website/dist
pnpm preview    # serve the production build
```

## Known gaps

- **aarch64 is deferred.** GitHub's arm64 runners do not yet provide the webkit2gtk-4.1 and
  Tauri bundling toolchain.
- **No code signing yet.** Assets are checksummed but not signed; supply-chain signing
  (minisign over the tarball plus a signed index) is planned.
- **`actionlint` is not run in CI.** Workflow YAML is validated by parsing locally.
