import {
  ArrowRight,
  BadgeCheck,
  FileStack,
  Languages,
  Link2,
  Lock,
  Mic,
  MonitorSmartphone,
  ScanText,
  Search,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import Link from "next/link";

import { AsterMark, Avatar } from "@/components/avatar/Avatar";

// Logged-out visitors hitting /home are sent through /login?next=/home by the proxy.
const START = "/home";

const STEPS = [
  { icon: UserRound, title: "Build your profile once", body: "Name, category, marks, income — saved and reused for every form you fill." },
  { icon: Search, title: "Pick a scholarship", body: "Aster researches eligibility and required documents, and shows you the sources." },
  { icon: ScanText, title: "Upload your documents", body: "Aster reads them, links every value to its document and flags any mismatch." },
  { icon: MonitorSmartphone, title: "Fill the portal together", body: "Share your screen. Aster guides you field by field, out loud, while you type." },
];

const FEATURES = [
  { icon: Languages, tone: "bg-sage", title: "Speaks your language", body: "English, हिंदी or मराठी — even mixed in one sentence. Talk or type." },
  { icon: FileStack, tone: "bg-peach", title: "Documents, once", body: "Your 10th and 12th marksheets, domicile and income certificates, kept ready for every form." },
  { icon: Link2, tone: "bg-lavender", title: "Every value has a source", body: "Each answer points back to the document line or the message it came from." },
  { icon: ShieldCheck, tone: "bg-butter", title: "You stay in control", body: "Mismatches are never fixed silently. You choose the value and say why." },
];

const PROMISES = [
  "Never asks for portal passwords, OTPs or captchas",
  "Never clicks Submit or Pay — you do",
  "Stores only the last 4 digits of Aadhaar",
  "Eligibility is “meets / does not meet — per source”, never a final verdict",
];

export default function Landing() {
  return (
    <div className="flex flex-1 flex-col">
      <header className="sticky top-0 z-20 border-b border-border/70 bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2 text-primary">
            <AsterMark size={30} />
            <span className="font-heading text-2xl font-bold tracking-tight">
              aster<span className="text-[#e3a46f]">.</span>
            </span>
          </Link>
          <nav className="hidden items-center gap-7 text-sm font-medium text-muted-foreground md:flex">
            <a href="#how" className="hover:text-foreground">How it works</a>
            <a href="#features" className="hover:text-foreground">Features</a>
            <a href="#trust" className="hover:text-foreground">Your safety</a>
          </nav>
          <div className="flex items-center gap-2">
            <Link href="/login" className="btn-ghost h-10">Sign in</Link>
            <Link href={START} className="btn-primary h-10 px-4 text-sm">Get started</Link>
          </div>
        </div>
      </header>

      <main>
        {/* Hero */}
        <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 pt-12 pb-16 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pt-20 lg:pb-24">
          <div>
            <span className="eyebrow flex items-center gap-2">
              <span className="size-1.5 rounded-full bg-primary" /> Scholarships made simpler · MahaDBT
            </span>
            <h1 className="mt-5 text-5xl leading-[1.05] font-bold text-primary sm:text-6xl">
              Big dreams.
              <br />
              Less paperwork.
            </h1>
            <p className="mt-6 max-w-lg text-lg leading-relaxed text-muted-foreground">
              Aster is your voice and chat companion for scholarship forms. It learns your details once, checks your
              documents, and walks you through the official portal — in the language you&apos;re most comfortable with.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link href={START} className="btn-primary px-6">
                Get started free <ArrowRight className="size-4" />
              </Link>
              <Link href="/login" className="btn-subtle px-6">I already have an account</Link>
            </div>
            <p className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
              <BadgeCheck className="size-4 text-primary" /> Sign in with Google or email. No password to remember.
            </p>
          </div>

          <div className="relative">
            <div className="relative overflow-hidden rounded-[28px] border border-border bg-gradient-to-br from-[#eef3e6] via-[#f5f7ef] to-[#fbf3ea] px-6 py-12 sm:px-10">
              <div aria-hidden className="absolute top-1/2 left-1/2 size-[340px] -translate-1/2 rounded-full border border-[#dfe7d3]" />
              <div aria-hidden className="absolute top-1/2 left-1/2 size-[230px] -translate-1/2 rounded-full border border-[#dfe7d3]" />
              <span aria-hidden className="absolute top-8 left-10 text-2xl text-[#9db58a]">✧</span>
              <span aria-hidden className="absolute right-10 bottom-10 text-xl text-[#d3a37c]">✦</span>
              <div className="relative flex flex-col items-center gap-8">
                <div className="flex items-end gap-2">
                  <Avatar id="mitra" size={190} />
                  <div className="-ml-6 mb-2"><Avatar id="chintu" size={64} /></div>
                </div>
                <div className="grid w-full max-w-sm gap-3">
                  <HeroChip icon={<Mic className="size-4" />} tone="bg-sage" title="“माझं उत्पन्न किती लिहू?”" note="Speak Marathi, Hindi or English" />
                  <HeroChip icon={<ScanText className="size-4" />} tone="bg-peach" title="Income ₹1,48,000" note="From your income certificate, line 8" />
                  <HeroChip icon={<BadgeCheck className="size-4" />} tone="bg-lavender" title="Class 12 marksheet ready" note="Saved once, reused for every form" />
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Languages strip */}
        <section className="border-y border-border bg-sidebar">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-8 gap-y-3 px-4 py-6 text-muted-foreground sm:px-6">
            <span className="eyebrow">Talk to Aster in</span>
            {["English", "हिंदी", "मराठी", "Hinglish & mixed"].map((l) => (
              <span key={l} className="font-heading text-lg font-semibold text-foreground">{l}</span>
            ))}
          </div>
        </section>

        {/* How it works */}
        <section id="how" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <span className="eyebrow">How it works</span>
          <h2 className="mt-3 max-w-xl text-4xl font-bold">One calm step at a time.</h2>
          <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className="card flex flex-col gap-4 p-6">
                <div className="flex items-center justify-between">
                  <span className="flex size-11 items-center justify-center rounded-xl bg-sage text-primary">
                    <s.icon className="size-5" />
                  </span>
                  <span className="font-heading text-3xl font-bold text-[#d7ddcf]">0{i + 1}</span>
                </div>
                <h3 className="text-lg font-semibold">{s.title}</h3>
                <p className="leading-relaxed text-muted-foreground">{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* Features */}
        <section id="features" className="scroll-mt-20 bg-sidebar">
          <div className="mx-auto grid max-w-6xl gap-12 px-4 py-20 sm:px-6 lg:grid-cols-[0.8fr_1.2fr]">
            <div>
              <span className="eyebrow">Why students like it</span>
              <h2 className="mt-3 text-4xl font-bold">A friend who knows the forms.</h2>
              <p className="mt-4 text-lg leading-relaxed text-muted-foreground">
                Scholarship portals are long, strict and in English. Aster sits next to you, explains every field in
                your language, and makes sure what you type matches your documents.
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {FEATURES.map((f) => (
                <div key={f.title} className="card p-6">
                  <span className={`flex size-11 items-center justify-center rounded-xl ${f.tone} text-primary`}>
                    <f.icon className="size-5" />
                  </span>
                  <h3 className="mt-4 text-lg font-semibold">{f.title}</h3>
                  <p className="mt-2 leading-relaxed text-muted-foreground">{f.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Trust */}
        <section id="trust" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <div className="grid gap-10 rounded-[28px] bg-primary px-6 py-12 text-primary-foreground sm:px-12 lg:grid-cols-2">
            <div>
              <span className="text-[11px] font-semibold tracking-[0.14em] text-[#bcd3b0] uppercase">Your safety</span>
              <h2 className="mt-3 text-4xl font-bold">Aster guides. You decide and submit.</h2>
              <p className="mt-4 text-lg leading-relaxed text-[#d6e4cf]">
                Rules built into Aster itself, not just promises.
              </p>
            </div>
            <ul className="grid gap-3">
              {PROMISES.map((p) => (
                <li key={p} className="flex items-start gap-3 rounded-xl bg-white/8 p-4">
                  <Lock className="mt-0.5 size-4 shrink-0 text-[#bcd3b0]" />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Final CTA */}
        <section className="mx-auto flex max-w-3xl flex-col items-center px-4 pb-24 text-center sm:px-6">
          <Avatar id="aster" size={110} />
          <h2 className="mt-6 text-4xl font-bold">Ready when you are.</h2>
          <p className="mt-3 text-lg text-muted-foreground">Set up your profile in a few minutes. Aster takes it from there.</p>
          <Link href={START} className="btn-primary mt-8 px-7">
            Create my profile <ArrowRight className="size-4" />
          </Link>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-4 py-6 text-sm text-muted-foreground sm:flex-row sm:px-6">
          <span className="flex items-center gap-2 text-primary">
            <AsterMark size={16} /> <span className="text-muted-foreground">A little help. A brighter future.</span>
          </span>
          <span className="flex items-center gap-2">
            <ShieldCheck className="size-4" /> Final eligibility is always decided by the official authority.
          </span>
        </div>
      </footer>
    </div>
  );
}

function HeroChip({ icon, tone, title, note }: { icon: React.ReactNode; tone: string; title: string; note: string }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-white/70 bg-white/85 p-3 shadow-[0_8px_24px_#283b2d10] backdrop-blur">
      <span className={`flex size-9 shrink-0 items-center justify-center rounded-xl ${tone} text-primary`}>{icon}</span>
      <span className="min-w-0">
        <strong className="block truncate text-sm font-semibold">{title}</strong>
        <small className="block truncate text-xs text-muted-foreground">{note}</small>
      </span>
    </div>
  );
}
