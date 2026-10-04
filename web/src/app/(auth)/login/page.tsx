import { WakeBackend } from "@/components/WakeBackend";
import { safeNext } from "@/lib/safe-next";

import { LoginForm } from "./login-form";

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { next, error } = await searchParams;
  return (
    <>
      <WakeBackend />
      <LoginForm
        next={safeNext(typeof next === "string" ? next : null)}
        authFailed={error === "auth"}
      />
    </>
  );
}
