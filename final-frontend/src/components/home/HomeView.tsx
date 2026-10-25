"use client";

import { useState } from "react";
import { Architecture } from "@/components/arch/Architecture";
import { Logo } from "@/components/brand/Logo";
import { Margaret } from "@/components/margaret/Margaret";
import { ATTACKS } from "@/components/shared/attacks";
import { QR, useJoinUrl } from "@/components/shared/JoinQR";
import { refusalText, useHealth } from "@/components/shared/Status";
import { Button, LinkButton } from "@/components/ui";
import { DEFAULT_ROOM } from "@/lib/config";
import { kernel, KernelError } from "@/lib/kernel/rest";
import type { AttackName } from "@/lib/kernel/types";
import { useAsync } from "@/lib/useAsync";
import { cn } from "@/lib/utils";

const RULES = ["Slow it down.", "Spot check: call the bank or a family member yourself.", "Stop. Do not send."];

export function HomeView() {
  const health = useHealth();
  const ev = useAsync(() => kernel.evalResults(), [], 30000);
  const joinUrl = useJoinUrl(DEFAULT_ROOM);
  const online = !!health.data && !health.error;

  return (
    <div className="min-h-screen">
      <nav className="gutter sticky top-0 z-30 border-b border-line/70 bg-paper/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1240px] items-center justify-between gap-6">
          <a href="/" aria-label="Second Key home">
            <Logo />
          </a>
          <div className="hidden items-center gap-7 text-[14px] text-ink-2 md:flex">
            <a href="#how" className="hover:text-ink">
              How it works
            </a>
            <a href="#break" className="hover:text-ink">
              Try to break it
            </a>
            <a href="#voice" className="hover:text-ink">
              Voice
            </a>
            <a href="/ops" className="hover:text-ink">
              Bank ops
            </a>
          </div>
          <LinkButton href="/board" size="md">
            Open live board
          </LinkButton>
        </div>
      </nav>

      {/* hero */}
      <header className="gutter">
        <div className="mx-auto grid max-w-[1240px] items-center gap-12 py-16 md:py-24 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-1 text-[13px] text-ink-2">
              <span className={cn("size-1.5 rounded-full", online ? "bg-allow" : "bg-muted")} />
              {online ? "Kernel online" : "Bank-side authorization kernel"}
            </p>
            <h1 className="mt-6 max-w-[14ch] text-[clamp(2.6rem,6vw,4.75rem)] font-semibold leading-[0.98] tracking-[-0.045em]">Margaret can be talked into anything. Her money can&apos;t.</h1>
            <p className="mt-6 max-w-[58ch] text-lg leading-relaxed text-ink-2">
              Margaret is a 72-year-old Claude persona, and this room is about to try to scam her. Whatever she agrees to, a payment only moves when deterministic rules, a human reviewer and a one-time certificate all agree.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <LinkButton href="#break" size="lg">
                Scam Margaret now
              </LinkButton>
              <LinkButton href="#how" size="lg" variant="secondary">
                See how it works
              </LinkButton>
            </div>
          </div>

          <div className="relative">
            <div className="vault relative overflow-hidden rounded-[28px] p-7 pb-0 shadow-[0_30px_60px_-30px_rgba(60,3,6,0.6)]">
              <p className="text-sm text-on-vault-muted">How the kernel answers</p>
              <ul className="mt-4 space-y-2.5">
                {[
                  { t: "HELD · H-01 H-02 H-04", n: "Grandchild-in-jail wire, $4,800" },
                  { t: "SETTLEMENT REFUSED · I2_FINGERPRINT", n: "Payee swapped after approval" },
                  { t: "SUBMITTED · A-01", n: "Bay Roofing, $8,000 ACH" },
                ].map((r) => (
                  <li key={r.t} className="rounded-xl bg-white/8 px-4 py-3 ring-1 ring-white/10">
                    <p className="code text-[15px] font-semibold text-white">{r.t}</p>
                    <p className="mt-0.5 text-[13px] text-on-vault-muted">{r.n}</p>
                  </li>
                ))}
              </ul>
              <div className="mt-6 flex items-end justify-between gap-4">
                <div className="pb-7">
                  <p className="text-[clamp(3rem,5vw,4rem)] font-semibold leading-none tracking-[-0.04em] text-white num" data-testid="hero-unauthorized">
                    {ev.data ? ev.data.unauthorized_releases : 0}
                  </p>
                  <p className="mt-2 max-w-[18ch] text-sm leading-snug text-on-vault-muted">
                    unauthorized releases{ev.data?.scam_total ? ` across ${ev.data.scam_total} scam scripts` : ""}
                  </p>
                </div>
                <Margaret mood="calm" shadow={false} className="-mb-2 w-44 shrink-0 sm:w-52" />
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* architecture */}
      <section id="how" className="gutter scroll-mt-16 border-t border-line bg-paper py-20">
        <div className="mx-auto max-w-[1240px]">
          <div className="grid gap-6 md:grid-cols-[1fr_1fr] md:items-end">
            <h2 className="max-w-[18ch] text-[clamp(2rem,3.6vw,3rem)] font-semibold leading-[1.02] tracking-[-0.035em]">The model proposes. The kernel disposes.</h2>
            <p className="max-w-[56ch] text-[17px] leading-relaxed text-ink-2">
              Start with five steps, then switch to the full system to see every service. Play a scenario and follow the payment: scams stop in crimson, real bills come out the other side.
            </p>
          </div>
          <div className="mt-10">
            <Architecture />
          </div>
        </div>
      </section>

      {/* break it */}
      <section id="break" className="gutter scroll-mt-16 bg-stone py-20">
        <div className="mx-auto max-w-[1240px]">
          <div className="grid gap-10 lg:grid-cols-[380px_1fr]">
            <div className="flex flex-col">
              <h2 className="text-[clamp(2rem,3.6vw,3rem)] font-semibold leading-[1.02] tracking-[-0.035em]">Try to break it.</h2>
              <p className="mt-4 text-[17px] leading-relaxed text-ink-2">Scan, pick a handle, and talk Margaret into a payment. Type or hold to talk. Your best attempt goes on the leaderboard.</p>
              <div className="mt-8 flex items-center gap-5 rounded-2xl border border-line bg-paper p-5">
                <QR value={joinUrl} size={132} />
                <div className="min-w-0">
                  <p className="text-sm text-muted">Room code</p>
                  <p className="code text-4xl font-semibold tracking-wider">{DEFAULT_ROOM}</p>
                  <a href={`/play?room=${DEFAULT_ROOM}`} className="mt-2 inline-block text-sm font-medium text-crimson underline-offset-4 hover:underline">
                    Or play in this browser
                  </a>
                </div>
              </div>
              <p className="mt-6 text-sm leading-relaxed text-muted">Bank staff get four harder attacks. They hit the live kernel and come back refused, with the invariant named.</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {ATTACKS.map((a) => (
                <AttackCard key={a.name} a={a} />
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* voice */}
      <section id="voice" className="gutter scroll-mt-16 border-t border-line bg-paper py-20">
        <div className="mx-auto max-w-[1240px]">
          <div className="grid gap-6 md:grid-cols-2 md:items-end">
            <h2 className="max-w-[16ch] text-[clamp(2rem,3.6vw,3rem)] font-semibold leading-[1.02] tracking-[-0.035em]">Talk to her. She talks back.</h2>
            <p className="max-w-[56ch] text-[17px] leading-relaxed text-ink-2">
              Cartesia handles both directions of the call. Voice makes the scam feel real. It earns no trust: a cloned voice saying &ldquo;it&apos;s me, Emily&rdquo; changes nothing in the kernel.
            </p>
          </div>
          <ol className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-line bg-line md:grid-cols-4">
            {[
              { h: "Hold to talk", p: "On your phone, hold the mic button and pitch your scam out loud.", who: "Your phone" },
              { h: "Speech to text", p: "The clip goes to Cartesia and comes back as a transcript you can edit before sending.", who: "Cartesia" },
              { h: "Margaret answers", p: "The Claude persona replies in character, remembering the whole room's conversation.", who: "Claude" },
              { h: "She says it out loud", p: "Cartesia speaks her reply on the projector and on your phone.", who: "Cartesia" },
            ].map((s, i) => (
              <li key={s.h} className="flex flex-col bg-paper p-6">
                <span className="flex size-8 items-center justify-center rounded-full bg-crimson text-sm font-semibold text-white">{i + 1}</span>
                <h3 className="mt-5 text-lg font-semibold tracking-tight">{s.h}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{s.p}</p>
                <p className="mt-auto pt-5 text-sm text-muted">{s.who}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* close */}
      <section className="gutter vault py-20">
        <div className="mx-auto grid max-w-[1240px] gap-12 lg:grid-cols-[1fr_1fr] lg:items-center">
          <div>
            <p className="text-on-vault-muted">If it happens to you</p>
            <ol className="mt-6 space-y-4">
              {RULES.map((r, i) => (
                <li key={r} className="flex gap-5 text-[clamp(1.6rem,3vw,2.4rem)] font-semibold leading-tight tracking-[-0.03em] text-white">
                  <span className="mt-1 flex size-9 shrink-0 items-center justify-center rounded-full bg-white/12 text-base">{i + 1}</span>
                  {r}
                </li>
              ))}
            </ol>
          </div>
          <div className="flex flex-col items-start gap-6 lg:items-end">
            <Margaret mood="happy" shadow={false} className="w-56" />
            <div className="flex flex-wrap gap-3">
              <LinkButton href="/board" variant="vault" size="lg">
                Live board
              </LinkButton>
              <LinkButton href={`/play?room=${DEFAULT_ROOM}`} variant="vault" size="lg">
                Play
              </LinkButton>
              <LinkButton href="/ops" variant="vault" size="lg">
                Bank ops
              </LinkButton>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function AttackCard({ a }: { a: (typeof ATTACKS)[number] }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ text: string; ok: boolean } | null>(null);
  const run = async (name: AttackName) => {
    setBusy(true);
    setResult(null);
    try {
      const r = await kernel.attack(name);
      setResult({ text: refusalText(r.invariant, r.text), ok: true });
    } catch (e) {
      const status = e instanceof KernelError ? e.status : 0;
      setResult({ text: status === 401 ? "Needs the operator token. Run it from the live board." : "The kernel isn't reachable from this screen. Run it from the live board.", ok: false });
    } finally {
      setBusy(false);
    }
  };
  return (
    <article className="flex flex-col rounded-2xl border border-line bg-paper p-6" data-testid={`home-attack-${a.name}`}>
      <h3 className="text-lg font-semibold tracking-tight">{a.label}</h3>
      <dl className="mt-3 space-y-2 text-[15px] leading-snug">
        <div>
          <dt className="inline font-medium text-ink">Tries: </dt>
          <dd className="inline text-ink-2">{a.tries}</dd>
        </div>
        <div>
          <dt className="inline font-medium text-ink">Fails because: </dt>
          <dd className="inline text-ink-2">{a.fails}</dd>
        </div>
      </dl>
      <div className="mt-auto pt-5">
        <div className={cn("min-h-12 rounded-xl px-3.5 py-2.5", result ? (result.ok ? "bg-rose" : "bg-stone") : "bg-stone")}>
          <p className={cn("code text-[13px] font-semibold", result ? (result.ok ? "refuse-in text-crimson" : "font-sans font-normal text-muted") : "text-muted")} data-testid="refusal">
            {result ? result.text : `Expected: ${a.expect}`}
          </p>
        </div>
        <Button variant="secondary" size="sm" className="mt-3 w-full" disabled={busy} onClick={() => run(a.name)}>
          {busy ? "Running against the kernel" : "Run against the kernel"}
        </Button>
      </div>
    </article>
  );
}
