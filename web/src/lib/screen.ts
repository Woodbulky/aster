/** Screen-share frame policy (docs/FORM_FILL.md): grab, downscale, JPEG; dHash change detection. */
export const FRAME_MAX_W = 1280;
export const JPEG_QUALITY = 0.7;
export const CHECK_MS = 1500; // how often the screen is checked for a change
export const MIN_GAP_MS = 3000; // at most one "change" frame per 3 s
export const CHANGED = 10; // dHash bits: the screen changed
export const NEW_PAGE = 24; // dHash bits while paused: a different page, so guidance resumes

/** 64-bit difference hash of a 9×8 RGBA image, as "0101…": each bit = a pixel is brighter than its
 * right neighbour. (A string, not a bigint: the TS target is ES2017.) */
export function dhash(rgba: ArrayLike<number>): string {
  const lum = (i: number) => rgba[i] * 0.299 + rgba[i + 1] * 0.587 + rgba[i + 2] * 0.114;
  let h = "";
  for (let y = 0; y < 8; y++)
    for (let x = 0; x < 8; x++) {
      const i = (y * 9 + x) * 4;
      h += lum(i) > lum(i + 4) ? "1" : "0";
    }
  return h;
}

export function hamming(a: string, b: string): number {
  let n = 0;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) n++;
  return n;
}

/** dHash of what the shared video shows now. */
export function hashVideo(video: HTMLVideoElement, scratch: HTMLCanvasElement): string {
  scratch.width = 9;
  scratch.height = 8;
  const c = scratch.getContext("2d", { willReadFrequently: true })!;
  c.drawImage(video, 0, 0, 9, 8);
  return dhash(c.getImageData(0, 0, 9, 8).data);
}

/** The current video frame as a JPEG at most `maxW` wide (null before the first frame). In memory only. */
export async function jpegOf(video: HTMLVideoElement, maxW = FRAME_MAX_W, quality = JPEG_QUALITY): Promise<ArrayBuffer | null> {
  const { videoWidth: w, videoHeight: h } = video;
  if (!w || !h) return null;
  const scale = Math.min(1, maxW / w);
  const c = document.createElement("canvas");
  c.width = Math.round(w * scale);
  c.height = Math.round(h * scale);
  c.getContext("2d")!.drawImage(video, 0, 0, c.width, c.height);
  const blob = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", quality));
  return blob ? blob.arrayBuffer() : null;
}
