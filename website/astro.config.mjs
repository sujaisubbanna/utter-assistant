// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import rehypeBaseLinks from './src/plugins/rehype-base-links.mjs';

const REPO = 'https://github.com/sujaisubbanna/utter-assistant';

// ---------------------------------------------------------------------------
// Where the site is served from.
//
// The single canonical origin is the custom domain on Vercel:
// https://utter.sujaisubbanna.com with no subpath. GitHub Pages is retired.
// SITE_URL / BASE_PATH can still be set to build a preview or a self-hosted
// copy at another origin; they default to the canonical domain.
// ---------------------------------------------------------------------------
const SITE_URL = process.env.SITE_URL ?? 'https://utter.sujaisubbanna.com';
const rawBase = process.env.BASE_PATH ?? '/';
const BASE_PATH = rawBase === '' || rawBase === '/' ? '/' : '/' + rawBase.replace(/^\/+|\/+$/g, '');
// Absolute origin + subpath, used for canonical-adjacent tags (OG image). Social
// crawlers need a fully-qualified URL and cannot use a root-relative path.
const SITE = BASE_PATH === '/' ? SITE_URL : `${SITE_URL}${BASE_PATH}`;

// Non-default locales. English is the root locale, so `/` is English and each
// translation lives under its own prefix (`/es/`, `/de/`, `/ja/`).
const LOCALES = {
  root: { label: 'English', lang: 'en' },
  es: { label: 'Español', lang: 'es' },
  de: { label: 'Deutsch', lang: 'de' },
  ja: { label: '日本語', lang: 'ja' },
};
const LOCALE_CODES = ['es', 'de', 'ja'];

// Sidebar labels translated per locale. The `translations` map is what Starlight
// reads; the English `label` is the fallback and the source of truth.
const label = (en, es, de, ja) => ({ label: en, translations: { es, de, ja } });

export default defineConfig({
  site: SITE_URL,
  base: BASE_PATH,
  trailingSlash: 'always',
  markdown: {
    // Prefix root-relative content links with `base` and, inside a translated
    // page, with the page's locale so links stay within the language.
    rehypePlugins: [[rehypeBaseLinks, { base: BASE_PATH, locales: LOCALE_CODES }]],
  },
  integrations: [
    starlight({
      title: 'Utter',
      description:
        'Utter turns your voice into actions on Linux and macOS. Hold a key, say what you want, and it happens. Local, offline and private.',
      defaultLocale: 'root',
      locales: LOCALES,
      // Global head additions. Starlight already emits title/description/
      // canonical/hreflang/OG/Twitter defaults from frontmatter; this adds the
      // social preview image (absolute, so crawlers can fetch it) and points
      // twitter:image at the same asset.
      head: [
        { tag: 'meta', attrs: { property: 'og:image', content: `${SITE}/og.png` } },
        { tag: 'meta', attrs: { property: 'og:image:width', content: '1200' } },
        { tag: 'meta', attrs: { property: 'og:image:height', content: '630' } },
        { tag: 'meta', attrs: { property: 'og:image:alt', content: 'The Utter settings app, with the wordmark Utter.' } },
        { tag: 'meta', attrs: { name: 'twitter:image', content: `${SITE}/og.png` } },
        { tag: 'meta', attrs: { name: 'twitter:image:alt', content: 'The Utter settings app, with the wordmark Utter.' } },
      ],
      // Override the default Head component to add JSON-LD (SoftwareApplication
      // on the landing page, TechArticle on docs pages) using the env-driven
      // origin so structured data matches canonical/OG tags.
      components: {
        Head: './src/components/Head.astro',
      },
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
          ...label('Start here', 'Empieza aquí', 'Erste Schritte', 'はじめに'),
          items: [
            { ...label('Introduction', 'Introducción', 'Einführung', 'はじめに'), slug: 'introduction' },
            { ...label('Getting started', 'Primeros pasos', 'Erste Schritte', 'はじめかた'), slug: 'getting-started' },
          ],
        },
        {
          ...label('Install', 'Instalación', 'Installation', 'インストール'),
          items: [
            { ...label('Overview', 'Resumen', 'Überblick', '概要'), slug: 'install' },
            { ...label('Install from the web', 'Instalar desde la web', 'Aus dem Web installieren', 'Web からインストール'), slug: 'install/remote' },
            { ...label('Agent-driven install', 'Instalación con un agente', 'Installation per Agent', 'エージェントによるインストール'), slug: 'install/agent' },
            { ...label('Clone and build from source', 'Clonar y compilar desde el código fuente', 'Aus dem Quellcode klonen und bauen', 'ソースからクローンしてビルド'), slug: 'install/from-source' },
          ],
        },
        {
          ...label('Guides', 'Guías', 'Anleitungen', 'ガイド'),
          items: [
            { ...label('Configuration', 'Configuración', 'Konfiguration', '設定'), slug: 'guides/configuration' },
            { ...label('Apps and actions', 'Aplicaciones y acciones', 'Apps und Aktionen', 'アプリとアクション'), slug: 'guides/apps-and-actions' },
            { ...label('How Utter compares', 'Cómo se compara Utter', 'Utter im Vergleich', 'Utter の比較'), slug: 'guides/comparison' },
            { ...label('Models', 'Modelos', 'Modelle', 'モデル'), slug: 'guides/models' },
            { ...label('Trust and safety', 'Confianza y seguridad', 'Vertrauen und Sicherheit', '信頼と安全性'), slug: 'guides/trust-and-safety' },
            { ...label('Theming', 'Temas', 'Theming', 'テーマ'), slug: 'guides/theming' },
            { ...label('Noctalia widget and OSD', 'Widget de Noctalia y OSD', 'Noctalia-Widget und OSD', 'Noctalia ウィジェットと OSD'), slug: 'guides/noctalia' },
            { ...label('KDE Plasma', 'KDE Plasma', 'KDE Plasma', 'KDE Plasma'), slug: 'guides/kde-plasma' },
            { ...label('macOS', 'macOS', 'macOS', 'macOS'), slug: 'guides/macos' },
          ],
        },
        {
          ...label('Plugins', 'Complementos', 'Plugins', 'プラグイン'),
          items: [
            { ...label('Plugin protocol', 'Protocolo de complementos', 'Plugin-Protokoll', 'プラグインプロトコル'), slug: 'plugins' },
            { ...label('Writing a plugin', 'Escribir un complemento', 'Ein Plugin schreiben', 'プラグインの書き方'), slug: 'plugins/writing-a-plugin' },
          ],
        },
        {
          ...label('Help', 'Ayuda', 'Hilfe', 'ヘルプ'),
          items: [
            { ...label('Troubleshooting', 'Solución de problemas', 'Fehlerbehebung', 'トラブルシューティング'), slug: 'help/troubleshooting' },
            { ...label('FAQ', 'Preguntas frecuentes', 'FAQ', 'よくある質問'), slug: 'help/faq' },
          ],
        },
        {
          ...label('Reference', 'Referencia', 'Referenz', 'リファレンス'),
          items: [
            { ...label('Architecture', 'Arquitectura', 'Architektur', 'アーキテクチャ'), slug: 'reference/architecture' },
            { ...label('The utter CLI (agents)', 'La CLI utter (agentes)', 'Die utter-CLI (Agenten)', 'utter CLI(エージェント向け)'), slug: 'reference/cli-agent' },
            { ...label('The assistant CLI', 'La CLI assistant', 'Die assistant-CLI', 'assistant CLI'), slug: 'reference/cli-assistant' },
            { ...label('Releasing', 'Publicación de versiones', 'Veröffentlichungen', 'リリース'), slug: 'reference/releasing' },
          ],
        },
      ],
    }),
  ],
});
