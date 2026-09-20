import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';

// Text inside SVG charts is sized in chart units, not screen pixels; everything else has a 12px floor (DESIGN.md).
const chartText = ['.chart-axis', '.chart-tick', '.evidence-value'];
test('no stylesheet sets HTML text below 12px', () => {
  const dir = new URL('../src/styles/', import.meta.url), small = [];
  for (const file of readdirSync(dir).filter(f => f.endsWith('.css'))) {
    for (const [, selector, body] of readFileSync(new URL(file, dir), 'utf8').matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (chartText.some(c => selector.includes(c))) continue;
      for (const [, value] of body.matchAll(/font(?:-size)?:([^;]+)/g)) {
        const size = value.match(/(?<![\d.])(\.\d+|\d+\.\d+|\d+)(rem|px)/);
        if (size && Number(size[1]) * (size[2] === 'rem' ? 16 : 1) < 11.95) small.push(`${file}: ${selector.trim().slice(-60)} { ${value.trim()} }`);
      }
    }
  }
  assert.deepEqual(small, []);
});
