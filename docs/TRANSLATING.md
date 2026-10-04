# Translating utter

utter is translated through **Crowdin** (free for open-source projects). Crowdin
is a **build-time tool only** — translators work there, finished strings are
exported into this repository as committed locale files, and the app bundles
whatever is committed. Nothing is fetched at runtime, and using utter never
contacts Crowdin.

## Where the strings live

| Surface | Source (English) | Translations |
|---|---|---|
| Settings app UI | `gui-tauri/src/i18n/en.ts` | `gui-tauri/src/i18n/<lang>.ts` |
| Installer | `install/install.sh` (English inline; no `en.sh`) | `install/i18n/<lang>.sh` |
| Documentation website | `website/src/content/docs/*.md(x)` | `website/src/content/docs/<lang>/*.md(x)` |

`en.ts` is the source of truth: every other locale is typed against it
(`const de: Messages`), so a missing or misspelt key is a **compile error**. The
installer looks translations up by their exact English message and falls back to
English for anything missing.

## Current languages

Top-10, machine-drafted: **en** (source), **es, de, fr, it, pt, zh, ja, ko, ru**.

> **These drafts are machine-generated and UNREVIEWED.** They exist so the app
> is not English-only from day one. They are not checked by native speakers and
> may contain errors, especially in the installer's prompts. Corrections are
> very welcome — that is what Crowdin is for.

## Translating (recommended: Crowdin)

1. Go to the utter project on Crowdin and pick a language. (If it does not exist
   yet, open an issue to request it.)
2. Translate the strings. Keep placeholders like `{name}` and plural keys
   (`one` / `other`) intact; do not translate keys, ids, paths or command names.
3. A maintainer runs the sync; finished strings arrive as a pull request
   (`chore/crowdin-translations`). A fluent speaker reviews, then it is merged.

## Translating without Crowdin

Editing the locale file directly is fine for a fix, as long as you keep key
parity with `en.ts`:

```bash
cd gui-tauri && pnpm install && pnpm exec tsc --noEmit   # fails on key mismatch
```

## Documentation website

The docs site (`website/`, Astro Starlight) supports **es**, **de** and **ja**.
English is the root locale (`/`); other languages live under a prefix
(`/es/`, `/de/`, `/ja/`). Starlight shows a language picker automatically and
falls back to the English page (with a notice) for any page without a
translation.

Add or fix a translation by creating the same path under
`website/src/content/docs/<lang>/` (for example
`website/src/content/docs/de/guides/configuration.md`). Rules:

- Keep the frontmatter `title` and `description` translated too.
- Do **not** translate code, commands, config keys, file paths or identifiers.
- Internal links use root-relative paths (`/guides/models/`); the build adds
  both the base path and the locale automatically.
- Each translated page must carry the unreviewed-translation banner in its
  frontmatter (see the existing files for the exact `banner.content`).

The docs locale set is distinct from the app/installer locales: the docs do not
have to cover every UI language. The website translations are currently
**machine-drafted, unreviewed** — treat them as drafts until a fluent speaker
reviews them.

## Adding a new language

1. Add `gui-tauri/src/i18n/<lang>.ts` (copy `en.ts`, translate the values, type
   it `const <lang>: Messages`).
2. Register it in `gui-tauri/src/i18n/index.tsx`: add to `LOCALES`, `LANGS` and
   `LANG_NAMES` (native name).
3. Installer: add `install/i18n/<lang>.sh` (keyed by exact English message;
   English fallback). Copy an existing file for the format.
4. Website (optional): add `website/src/content/docs/<lang>/` and register the
   locale in `website/astro.config.mjs` (`locales` + the sidebar `translations`).
5. Add the language to the Crowdin config if you want community translations.
6. Run `pnpm exec tsc --noEmit`, the installer's `--dry-run`, and
   `cd website && pnpm build` to check nothing broke.

## Maintainer setup (Crowdin)

The sync (`.github/workflows/crowdin.yml`) is a **no-op without credentials**.
To enable it, set repository secrets `CROWDIN_PROJECT_ID` and
`CROWDIN_PERSONAL_TOKEN`; the workflow then uploads the English sources
(`gui-tauri/src/i18n/en.ts` and the inline English in `install/install.sh`) and
opens a PR with new translations.
