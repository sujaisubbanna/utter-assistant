// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import rehypeBaseLinks from './src/plugins/rehype-base-links.mjs';

const REPO = 'https://github.com/sujaisubbanna/utter-assistant';
const BASE = '/utter-assistant';

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
        'Utter turns your voice into actions on your Linux desktop. Local, offline and private.',
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
            { label: 'The assistant CLI', slug: 'reference/cli' },
            { label: 'Releasing', slug: 'reference/releasing' },
          ],
        },
      ],
    }),
  ],
});
