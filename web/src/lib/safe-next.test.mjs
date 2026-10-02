import assert from "node:assert/strict";
import { test } from "node:test";

import { safeNext } from "./safe-next.ts";

test("safeNext allows relative paths, rejects open redirects", () => {
  assert.equal(safeNext("/chat/abc?x=1"), "/chat/abc?x=1");
  const bad = [null, "", "onboarding", "https://evil.com", "//evil.com", "/\\evil.com", "/\tevil"];
  for (const b of [...bad, "javascript:alert(1)"]) {
    assert.equal(safeNext(b), "/onboarding", String(b));
  }
});

test("safeNext keeps every redirect on our origin", () => {
  for (const b of ["//evil.com", "/\\evil.com", "/%2F%2Fevil.com", "/ok"]) {
    assert.equal(new URL(safeNext(b), "https://aster.app").origin, "https://aster.app", b);
  }
});
