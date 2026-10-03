/** Client-side blur check before upload (VERIFICATION.md step 2): variance of the Laplacian of a
 * downscaled grayscale copy. Sharp text has strong edges (high variance); a shaken photo does not. */

/** Below this the photo is probably too blurry to read. Calibrated on the income-certificate
 * specimen at 800 px: sharp 2242, 2x blur 326 (readable), 3x blur 82 (small text lost), 13, 3.
 * Calibration knob: re-check on real phone photos. */
export const BLUR_MIN = 100;
const MAX_SIDE = 800; // downscale first: the score then means the same for any camera size

export function laplacianVariance(gray: ArrayLike<number>, w: number, h: number): number {
  let sum = 0;
  let sq = 0;
  let n = 0;
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const v = 4 * gray[i] - gray[i - 1] - gray[i + 1] - gray[i - w] - gray[i + w];
      sum += v;
      sq += v * v;
      n++;
    }
  }
  if (!n) return 0;
  const mean = sum / n;
  return sq / n - mean * mean;
}

/** null for PDFs (not photos) or when the browser can't decode the image. */
export async function blurScore(file: File): Promise<number | null> {
  if (!file.type.startsWith("image/")) return null;
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
    const w = Math.max(3, Math.round(bmp.width * scale));
    const h = Math.max(3, Math.round(bmp.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(bmp, 0, 0, w, h);
    const rgba = ctx.getImageData(0, 0, w, h).data;
    const gray = new Float32Array(w * h);
    for (let i = 0; i < gray.length; i++) gray[i] = 0.299 * rgba[i * 4] + 0.587 * rgba[i * 4 + 1] + 0.114 * rgba[i * 4 + 2];
    return Math.round(laplacianVariance(gray, w, h));
  } catch {
    return null;
  }
}
