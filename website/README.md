# Utter documentation site

The documentation site for Utter, built with [Astro Starlight](https://starlight.astro.build/).
It is published to GitHub Pages at `https://sujaisubbanna.github.io/utter-assistant/` by
`.github/workflows/pages.yml`, together with the hosted installer (`/install.sh`).

```bash
pnpm install
pnpm dev        # live reload at http://localhost:4321/utter-assistant/
pnpm build      # production build into dist/
pnpm preview    # serve the production build
```

## Layout

| Path | Purpose |
|---|---|
| `astro.config.mjs` | site/base (`/utter-assistant`), sidebar, logo, social links |
| `src/content/docs/` | the pages (Markdown/MDX) |
| `src/assets/` | logo, wordmarks and screenshots used by pages |
| `src/styles/custom.css` | theme: accent colour, fonts, spacing, home-page helpers |
| `src/plugins/rehype-base-links.mjs` | prefixes root-relative links in content with the base path |
| `public/` | files copied verbatim (`favicon.svg`, `.nojekyll`) |
| `screenshots/` | reference captures of the built site in light and dark |

## Writing

- Source of truth for behaviour is the code and the Markdown in `docs/`; do not document
  features that do not exist.
- Use root-relative links (`/guides/models/`); the base path is added at build time.
- Quote any frontmatter `description` that contains a colon.
- No personal information: no real names, e-mail addresses, machine names or
  `/home/<user>` paths. Use `~/...`.
