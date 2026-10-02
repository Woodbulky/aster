import Link from "next/link";

import { Avatar } from "@/components/avatar/Avatar";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-8 px-6 py-16 text-center">
      <Avatar id="aster" size={160} />

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
