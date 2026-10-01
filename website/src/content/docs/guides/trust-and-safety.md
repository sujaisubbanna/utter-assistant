---
title: "Trust and safety"
description: "Utter's safety model: provenance tagging, 'untrusted content selects, never authors', argument-bearing confirmation, dangerous abilities that are off by default, and plugin permissions."
---

Utter can press keys, click, open URLs and, if you allow it, type into a terminal. It also reads
your screen. The safety model exists so that the second thing can never drive the first without
you.

The **runner is the trust boundary**. It enforces policy; plugins and their output are
**untrusted**, and so is anything read from the screen.

## Provenance tagging

Every value that can influence an action carries a provenance tag:

| Provenance | Source | Trust |
|---|---|---|
| `user` | your utterance, explicit input in the settings app | **trusted** |
| `screen` | the accessibility tree, OCR, window titles, the clipboard, web content | **untrusted** |

## Select, never author

Untrusted content **may only select among precomputed candidates**. It may **never author new
arguments**. Concretely:

- The constrained decision head (`llm.choose`) is **non-optional** on any model-driven path. The
  model picks a letter from a list Utter built; it does not write the action.
- A request whose concrete arguments derive from `screen` provenance is rejected by policy with
  error `-32006` before any plugin is called.
- Titles are truncated and sanitised. Screen text is never turned into a terminal command or an
  arbitrary `open_url` scheme.

This is what makes a malicious web page, a sneaky window title or a poisoned clipboard harmless:
at most they can nudge Utter toward one of the options it had already decided were acceptable.

## Confirmation

Confirmation is **runner-enforced and argument-bearing**. Utter shows the **concrete** URL,
command or target before acting, and re-validates the target after approval, so nothing can
swap underneath you between the prompt and the action.

- A step's `confirm` flag and the `[actions] require_confirm` substring list are honoured.
  The default list is `send`, `submit`, `delete`, `purchase`, `pay` and `confirm order`.
- Confirmation is a runner UI channel (`host.confirm`), not something a plugin declares about
  itself. A plugin's `needs_confirm` is only an untrusted hint.
- The **Safety** page of the settings app calls this *Ask before acting*, and lets you edit the
  words that always trigger it.

## Dangerous abilities are off by default

| Op | Default | Notes |
|---|---|---|
| `action.terminal` | **off** | enabling needs an explicit opt-in and the op still asks for confirmation; it is never fed model-derived strings unless you opted in |
| `action.input` (raw keyboard and mouse) | **off** | high risk; native, built-in handlers are preferred |
| `action.open_url` / `ensure_url` | on | scheme allow-list: `http`, `https`, `mailto`. No `file:`, `javascript:` or anything else |

Enable an op in the **runner** config:

```toml
[policy]
enabled_ops = ["action.terminal"]   # or "action.input"
# disabled_ops = []
```

The Safety page shows the same toggles under **Risky abilities**, behind a warning, and keeps a
banner visible while any of them is on. Under **Limits** you can restrict which terminal
commands are allowed and list phrases that are always refused.

## Socket and IPC trust

The runner listens on `$XDG_RUNTIME_DIR/utter/runner.sock`. Same-user processes must not be able
to drive your desktop by default:

- the socket directory is `0700` and the socket `0600`;
- the runner verifies the peer with `SO_PEERCRED` (same uid) and an **allow-list of client
  binaries**, resolved through `/proc/<pid>/exe`;
- alternatively a client authenticates with a token via `runner.auth`;
- `allow_same_uid = true` is a development escape hatch, not a default;
- requests are rate limited.

## Plugin sandboxing and permissions

Plugins declare permissions in their manifest (for example `network`, `microphone`). With
`[security] enforce = true` in the runner config, subprocess plugins are started under
`systemd-run --user --scope` (preferred) or `bwrap` with hardening such as `NoNewPrivileges`,
restricted address families, device allow-lists, read-only paths and seccomp or landlock where
available.

**If a permission cannot be enforced on a platform, it is labelled advisory**, never implied
safe. `assistant doctor` and the **Plugins** page print the enforced-versus-advisory status per
plugin, so you can see exactly what is actually contained.

## Secrets and logging

- Remote API keys, if you use any, go through the keyring (libsecret) or a `0600` file, and are
  redacted from logs and from `doctor` output.
- Screen, clipboard and audio content is **not** logged by default. Debug logging is opt-in and
  warned about.
- The optional on-screen display writes its state file `0700` under `$XDG_RUNTIME_DIR`. Its
  text is, by design, visible on your screen.

## Supply chain

Installing a plugin means running untrusted code at your privilege level. The intended policy is
a signature (minisign over the package plus a signed index) and pinned digests, explicit consent,
and a scoped sandbox on install. Model downloads are pinned by SHA-256 over HTTPS today. Release
assets are checksummed but **not yet signed**; see [Releasing](/reference/releasing/).

## What this means for you

- Leave terminal and raw input off unless you need them, and turn them off afterwards.
- Keep the confirmation words. Add your own for anything you consider consequential.
- Treat `allow_same_uid` and `[security] enforce = false` as developer settings.
- Read the enforced-versus-advisory column before trusting a third-party plugin with a
  permission.
- Dry run first. `UTTER_DRY_RUN` defaults to on in the `utter_py` plugin, and
  `python -m utter.daemon --text "..." --dry-run` shows a plan without executing it.
