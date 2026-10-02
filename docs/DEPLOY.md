# Deploying the documentation site

The Utter docs are a **static Astro Starlight build** (`website/`) deployed to
**Vercel** at the single canonical origin:

```
https://utter.sujaisubbanna.com/
```

There is nothing else deployable in this repository — no services, no
serverless functions, no bindings. DNS for `utter.sujaisubbanna.com` points at
Vercel (`216.198.79.65`).

## How it builds

Vercel is configured by the **root `vercel.json`**:

| Setting | Value |
|---|---|
| `framework` | `null` (explicit static build; not Vercel's Astro auto-detect) |
| `installCommand` | `cd website && corepack pnpm@10.0.0 install --frozen-lockfile` |
| `buildCommand` | `cd website && corepack pnpm@10.0.0 build` |
| `outputDirectory` | `website/dist` |
| `trailingSlash` | `true` |

The Vercel project's **Root Directory** must be the repository root, so the
root `vercel.json` applies. Equivalently, a project rooted at `website/` could
use `pnpm build` / `dist`; the root file is what is committed today.

## Origin and base path

`website/astro.config.mjs` reads:

- `SITE_URL` — defaults to `https://utter.sujaisubbanna.com`
- `BASE_PATH` — defaults to `/`

Both can be overridden for a local preview or a self-hosted copy, but the
defaults are the canonical domain. **GitHub Pages is retired** and is no longer
special-cased; the site is always built for the custom domain.

Canonical, `hreflang`, Open Graph, the sitemap and `robots.txt` all derive from
these values, so they always point at the custom domain.

## The hosted installer

The build copies `install.sh` into `website/dist/` so it is served from the
site root:

```bash
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash
```

## Old links

`vercel.json` redirects the old GitHub Pages subpath to the new root:

| From | To | Status |
|---|---|---|
| `/utter-assistant` | `/` | 308 |
| `/utter-assistant/*` | `/*` | 308 |

**`sujaisubbanna.github.io` itself cannot redirect** — GitHub Pages does not
support HTTP redirects, and the Pages workflow has been removed. Anyone with the
old bookmarked URL who reaches the (retired) Pages host will not be forwarded;
the redirects above only work once traffic reaches Vercel (for example through
a custom DNS record or a link that already points at the custom domain). If the
old Pages site is kept alive for a time, it should say on the index page that the
docs have moved to <https://utter.sujaisubbanna.com/>.

## Local development

```bash
cd website
corepack pnpm@10.0.0 install
corepack pnpm@10.0.0 build     # production build into website/dist
corepack pnpm@10.0.0 preview   # serve the production build
```

The dev server runs at `http://localhost:4321/`.

## Robots and agents

- `website/public/robots.txt` — allows all crawlers and points the sitemap at
  the custom domain.
- `website/public/llms.txt` — a short index for AI agents/crawlers
  (<https://llmstxt.org/>).
- `llms-full.txt` — the full English documentation in one file, generated at
  build time by `website/scripts/gen-llms-full.mjs`.
