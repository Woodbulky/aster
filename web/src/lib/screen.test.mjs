import assert from "node:assert/strict";
import { test } from "node:test";

import { CHANGED, NEW_PAGE, dhash, hamming } from "./screen.ts";

/** 9×8 RGBA image from a brightness function. */
function img(f) {
  const out = new Uint8ClampedArray(9 * 8 * 4);
  for (let y = 0; y < 8; y++)
    for (let x = 0; x < 9; x++) {
      const i = (y * 9 + x) * 4;
      out[i] = out[i + 1] = out[i + 2] = f(x, y);
      out[i + 3] = 255;
    }
  return out;
}

test("dhash is 64 bits and stable", () => {
  const a = img((x) => 255 - x * 20);
  assert.equal(dhash(a).length, 64);
  assert.equal(dhash(a), "1".repeat(64)); // every pixel brighter than its right neighbour
  assert.equal(hamming(dhash(a), dhash(img((x) => 255 - x * 20))), 0);
});

test("a small change stays under CHANGED, a different page goes over NEW_PAGE", () => {
  const page = (x, y) => ((x * 37 + y * 91) % 7) * 30;
  const base = dhash(img(page));
  const typed = dhash(img((x, y) => (x === 4 && y === 3 ? 255 : page(x, y)))); // one cell changed
  const other = dhash(img((x, y) => 255 - page(x, y))); // inverted: a different page
  assert.ok(hamming(base, typed) <= CHANGED);
  assert.ok(hamming(base, other) > NEW_PAGE);
});
