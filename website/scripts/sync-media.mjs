// Copy the demo media from docs/media/ into the site's public/ directory, so
// the static build serves it with the correct content type. The copy exists only in
// the build output; the repository keeps a single copy of the video.
//
// Also stage the hosted installer at the site root, so
// https://utter.sujaisubbanna.com/install.sh serves the exact script from the
// repository (the previous GitHub Pages workflow did the same).
import { copyFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, '../../docs/media');
const dest = resolve(here, '../public/media');

const files = ['utter-demo.mp4', 'utter-demo-poster.png'];

await mkdir(dest, { recursive: true });
for (const file of files) {
  await copyFile(resolve(source, file), resolve(dest, file));
  console.log(`[media] ${file} -> public/media/${file}`);
}

// Stage install.sh at the site root (public/ root == dist/ root).
const installerSrc = resolve(here, '../../install.sh');
const installerDest = resolve(here, '../public/install.sh');
await copyFile(installerSrc, installerDest);
console.log('[installer] install.sh -> public/install.sh');
