"use client";

import { FolderOpen, History, House, LogOut, Menu, MessageCircle, UserRound, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

import { AsterMark, Avatar } from "@/components/avatar/Avatar";
import { ConsentHost } from "@/components/consent/ConsentHost";
import { ProfileSetup } from "@/components/profile/ProfileSetup";
import { completion } from "@/components/profile/ProfileForm";
import { clearLocalCache, loadMe, wakeBackend, type ProfileDraft, useAssistant, useProfile } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

type User = { name: string; email: string };
type Shell = { user: User | null; profile: ProfileDraft | null | undefined; openSetup: (step?: number) => void };
const LATER_KEY = "aster.setup.later";
const ShellContext = createContext<Shell | null>(null);
export const useShell = () => useContext(ShellContext)!;

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase() || "?";

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const profile = useProfile();
  const assistant = useAssistant();
  const [user, setUser] = useState<User | null>(null);
  const [menu, setMenu] = useState(false);
  const [setupStep, setSetupStep] = useState<number | null>(null);
  // "Later" holds for this browser session. Read lazily: the pop-up never renders during hydration.
  const [dismissed, setDismissed] = useState(() => {
    try {
      return sessionStorage.getItem(LATER_KEY) === "1";
    } catch {
      return false;
    }
  });

  // The pop-up waits for loadMe: before it returns, a new browser has no local profile even when
  // the account has one (seen: the demo account's seeded profile was overwritten via the pop-up).
  const [meLoaded, setMeLoaded] = useState(false);
  useEffect(() => {
    wakeBackend();
    loadMe() // local choices win; this only fills an empty cache
      .catch(console.error)
      .finally(() => setMeLoaded(true));
    createClient()
      .auth.getUser()
      .then(({ data }) => {
        const u = data.user;
        if (!u) return;
        const meta = u.user_metadata as { full_name?: string; name?: string };
        setUser({ name: meta.full_name ?? meta.name ?? u.email?.split("@")[0] ?? "", email: u.email ?? "" });
      });
  }, []);

  // First visit after sign-in: the profile pop-up opens by itself until something is saved or it's dismissed.
  const showSetup = setupStep !== null || (meLoaded && profile === null && !dismissed);
  const displayName = profile?.full_name?.trim() || user?.name || "Student";
  const pct = completion(profile);

  const nav = [
    { href: "/home", label: "Home", icon: House },
    { href: "/chat", label: `Talk to ${assistant.assistant_name}`, icon: MessageCircle },
    { href: "/documents", label: "My documents", icon: FolderOpen },
    { href: "/sessions", label: "My applications", icon: History },
    { href: "/profile", label: "My profile", icon: UserRound },
  ];
  const title = nav.find((n) => path.startsWith(n.href))?.label ?? "";

  async function signOut() {
    await createClient().auth.signOut();
    clearLocalCache();
    router.replace("/");
  }

  return (
    <ShellContext.Provider value={{ user, profile, openSetup: (s = 0) => setSetupStep(s) }}>
      <div className="flex h-dvh overflow-hidden">
        {menu && <button aria-label="Close menu" onClick={() => setMenu(false)} className="fixed inset-0 z-30 bg-black/30 lg:hidden" />}
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-40 flex w-72 flex-col gap-6 border-r border-sidebar-border bg-sidebar p-5 transition-transform lg:static lg:translate-x-0",
            menu ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <div className="flex items-center justify-between">
            <Link href="/home" className="flex items-center gap-2 text-primary" onClick={() => setMenu(false)}>
              <AsterMark size={30} />
              <span className="font-heading text-2xl font-bold tracking-tight">
                aster<span className="text-[#e3a46f]">.</span>
              </span>
            </Link>
            <button onClick={() => setMenu(false)} aria-label="Close menu" className="btn-ghost size-10 p-0 lg:hidden">
              <X className="size-5" />
            </button>
          </div>

          <nav className="flex flex-col gap-1">
            <span className="eyebrow mb-2 px-3">Your workspace</span>
            {nav.map((n) => {
              const active = path.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  onClick={() => setMenu(false)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-12 items-center gap-3 rounded-xl px-3 font-medium transition-colors",
                    active ? "bg-sidebar-accent text-primary" : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
                  )}
                >
                  <n.icon className="size-5" strokeWidth={1.8} />
                  <span className="truncate">{n.label}</span>
                  {n.href === "/chat" && <span className="ml-auto size-2 rounded-full bg-[#7fae6b]" />}
                </Link>
              );
            })}
          </nav>

          <div className="mt-auto flex flex-col gap-3">
            {pct < 100 && profile !== undefined && (
              <div className="rounded-2xl border border-[#dde5d2] bg-sage p-4">
                <div className="flex items-center gap-3">
                  <Avatar id={assistant.avatar_id} size={40} />
                  <div>
                    <p className="text-sm font-semibold">Your profile is {pct}% ready</p>
                    <p className="text-xs text-muted-foreground">Finish it once, reuse it everywhere.</p>
                  </div>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                </div>
                <button
                  onClick={() => {
                    setSetupStep(0);
                    setMenu(false);
                  }}
                  className="mt-3 text-sm font-semibold text-primary hover:underline"
                >
                  Continue setup →
                </button>
              </div>
            )}
            <div className="flex items-center gap-3 rounded-xl p-2">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#e3ead8] font-heading text-sm font-bold text-primary">
                {initials(displayName)}
              </span>
              <span className="min-w-0 flex-1">
                <strong className="block truncate text-sm">{displayName}</strong>
                <small className="block truncate text-xs text-muted-foreground">{user?.email}</small>
              </span>
              <button onClick={signOut} aria-label="Sign out" title="Sign out" className="btn-ghost size-10 p-0">
                <LogOut className="size-4" />
              </button>
            </div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-16 shrink-0 items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur sm:px-6">
            <button onClick={() => setMenu(true)} aria-label="Open menu" aria-expanded={menu} className="btn-ghost size-10 p-0 lg:hidden">
              <Menu className="size-5" />
            </button>
            <span className="text-sm text-muted-foreground">Your workspace</span>
            <span className="text-sm text-muted-foreground">/</span>
            <strong className="truncate text-sm">{title}</strong>
            <Link
              href="/profile"
              aria-label="Open profile"
              className="ml-auto flex size-9 items-center justify-center rounded-full bg-[#e3ead8] font-heading text-xs font-bold text-primary"
            >
              {initials(displayName)}
            </Link>
          </header>
          <main className="relative min-h-0 flex-1 overflow-y-auto">{children}</main>
        </div>
      </div>

      <ConsentHost />
      {showSetup && profile !== undefined && user && (
        <ProfileSetup
          startAt={setupStep ?? 0}
          profile={profile ?? (user?.name ? { full_name: user.name } : {})}
          assistant={assistant}
          onClose={() => {
            setSetupStep(null);
            setDismissed(true);
            try {
              sessionStorage.setItem(LATER_KEY, "1");
            } catch {}
          }}
        />
      )}
    </ShellContext.Provider>
  );
}
