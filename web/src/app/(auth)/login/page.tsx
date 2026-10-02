import { safeNext } from "@/lib/safe-next";

import { LoginForm } from "./login-form";

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { next, error } = await searchParams;
  return (
    <LoginForm
      next={safeNext(typeof next === "string" ? next : null)}
      authFailed={error === "auth"}
    />
  );
}
