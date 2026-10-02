import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-8 px-6 py-16 text-center">
      {/* Static orb placeholder; the animated avatar arrives in M1. */}
      <div
        aria-hidden
        className="relative size-32 rounded-full bg-primary shadow-[0_0_0_10px_var(--accent)]"
      >
        <span className="absolute top-12 left-9 h-5 w-4 rounded-full bg-background" />
        <span className="absolute top-12 right-9 h-5 w-4 rounded-full bg-background" />
      </div>

      <div className="max-w-md space-y-3">
        <h1 className="font-heading text-4xl font-bold tracking-tight">
          Meet <span className="text-primary">Aster</span>
        </h1>
        <p className="text-lg">
          Your voice assistant for scholarship forms. Speak in Marathi, Hindi or English.
        </p>
        <p lang="mr" className="text-muted-foreground">
          शिष्यवृत्ती अर्ज भरायला मदत — मराठी, हिंदी किंवा इंग्रजीत बोला.
        </p>
      </div>

      <Link
        href="/login"
        className={cn(buttonVariants(), "h-12 px-8 text-base")}
      >
        Get started
      </Link>

      <p className="max-w-sm text-sm text-muted-foreground">
        <span className="mr-1 inline-block size-2 rounded-full bg-saffron align-middle" />
        Aster guides you. You review, decide and submit.
      </p>
    </main>
  );
}
