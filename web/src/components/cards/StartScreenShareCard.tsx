"use client";

import { MonitorUp } from "lucide-react";
import Link from "next/link";

import type { StartScreenSharePayload } from "@/lib/ws/protocol";

/** Opens guided filling: the user shares the portal tab on a laptop; Aster guides field by field. */
export function StartScreenShareCard({ payload }: { payload: StartScreenSharePayload }) {
  return (
    <section aria-label="Guided filling" className="card max-w-xl border-l-4 border-l-primary p-5">
      <h2 className="flex items-center gap-2 font-heading font-semibold">
        <MonitorUp className="size-5 text-primary" /> Fill {payload.scheme || "the form"} together
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        On a laptop (Chrome): open the portal in another tab and log in yourself, then share that tab. You type, check and submit.
      </p>
      <Link href={`/fill/${payload.session_id}`} className="btn-primary mt-3 inline-flex h-10 gap-2 rounded-xl px-4 text-sm">
        Start guided filling
      </Link>
    </section>
  );
}
