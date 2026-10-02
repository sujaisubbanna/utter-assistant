# Contributing to Utter

Thanks for taking the time to help! Utter is an open project and contributions of any size and skill
level are welcome — code, documentation, design, translations, testing and bug reports all count.
By taking part you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md). Unless you say
otherwise, anything you contribute is offered under the project's [Apache-2.0](LICENSE) license.

## Contents

- [Ways to contribute](#ways-to-contribute)
- [Before you start](#before-you-start)
- [Reporting a bug](#reporting-a-bug)
- [Suggesting a feature](#suggesting-a-feature)
- [Your first code contribution](#your-first-code-contribution)
- [Development setup](#development-setup)
- [Running tests](#running-tests)
- [Pull requests](#pull-requests)
- [Review process: what happens next](#review-process-what-happens-next)
- [Code style](#code-style)
- [AI-assisted contributions](#ai-assisted-contributions)
- [Community & questions](#community--questions)

## Ways to contribute

- **Code** — fix a bug, add an action or app profile, improve the runner or the settings app.
- **Documentation** — the in-repo `docs/` and the site at [utter.sujaisubbanna.com](https://utter.sujaisubbanna.com/).
- **Translations** — the settings app and installer ship many locales; see [docs/TRANSLATING.md](docs/TRANSLATING.md).
- **Testing & triage** — reproduce bugs, confirm fixes, label and narrow issues, try edge cases.
- **Design** — UI, icons, animations and docs visuals make Utter approachable.

## Before you start

- **Search first.** Look through existing [issues](https://github.com/sujaisubbanna/utter-assistant/issues)
  and [pull requests](https://github.com/sujaisubbanna/utter-assistant/pulls) before opening a new one.
- **Read the docs.** [docs/INSTALL.md](docs/INSTALL.md), [docs/CLI.md](docs/CLI.md),
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [AGENTS.md](AGENTS.md) answer most questions.
- **Questions go to [Discussions](https://github.com/sujaisubbanna/utter-assistant/discussions),
  not the issue tracker.**
- **Security issues go to [SECURITY.md](SECURITY.md) — never a public issue.**
- Use **👍 reactions** on an existing issue to show support instead of posting a new "+1" comment.

## Reporting a bug

Open a [bug report](https://github.com/sujaisubbanna/utter-assistant/issues/new?template=bug_report.yml).
**One bug per issue**, and please include:

- **Version and how you installed it** (installer, source checkout, release bundle).
- **OS and version** (e.g. Linux Wayland / niri, or macOS 15 on Apple Silicon).
- **Numbered reproduction steps** — the smallest sequence that shows the problem.
- **Expected vs actual** behaviour.
- **Logs and errors as text, not screenshots of text.** Paste them in a code block.
- **Screenshots or an animation** for anything visual or UI-related.
- **Whether it reproduces on the [latest release](https://github.com/sujaisubbanna/utter-assistant/releases/latest).**

Issues without a clear reproduction may be labeled and closed after a period of inactivity. If you
solve your own issue, please close it yourself and leave a note on what worked — it helps the next person.

## Suggesting a feature

Lead with the **motivation**: what problem are you trying to solve, who does it affect, and what
alternatives have you already considered? For anything large, **start a
[Discussion](https://github.com/sujaisubbanna/utter-assistant/discussions) first** and wait for a
maintainer to approve the direction before writing code — it saves you from building something that
does not fit the roadmap. Use the
[feature request form](https://github.com/sujaisubbanna/utter-assistant/issues/new?template=feature_request.yml)
for smaller, well-scoped proposals.

## Your first code contribution

Issues labeled **`good first issue`** and **`help wanted`** are a good starting point:

- [good first issues](https://github.com/sujaisubbanna/utter-assistant/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)
- [help wanted](https://github.com/sujaisubbanna/utter-assistant/issues?q=is%3Aopen+is%3Aissue+label%3A%22help+wanted%22)

Comment on the issue to say you are taking it, and ask if anything is unclear — we are happy to help.

## Development setup

A quick taste of the repo; full instructions live in the docs, so we do not duplicate them here.

```bash
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant
./install.sh --dry-run   # print the plan, change nothing
```

Then read:

- [docs/INSTALL.md](docs/INSTALL.md) — installer, services and the model store.
- [docs/INSTALL-AGENT.md](docs/INSTALL-AGENT.md) — the agent-driven install runbook.
- [AGENTS.md](AGENTS.md) — repo map, contracts and invariants.
- The docs site: [utter.sujaisubbanna.com](https://utter.sujaisubbanna.com/).

## Running tests

Run the suite before declaring anything done:

```bash
scripts/verify.sh
```

The settings app typechecks from `gui-tauri/`:

```bash
pnpm exec tsc --noEmit
```

> There are **2 known pre-existing errors** in `Diagnostics.tsx` — these are not caused by your
> change, and we do not claim a fully clean typecheck today. Please do not add new ones.

CI runs the same protocol and assistant suites via
[`.github/workflows/verify.yml`](.github/workflows/verify.yml).

## Pull requests

- **Keep it small and focused** — one concern per pull request.
- **Link the issue** it closes (for example `Closes #123`).
- **Add or update tests and docs** for the behaviour you change.
- Use **Conventional-Commit-style titles** — `fix:`, `feat:`, `docs:`, `chore:` — and fill in the
  [pull request template](.github/PULL_REQUEST_TEMPLATE.md).
- **Allow maintainer edits** so a reviewer can push small fixes.
- **Draft pull requests are welcome** for early feedback.

## Review process: what happens next

CI must pass, then a maintainer reviews the change. Push fixes as **new commits** rather than
force-pushing — it keeps the history reviewable. Pull requests are **squashed on merge**. Review is
best-effort by a small team, so please be patient; a polite bump after a quiet period is fine.
Please do not ping maintainers privately about a review.

## Code style

Follow the surrounding code and keep changes minimal. Run the repo's formatters and linters through
`scripts/verify.sh`. Prefer small, readable changes over broad rewrites, and match the language and
patterns already in the file you are editing.

## AI-assisted contributions

AI tools are welcome as an aid — but you are responsible for the result. You must **understand and
be able to explain every change**, **disclose AI assistance** in the pull request, **verify and test
the output yourself**, and **respond to review in your own words**. Fully autonomous agent
contributions are not accepted; a human must stand behind the patch.

## Community & questions

Most conversation happens in
[GitHub Discussions](https://github.com/sujaisubbanna/utter-assistant/discussions). Ask there, and be
kind — see the [Code of Conduct](CODE_OF_CONDUCT.md).

## Thank you

Every bug report, translation, review and patch makes Utter better — thank you for being part of it.
