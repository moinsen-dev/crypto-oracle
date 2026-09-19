import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { validateResearch, assertPublicText } from './public-data.mjs';

const research = JSON.parse(await readFile(new URL('../src/data/research.json', import.meta.url), 'utf8'));
const operator = JSON.parse(await readFile(new URL('../src/data/operator.json', import.meta.url), 'utf8'));
validateResearch(research);
assert.match(operator.email, /^[^\s@]+@[^\s@]+\.[^\s@]+$/, 'A verified public contact email is required before release');
for (const field of ['name', 'street', 'postalCode', 'city', 'country', 'vatId', 'source']) assert.ok(operator[field]?.trim(), `Missing operator field: ${field}`);

const directory = new URL('../dist/', import.meta.url);
const allowed = new Set(['index.html', 'method/index.html', 'build-notes/index.html', 'paper-portfolio/index.html', 'forecasts/index.html', 'legal/index.html', 'privacy/index.html', '404.html', 'data/research.json', 'scripts/benchmark.js', 'scripts/paper.js', 'scripts/forecasts.js', 'favicon.svg', 'robots.txt', '_headers', '.assetsignore']);
let count = 0;
async function inspect(relative = '') {
  for (const entry of await readdir(new URL(relative, directory), { withFileTypes: true })) {
    const file = join(relative, entry.name);
    if (entry.isDirectory()) { await inspect(`${file}/`); continue; }
    assert.ok(entry.isFile(), `Unexpected non-file asset: ${file}`);
    assert.ok(allowed.has(file) || /^_astro\/[A-Za-z0-9_.-]+\.css$/.test(file), `Unexpected published file: ${file}`);
    const body = await readFile(new URL(file, directory), 'utf8');
    assertPublicText(body, file);
    count++;
  }
}
await inspect();
const output = JSON.parse(await readFile(new URL('data/research.json', directory), 'utf8'));
assert.deepEqual(output, research, 'Public result export must match the reviewed snapshot exactly');
for (const page of ['index.html', 'method/index.html', 'build-notes/index.html', 'paper-portfolio/index.html', 'forecasts/index.html', 'legal/index.html', 'privacy/index.html', '404.html']) {
  const html = await readFile(new URL(page, directory), 'utf8');
  assert.match(html, /<html lang="en"/);
  assert.match(html, /href="\/privacy\/"/);
  assert.match(html, /href="\/legal\/"/);
}
const headers = await readFile(new URL('_headers', directory), 'utf8');
assert.ok(headers.includes("connect-src 'self'"));
assert.ok(headers.includes("frame-ancestors 'none'"));
assert.ok(headers.includes('Referrer-Policy: no-referrer'));
console.log(`Public release checks passed: ${count} files, six aggregate results, complete operator details, no private backend material or unapproved embedded scripts.`);
