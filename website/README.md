# Utter documentation site

The documentation site for Utter, built with [Astro Starlight](https://starlight.astro.build/).
It is published to Vercel at `https://utter.sujaisubbanna.com/` (static build;
GitHub Pages is retired), together with the hosted installer (`/install.sh`).

```bash
pnpm install
pnpm dev        # live reload at http://localhost:4321/
pnpm build      # production build into dist/
pnpm preview    # serve the production build
```

The build is static and multi-language (`en` at `/`, plus `es`, `de`, `ja`).

## Layout

| Path | Purpose |
|---|---|
| `astro.config.mjs` | site/base (env-driven, default `https://utter.sujaisubbanna.com`), locales, sidebar, logo, social links |
| `src/content/docs/` | the English pages (Markdown/MDX) |
| `src/content/docs/<lang>/` | machine-drafted translations (`es`, `de`, `ja`) |
| `src/assets/` | logo, wordmarks and screenshots used by pages |
| `src/styles/custom.css` | theme: accent colour, fonts, spacing, home-page helpers |
| `src/components/Head.astro` | head override: JSON-LD (SoftwareApplication / TechArticle) |
| `src/plugins/rehype-base-links.mjs` | prefixes root-relative links with the base and locale |
| `public/` | files copied verbatim (`favicon.svg`, `robots.txt`, `llms.txt`, `og.png`) |
| `screenshots/` | reference captures of the built site in light and dark |

## Writing

- Source of truth for behaviour is the code and the Markdown in `docs/`; do not document
  features that do not exist.
- Use root-relative links (`/guides/models/`); the base path and locale are added at build time.
- Quote any frontmatter `description` that contains a colon.
- No personal information: no real names, e-mail addresses, machine names or
  `/home/<user>` paths. Use `~/...`.
