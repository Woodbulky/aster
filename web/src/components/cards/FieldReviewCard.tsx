"use client";

import { FileSearch, LoaderCircle, ScanText, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { pageUrl } from "@/lib/documents";
import { cn } from "@/lib/utils";
import type { BBox, FieldReviewPayload, PageMeta, ReviewField } from "@/lib/ws/protocol";

/** The page image with the cited lines boxed. No bbox (read by the vision model) = no box. */
function DocumentViewer({ title, page, boxes, onClose }: { title: string; page: PageMeta; boxes: BBox[]; onClose: () => void }) {
  const [url, setUrl] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    pageUrl(page.path).then(setUrl, () => setUrl(null));
  }, [page.path]);
  return (
    <Modal title={title} subtitle={boxes.length ? "The highlighted line is where Aster read this value." : "Read by AI from the image: check the value against the page."} onClose={onClose} className="max-w-3xl">
      <div className="overflow-auto p-4">
        {url === undefined ? (
          <LoaderCircle className="mx-auto my-16 size-6 animate-spin text-muted-foreground" />
        ) : url === null ? (
          <p className="p-6 text-sm text-destructive">Couldn&apos;t open the page. Try again.</p>
        ) : (
          <div className="relative">
            {/* eslint-disable-next-line @next/next/no-img-element -- signed, short-lived storage URL */}
            <img src={url} alt={title} className="block w-full rounded-lg border border-border" />
            {boxes.map(([x0, y0, x1, y1], i) => (
              <span
                key={i}
                aria-hidden
                className="absolute rounded-sm bg-[#f5c542]/30 ring-2 ring-[#d69e2e]"
                style={{
                  left: `${(x0 / page.width) * 100}%`,
                  top: `${(y0 / page.height) * 100}%`,
                  width: `${((x1 - x0) / page.width) * 100}%`,
                  height: `${((y1 - y0) / page.height) * 100}%`,
                }}
              />
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}

/** Every value read from one document, each with its source chip (guardrail 2). */
export function FieldReviewCard({ payload }: { payload: FieldReviewPayload }) {
  const [open, setOpen] = useState<ReviewField | null>(null);
  const page = open ? payload.pages[open.source.page] : null;
  return (
    <section aria-label={`Values read from your ${payload.label}`} className="card max-w-xl p-5">
      <h3 className="flex items-start gap-2 font-heading font-semibold">
        <ScanText className="mt-0.5 size-5 shrink-0 text-primary" /> Read from your {payload.label}
      </h3>
      {payload.engine === "vision_llm" && <p className="mt-1 text-xs text-muted-foreground">Read by AI from the photo — please check each value.</p>}
      <ul className="mt-3 divide-y divide-border">
        {payload.fields.map((f) => (
          <li key={f.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
            <span className="w-40 shrink-0 text-sm text-muted-foreground">{f.label}</span>
            <strong className="min-w-0 flex-1 font-medium break-words">{f.value}</strong>
            <button
              type="button"
              onClick={() => setOpen(f)}
              className={cn("chip cursor-pointer hover:ring-1 hover:ring-primary/40", f.low_confidence ? "bg-butter" : "bg-sage text-primary")}
              aria-label={`Show where ${f.label} was read on the ${payload.label}`}
            >
              {f.low_confidence ? <TriangleAlert className="size-3.5" /> : <FileSearch className="size-3.5" />}
              {payload.label} · {f.source.line_ids.join(", ")}
            </button>
          </li>
        ))}
      </ul>
      {payload.unreadable.length > 0 && (
        <p className="mt-2 flex items-start gap-1.5 text-sm text-[#b7791f]">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" /> Not found on this document: {payload.unreadable.join(", ")}. Check these on your document.
        </p>
      )}
      {open && page && (
        <DocumentViewer
          title={`${open.label}: ${open.value}`}
          page={page}
          boxes={open.source.bbox.filter((b): b is BBox => b !== null)}
          onClose={() => setOpen(null)}
        />
      )}
    </section>
  );
}
