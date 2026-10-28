import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";

const destination = new URL("../app/static/vendor/", import.meta.url);
await mkdir(destination, { recursive: true });
for (const [source, target] of [
  ["markdown-it/dist/browser/markdown-it.umd.min.js", "markdown-it.min.js"],
  ["markdown-it/LICENSE", "markdown-it.LICENSE"],
  ["dompurify/dist/purify.min.js", "purify.min.js"],
  ["dompurify/LICENSE", "DOMPurify.LICENSE"],
  ["dompurify/LICENSE-MPL", "DOMPurify.LICENSE-MPL"],
]) {
  await copyFile(
    new URL(`../node_modules/${source}`, import.meta.url),
    new URL(target, destination),
  );
}
const manifest = JSON.parse(
  await readFile(new URL("../package.json", import.meta.url)),
);
await writeFile(
  new URL("README.md", destination),
  `# Browser dependencies\n\nLocally bundled from npm with scripts/vendor-markdown.mjs.\n\n- markdown-it ${manifest.devDependencies["markdown-it"]} (MIT)\n- DOMPurify ${manifest.devDependencies.dompurify} (Apache-2.0 / MPL-2.0)\n\nSee package-lock.json for integrity hashes and adjacent license files. No CDN requests are needed at runtime.\n`,
);
