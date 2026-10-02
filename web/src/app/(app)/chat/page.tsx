"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { openSession } from "@/lib/api";

/** /chat → the latest active conversation, or a new one. */
export default function ChatIndex() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    openSession()
      .then((id) => router.replace(`/chat/${id}`))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't open the conversation."));
  }, [router]);
  return (
    <div role="status" className="flex h-full items-center justify-center p-8 text-muted-foreground">
      {error ?? "Opening your conversation…"}
    </div>
  );
}
