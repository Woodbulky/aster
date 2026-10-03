import assert from "node:assert/strict";
import { test } from "node:test";

import { BLUR_MIN, laplacianVariance } from "./blur.ts";

/** Black text-like strokes on white, then a box blur of the same image. */
function strokes(w, h) {
  const g = new Float32Array(w * h).fill(255);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (y % 12 < 3 && x % 9 < 6) g[y * w + x] = 0;
  return g;
}
function boxBlur(src, w, h, r) {
  const out = new Float32Array(w * h);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      let s = 0;
      let n = 0;
      for (let dy = -r; dy <= r; dy++)
        for (let dx = -r; dx <= r; dx++) {
          const yy = y + dy;
          const xx = x + dx;
          if (yy >= 0 && yy < h && xx >= 0 && xx < w) {
            s += src[yy * w + xx];
            n++;
          }
        }
      out[y * w + x] = s / n;
    }
  return out;
}

test("sharp text scores high, the same text blurred scores below BLUR_MIN", () => {
  const w = 200;
  const h = 120;
  const sharp = laplacianVariance(strokes(w, h), w, h);
  const blurred = laplacianVariance(boxBlur(strokes(w, h), w, h, 6), w, h);
  assert.ok(sharp > 10 * BLUR_MIN, `sharp=${sharp}`);
  assert.ok(blurred < BLUR_MIN, `blurred=${blurred}`);
});

test("a blank page scores zero", () => {
  assert.equal(laplacianVariance(new Float32Array(50 * 50).fill(200), 50, 50), 0);
});
