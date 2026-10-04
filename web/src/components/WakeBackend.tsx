"use client";

import { useEffect } from "react";

import { wakeBackend } from "@/lib/api";

/** Renders nothing: wakes the backend while the visitor reads or signs in. */
export function WakeBackend() {
  useEffect(wakeBackend, []);
  return null;
}
