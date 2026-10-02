"use client";

import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Native <dialog>: focus trap, Esc and backdrop for free. Mount it to open, unmount to close. */
export function Modal({
  title,
  subtitle,
  onClose,
  children,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = overflow;
    };
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby="modal-title"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
      className={cn(
        "m-auto max-h-[92dvh] w-[calc(100%-1.5rem)] max-w-2xl overflow-hidden rounded-3xl border border-border bg-background p-0 text-foreground shadow-2xl backdrop:bg-[#1d2a22]/45 backdrop:backdrop-blur-sm",
        className,
      )}
    >
      <div className="flex max-h-[92dvh] flex-col">
        <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2 id="modal-title" className="text-xl font-bold">
              {title}
            </h2>
            {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="btn-ghost -mt-1 -mr-2 size-10 p-0">
            <X className="size-5" />
          </button>
        </header>
        {children}
      </div>
    </dialog>
  );
}
