import { Info } from "lucide-react";

import { DocVault } from "@/components/profile/DocVault";

export default function DocumentsPage() {
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-8 px-4 py-8 sm:px-8 sm:py-10">
      <div>
        <span className="eyebrow">A little more organised</span>
        <h1 className="mt-2 text-3xl font-bold sm:text-4xl">Your documents, together.</h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          The documents nearly every scholarship asks for. Add them once — they&apos;re saved privately to your account
          and reused for each form.
        </p>
      </div>
      <DocVault />
      <p className="flex items-start gap-3 rounded-2xl bg-lavender p-4 text-sm">
        <Info className="mt-0.5 size-4 shrink-0" />
        Scheme-specific documents (fee receipt, admission letter…) are requested when you start a form. Aadhaar and bank
        passbook are never stored here — you read those numbers from your own copy.
      </p>
    </div>
  );
}
