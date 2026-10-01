// Copy the demo media from docs/media/ into the site's public/ directory, so
// GitHub Pages serves it with the correct content type. The copy exists only in
// the build output; the repository keeps a single copy of the video.
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
