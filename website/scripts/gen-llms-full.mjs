// Generate public/llms-full.txt at build time: the full English documentation as
// one plain-text file, following the llms.txt convention
// (https://llmstxt.org/). Generated, not committed, so it cannot go stale.
//
// Only the default-locale (English) pages are included: the translated pages are
// machine-drafted and unreviewed. Frontmatter is stripped; fenced code blocks are
// kept verbatim (they contain the actual commands, config keys and paths).
import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const docsDir = resolve(here, '../src/content/docs');
const outFile = resolve(here, '../public/llms-full.txt');
const base = 'https://utter.sujaisubbanna.com';

// Skip the non-default locale directories; they are machine-drafted.
const LOCALES = new Set(['es', 'de', 'ja']);

/** Order the pages the way the sidebar does, so the file reads naturally. */
const ORDER = [
  'index.mdx',
  'introduction.md',
  'getting-started.md',
  'demo.mdx',
  'install/index.md',
  'install/remote.md',
  'install/from-source.md',
  'guides/configuration.md',
  'guides/apps-and-actions.md',
  'guides/models.md',
  'guides/trust-and-safety.md',
  'guides/theming.md',
  'guides/noctalia.md',
  'guides/kde-plasma.md',
  'guides/macos.md',
  'plugins/index.md',
  'plugins/writing-a-plugin.md',
  'help/troubleshooting.md',
  'help/faq.md',
  'reference/architecture.md',
  'reference/cli-agent.md',
  'reference/cli-assistant.md',
  'reference/releasing.md',
];

async function collect(dir, prefix = '') {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.isDirectory()) {
      if (!prefix && LOCALES.has(entry.name)) continue; // skip locale dirs
      files.push(...(await collect(join(dir, entry.name), prefix + entry.name + '/')));
    } else if (/\.mdx?$/.test(entry.name)) {
      files.push(prefix + entry.name);
    }
  }
  return files;
}

/** Parse simple `key: value` frontmatter and return { title, description, body }. */
function parse(raw) {
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (!match) return { title: '', description: '', body: raw };
  const front = match[1];
  const body = raw.slice(match[0].length);
  const field = (name) => {
    const m = front.match(new RegExp(`^${name}:\\s*"?([^"\\n]*)"?\\s*$`, 'm'));
    return m ? m[1].trim().replace(/\s+#.*$/, '') : '';
  };
  return { title: field('title'), description: field('description'), body: body.trim() };
}

/** Rewrite root-relative markdown links to absolute URLs on the canonical site. */
function absolutize(body) {
  return body.replace(/\]\((\/[^)\s#]*)(#[^)\s]*)?\)/g, (_m, path, hash = '') => {
    return `](${base}${path}${hash})`;
  });
}

const found = new Set(await collect(docsDir));
const files = [
  ...ORDER.filter((f) => found.has(f)),
  ...[...found].filter((f) => !ORDER.includes(f)).sort(),
];

let out = `# Utter — full documentation

Source: https://github.com/sujaisubbanna/utter-assistant
Canonical site: ${base}/
License: Apache-2.0

This file contains the complete English documentation for Utter in one place.
Localised versions are machine-drafted and unreviewed and are not included here.
See ${base}/llms.txt for a short index.

`;

for (const rel of files) {
  const raw = await readFile(join(docsDir, rel), 'utf8');
  const { title, description, body } = parse(raw);
  const url = base + '/' + rel.replace(/\.mdx?$/, '').replace(/(^|\/)index$/, '$1').replace(/\/$/, '/');
  out += `\n\n===== ${url} =====\n\n`;
  if (title) out += `# ${title}\n`;
  if (description) out += `\n> ${description}\n`;
  out += `\n${absolutize(body)}\n`;
}

await mkdir(dirname(outFile), { recursive: true });
await writeFile(outFile, out);
console.log(`[llms] wrote public/${basename(outFile)} (${files.length} pages)`);
