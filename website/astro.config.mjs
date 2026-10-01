// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import rehypeBaseLinks from './src/plugins/rehype-base-links.mjs';

const REPO = 'https://github.com/sujaisubbanna/utter-assistant';
const BASE = '/utter-assistant';
// Absolute origin + subpath, used for canonical-adjacent tags (OG image). The
// site is served from a GitHub Pages project subpath, so fileWithBase() is not
// enough here — social crawlers need a fully-qualified URL.
const SITE = `https://sujaisubbanna.github.io${BASE}`;

// The site is served by GitHub Pages from a project subpath, so every asset
// and internal link must be prefixed with `base`. Starlight and Astro handle
// that as long as both `site` and `base` are set here.
export default defineConfig({
  site: 'https://sujaisubbanna.github.io',
  base: BASE,
  trailingSlash: 'always',
  markdown: {
    rehypePlugins: [[rehypeBaseLinks, { base: BASE }]],
  },
  integrations: [
    starlight({
      title: 'Utter',
      description:
        'Utter turns your voice into actions on Linux and macOS. Hold a key, say what you want, and it happens. Local, offline and private.',
      // Global head additions. Starlight already emits title/description/
      // canonical/OG/Twitter defaults from frontmatter; this adds the social
      // preview image (absolute, so crawlers can fetch it) and points
      // twitter:image at the same asset.
      head: [
        { tag: 'meta', attrs: { property: 'og:image', content: `${SITE}/og.png` } },
        { tag: 'meta', attrs: { property: 'og:image:width', content: '1200' } },
        { tag: 'meta', attrs: { property: 'og:image:height', content: '630' } },
        { tag: 'meta', attrs: { property: 'og:image:alt', content: 'The Utter settings app, with the wordmark Utter.' } },
        { tag: 'meta', attrs: { name: 'twitter:image', content: `${SITE}/og.png` } },
        { tag: 'meta', attrs: { name: 'twitter:image:alt', content: 'The Utter settings app, with the wordmark Utter.' } },
      ],
      logo: {
        light: './src/assets/utter-wordmark.svg',
        dark: './src/assets/utter-wordmark-dark.svg',
        replacesTitle: true,
      },
      favicon: '/favicon.svg',
      customCss: ['./src/styles/custom.css'],
      social: [
        { icon: 'github', label: 'GitHub', href: REPO },
        { icon: 'download', label: 'Releases', href: `${REPO}/releases` },
      ],
      editLink: {
        baseUrl: `${REPO}/edit/main/website/`,
      },
      sidebar: [
        {
          label: 'Start here',
          items: [
            { label: 'Introduction', slug: 'introduction' },
            { label: 'Getting started', slug: 'getting-started' },
          ],
        },
        {
          label: 'Install',
          items: [
            { label: 'Overview', slug: 'install' },
            { label: 'Install from the web', slug: 'install/remote' },
            { label: 'Clone and build from source', slug: 'install/from-source' },
          ],
        },
        {
          label: 'Guides',
          items: [
            { label: 'Configuration', slug: 'guides/configuration' },
            { label: 'Apps and actions', slug: 'guides/apps-and-actions' },
            { label: 'Models', slug: 'guides/models' },
            { label: 'Trust and safety', slug: 'guides/trust-and-safety' },
            { label: 'Theming', slug: 'guides/theming' },
            { label: 'Noctalia widget and OSD', slug: 'guides/noctalia' },
            { label: 'KDE Plasma', slug: 'guides/kde-plasma' },
            { label: 'macOS (experimental)', slug: 'guides/macos' },
          ],
        },
        {
          label: 'Plugins',
          items: [
            { label: 'Plugin protocol', slug: 'plugins' },
            { label: 'Writing a plugin', slug: 'plugins/writing-a-plugin' },
          ],
        },
        {
          label: 'Help',
          items: [
            { label: 'Troubleshooting', slug: 'help/troubleshooting' },
            { label: 'FAQ', slug: 'help/faq' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'Architecture', slug: 'reference/architecture' },
            { label: 'The utter CLI (agents)', slug: 'reference/cli-agent' },
            { label: 'The assistant CLI', slug: 'reference/cli-assistant' },
            { label: 'Releasing', slug: 'reference/releasing' },
          ],
        },
      ],
    }),
  ],
});
