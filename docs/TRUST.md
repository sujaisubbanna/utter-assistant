# Trust model (M0)

The runner is the **trust boundary**. It enforces policy; plugins and their output are
**untrusted**.

## 1. Provenance tagging
Every value that can influence an action carries provenance:
- `user` — the user's utterance / explicit UI input. **Trusted.**
- `screen` — a11y tree, OCR, window titles, clipboard, web content. **Untrusted.**

## 2. Select, never author
Untrusted content **may only select among precomputed candidates**. It may **never author
new `args`**. Concretely: the constrained decision head (`llm.choose`) is **non-optional**
on any LLM-driven path; a request whose concrete arguments derive from `screen` provenance
is rejected by policy with `-32006`. Titles are truncated/sanitized; screen text is never
turned into a `terminal` command or an arbitrary `open_url` scheme.

## 3. Confirmation
Runner-enforced and **argument-bearing**: it displays the **concrete** URL/command/target,
then re-validates the target after approval (TOCTOU). `Step.confirm`/`require_confirm` are
real. Confirmation is a runner UI channel (`host.confirm`), not a plugin self-declaration
(plugin-declared `needs_confirm` is an untrusted hint).

## 4. Dangerous capabilities (off by default)
- `action.terminal` — **off by default**; enabling requires explicit confirmation; never fed
  LLM-derived strings unless the user opted in.
- `action.input` — high risk; native/builtin preferred.
- `action.open_url` — scheme allow-list (http/https/mailto); no `file:`, `javascript:`, etc.

## 5. IPC trust
Runner socket dir `0700`, socket `0600`, verify **`SO_PEERCRED`** (same uid), allow-list of
client binaries, rate limiting. Same-uid processes must not be able to drive actions by
default; privileged control requires an explicit token/allow-list entry.

## 6. Plugin sandboxing
Subprocess plugins run under systemd-run/bubblewrap hardening where possible
(`NoNewPrivileges`, `RestrictAddressFamilies`, `DeviceAllow`, `ReadOnlyPaths`, seccomp/landlock).
**If a permission cannot be enforced on a platform, it is labelled advisory** — never
implied safe. `doctor` prints the enforced-vs-advisory status per plugin.

## 7. Secrets & logging
Remote API keys via keyring/libsecret or a 0600 file; redacted from logs and `doctor`.
Screen/clipboard/audio content is **not** logged by default; debug logging is opt-in and
warned about.

## 8. Supply chain
Installing a plugin = running untrusted code at user privilege: require a signature
(minisign over the package + signed index) and pinned digests; model downloads pinned by
sha256 over https; explicit consent and a scoped sandbox on install.
