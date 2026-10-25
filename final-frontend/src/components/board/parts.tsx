"use client";

import NumberFlow from "@number-flow/react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Margaret, MOOD_LABEL, type Mood } from "@/components/margaret/Margaret";
import { ATTACKS } from "@/components/shared/attacks";
import { ruleLabel } from "@/components/shared/rules";
import { Refusal, StatePill, Waveform, refusalText } from "@/components/shared/Status";
import { Button, Panel, PanelHead, Pill } from "@/components/ui";
import { MARGARET } from "@/lib/config";
import { kernel, KernelError } from "@/lib/kernel/rest";
import type { AttackName, AttackResult } from "@/lib/kernel/types";
import { audioSrc, STAGES, type LeaderboardRow } from "@/lib/room";
import { errorText } from "@/lib/useAsync";
import { cents, cn, shortHash } from "@/lib/utils";

export interface MargaretLive {
  text: string;
  audioUrl: string | null;
  persuaded: boolean;
  /** 0..100 */
  meter: number;
  seq: number;
}

export interface LivePayment {
  paymentId: string;
  state: string;
  fingerprint: string;
  ruleIds: string[];
  refusal: string | null;
  amountCents?: number;
  payee?: string;
  rail?: string;
  seq: number;
  /** ms epoch when this push arrived */
  at: number;
}

export interface LiveRefusal {
  text: string;
  invariant: string;
  title: string;
  steps: string[];
  ruleIds: string[];
  seq: number;
  at: number;
}

// ---------------------------------------------------------------- Margaret
export function MargaretStage({ live, mood, balanceCents, voiceMock }: { live: MargaretLive | null; mood: Mood; balanceCents: number; voiceMock: boolean }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const src = audioSrc(live?.audioUrl);

  // Autoplay new replies when the browser allows it; the play button is the fallback.
  useEffect(() => {
    if (!src || !audio.current) return;
    audio.current.src = src;
    audio.current
      .play()
      .then(() => {
        setPlaying(true);
        setBlocked(false);
      })
      .catch(() => {
        setPlaying(false);
        setBlocked(true);
      });
  }, [src, live?.seq]);

  const play = () => {
    if (!audio.current || !src) return;
    audio.current.currentTime = 0;
    audio.current
      .play()
      .then(() => {
        setPlaying(true);
        setBlocked(false);
      })
      .catch(() => setPlaying(false));
  };

  const meter = Math.max(0, Math.min(100, live?.meter ?? 0));

  return (
    <Panel className="flex min-h-0 flex-col overflow-hidden bg-stone" data-testid="margaret-card">
      <div className="flex items-start justify-between gap-4 px-6 pt-5">
        <div>
          <p className="text-[26px] font-semibold leading-none tracking-[-0.03em]">{MARGARET.fullName}</p>
          <p className="mt-1.5 text-[15px] text-muted">Age {MARGARET.age}, checking account</p>
        </div>
        <div className="text-right">
          <p className="text-[13px] text-muted">Balance</p>
          <p className="num text-[26px] font-semibold leading-none tracking-[-0.02em]" data-testid="balance">
            <NumberFlow value={balanceCents / 100} format={{ style: "currency", currency: "USD", maximumFractionDigits: 0 }} />
          </p>
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 items-end justify-center px-6">
        <Margaret mood={mood} className="h-full max-h-[340px] min-h-[160px] w-auto" />
        <Pill tone={mood === "happy" ? "allow" : mood === "angry" ? "refuse" : mood === "calm" ? "outline" : "hold"} className="absolute top-3 left-6 bg-paper/90 text-[13px]" data-testid="mood">
          {MOOD_LABEL[mood]}
        </Pill>
      </div>

      <div className="mx-4 mb-4 rounded-2xl bg-paper p-4 ring-1 ring-line">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[13px] text-muted">Margaret says</p>
          <div className="flex items-center gap-2 text-crimson">
            <Waveform playing={playing} />
            <span className="text-[12px] text-muted">{voiceMock ? "Voice (mock)" : "Cartesia voice"}</span>
          </div>
        </div>
        <AnimatePresence mode="wait">
          <motion.p
            key={live?.seq ?? 0}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className={cn("mt-2 line-clamp-4 min-h-[3.2em] text-[clamp(1.05rem,1.35vw,1.45rem)] leading-snug", live?.text ? "text-ink" : "text-muted")}
            data-testid="margaret-reply"
            title={live?.text}
          >
            {live?.text ? `“${live.text}”` : "Margaret is waiting for the first message."}
          </motion.p>
        </AnimatePresence>
        <div className="mt-3 flex items-center gap-3">
          <Button size="sm" variant={blocked ? "primary" : "secondary"} onClick={play} disabled={!src} data-testid="play-reply">
            {blocked ? "Play her voice" : playing ? "Play again" : "Replay"}
          </Button>
          <div className="min-w-0 flex-1" data-testid="persuaded-meter">
            <div className="flex items-baseline justify-between text-[12px] text-muted">
              <span>Persuaded</span>
              <span className="num font-medium text-ink">{meter}%</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-stone-2" role="meter" aria-valuenow={meter} aria-valuemin={0} aria-valuemax={100} aria-label="Persuaded meter">
              <motion.div className={cn("h-full rounded-full", meter >= 75 ? "bg-crimson" : "bg-hold")} animate={{ width: `${meter}%` }} transition={{ type: "spring", stiffness: 120, damping: 20 }} />
            </div>
          </div>
        </div>
        <audio ref={audio} onEnded={() => setPlaying(false)} onPause={() => setPlaying(false)} preload="none" />
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- where the money is
type Tone = "hold" | "allow" | "refuse" | "neutral";
const PIPE = [
  { id: "agreed", label: "Margaret agreed", zone: "ai" },
  { id: "policy", label: "Policy engine", zone: "core" },
  { id: "held", label: "Held for review", zone: "core" },
  { id: "eligible", label: "Reviewer attested", zone: "core" },
  { id: "cert", label: "Certificate checked", zone: "core" },
  { id: "bank", label: "Sent to bank", zone: "out" },
] as const;

function pipeState(payment: LivePayment | null, refused: boolean): { reached: number; tone: Tone; end: string | null } {
  if (refused) return { reached: 4, tone: "refuse", end: "Refused" };
  if (!payment) return { reached: -1, tone: "neutral", end: null };
  const s = payment.state.toUpperCase();
  if (s === "SUBMITTED") return { reached: 5, tone: "allow", end: null };
  if (s === "ELIGIBLE_TO_SUBMIT") return { reached: 3, tone: "allow", end: null };
  if (s === "HELD" || s === "PENDING_REVIEW") return { reached: 2, tone: "hold", end: null };
  if (s === "DENIED") return { reached: 1, tone: "refuse", end: "Denied" };
  if (s === "CANCELLED") return { reached: 2, tone: "neutral", end: "Cancelled" };
  if (payment.refusal) return { reached: 4, tone: "refuse", end: "Refused" };
  return { reached: 0, tone: "neutral", end: null };
}

export function MoneyPath({ payment, refused }: { payment: LivePayment | null; refused: boolean }) {
  const { reached, tone, end } = pipeState(payment, refused);
  const toneBg = tone === "allow" ? "bg-allow" : tone === "hold" ? "bg-hold" : tone === "refuse" ? "bg-crimson" : "bg-ink-2";
  return (
    <div className="flex items-stretch gap-0" data-testid="money-path" aria-label="Where the money is">
      {PIPE.map((p, i) => {
        const done = i <= reached;
        const current = i === reached;
        const core = p.zone === "core";
        return (
          <div key={p.id} className={cn("relative flex flex-1 flex-col items-center px-1 pt-1 pb-2", core && "bg-crimson/[0.06]", i === 1 && "rounded-l-xl", i === 4 && "rounded-r-xl")}>
            {i > 0 ? <span className={cn("absolute top-[19px] right-1/2 left-[-50%] h-[3px] rounded-full", i <= reached ? toneBg : "bg-line")} /> : null}
            <span
              className={cn(
                "relative z-10 mt-2 flex size-[22px] items-center justify-center rounded-full border-2 transition-colors",
                done ? `${toneBg} border-transparent` : "border-line-2 bg-paper",
                current && "ring-4 ring-crimson/15",
              )}
            >
              {done ? <span className="size-1.5 rounded-full bg-white" /> : null}
            </span>
            <span className={cn("mt-2 text-center text-[12.5px] leading-tight", done ? "font-medium text-ink" : "text-muted")}>
              {current && end ? <span className={tone === "refuse" ? "text-crimson" : "text-ink-2"}>{end}</span> : p.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- the kernel's answer
export function KernelDecision({ payment, refusal, showRefusal }: { payment: LivePayment | null; refusal: LiveRefusal | null; showRefusal: boolean }) {
  return (
    <section className="vault flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl" data-testid="live-payment">
      <div className="flex items-start justify-between gap-4 px-6 pt-5">
        <div>
          <h2 className="text-[15px] font-semibold text-white">Kernel decision</h2>
          <p className="mt-0.5 text-[13px] text-on-vault-muted">Rules, not models. Every answer names the rule that fired.</p>
        </div>
        {showRefusal ? <span className="rounded-full bg-white px-3.5 py-1 text-[13px] font-semibold text-crimson">Attack refused</span> : payment ? <StatePill state={payment.state} className="px-3.5 py-1 text-base" /> : null}
      </div>

      {payment && !showRefusal ? (
        <div className="mt-4 flex flex-wrap items-baseline gap-x-4 gap-y-1 px-6">
          {payment.amountCents ? <span className="num text-[clamp(1.8rem,2.6vw,2.8rem)] font-semibold leading-none tracking-[-0.03em] text-white">{cents(payment.amountCents)}</span> : null}
          {payment.payee ? <span className="text-[19px] text-on-vault">to {payment.payee}</span> : null}
          {payment.rail ? <span className="rounded-md bg-white/10 px-2 py-0.5 text-[13px] text-on-vault uppercase">{payment.rail}</span> : null}
          {payment.fingerprint ? (
            <span className="code text-[13px] text-on-vault-muted" title={payment.fingerprint}>
              fingerprint {shortHash(payment.fingerprint, 12)}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 flex min-h-0 flex-1 flex-col px-6 pb-6">
        {showRefusal && refusal ? (
          <div key={refusal.seq} className="refuse-in flex min-h-0 flex-1 flex-col justify-center rounded-xl bg-white p-5 text-ink">
            <p className="text-[14px] text-muted">Attack: {refusal.title}</p>
            <Refusal text={refusal.text} size="xl" className="mt-1" />
            {refusal.invariant || refusal.ruleIds.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2" data-testid="refusal-rules">
                {refusal.invariant ? <span className="code rounded-md border border-crimson/40 px-2.5 py-0.5 text-[14px] text-crimson">{refusal.invariant}</span> : null}
                {refusal.ruleIds.map((r) => (
                  <span key={r} className="code rounded-md bg-stone px-2.5 py-0.5 text-[14px]">
                    {r}
                  </span>
                ))}
              </div>
            ) : null}
            {refusal.steps.length > 0 ? (
              <ol className="mt-4 max-h-32 space-y-1 overflow-hidden text-[13px] leading-snug text-muted">
                {refusal.steps.map((s, i) => (
                  <li key={i} className="truncate" title={s}>
                    {i + 1}. {s}
                  </li>
                ))}
              </ol>
            ) : null}
          </div>
        ) : payment?.refusal ? (
          <div className="flex flex-1 items-center rounded-xl bg-white p-5">
            <Refusal text={refusalText(payment.refusal)} size="xl" animate />
          </div>
        ) : payment && payment.ruleIds.length > 0 ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <p className="text-[13px] text-on-vault-muted">Why</p>
            <ul className="mt-2 grid gap-2" data-testid="rule-ids">
              {payment.ruleIds.map((r) => (
                <li key={r} className="flex items-center gap-3 rounded-xl bg-white/8 px-4 py-2.5 ring-1 ring-white/10">
                  <span className="code text-[17px] font-semibold text-white">{r}</span>
                  {ruleLabel(r) ? <span className="text-[15px] text-on-vault">{ruleLabel(r)}</span> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="flex flex-1 flex-col justify-center">
            <p className="max-w-[28ch] text-[clamp(1.5rem,2.2vw,2.3rem)] font-semibold leading-tight tracking-[-0.03em] text-white">
              {payment ? "Decided. Nothing to flag." : "No payment yet. Margaret hasn't agreed to send anything."}
            </p>
            <p className="mt-3 text-[15px] text-on-vault-muted">The model proposes. The kernel disposes.</p>
          </div>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- attacks
export function AttackBar({ onResult, onError }: { onResult: (a: AttackName, r: AttackResult) => void; onError: (a: AttackName, msg: string, status: number) => void }) {
  const [busy, setBusy] = useState<AttackName | null>(null);
  const [shaking, setShaking] = useState<AttackName | null>(null);
  const run = async (name: AttackName) => {
    setBusy(name);
    try {
      const r = await kernel.attack(name);
      onResult(name, r);
      setShaking(name);
      setTimeout(() => setShaking(null), 500);
    } catch (e) {
      onError(name, errorText(e), e instanceof KernelError ? e.status : 0);
    } finally {
      setBusy(null);
    }
  };
  return (
    <Panel className="px-5 py-4" data-testid="attack-panel">
      <div className="flex items-center gap-5">
        <div className="w-[190px] shrink-0">
          <h2 className="text-[15px] font-semibold">Try to break the kernel</h2>
          <p className="mt-0.5 text-[13px] leading-snug text-muted">Each button hits the live kernel.</p>
        </div>
        <div className="grid flex-1 grid-cols-4 gap-3">
          {ATTACKS.map((a) => (
            <button
              key={a.name}
              disabled={busy !== null}
              onClick={() => run(a.name)}
              className={cn(
                "group flex flex-col items-start rounded-xl border border-line-2 bg-paper px-4 py-3 text-left transition-colors hover:border-crimson hover:bg-rose/40 disabled:opacity-60",
                shaking === a.name && "shake border-crimson",
              )}
              data-testid={`attack-${a.name}`}
            >
              <span className="text-[15px] font-semibold leading-tight">{busy === a.name ? "Running…" : a.label}</span>
              <span className="code mt-1 text-[12px] text-crimson">{a.invariant}</span>
            </button>
          ))}
        </div>
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- scores
export function Scoreboard({ unauthorized, legit }: { unauthorized: number; legit: number }) {
  return (
    <Panel className="grid grid-cols-2 divide-x divide-line" data-testid="scoreboard">
      <div className="px-5 py-4">
        <p className="text-[13px] text-muted">Unauthorized releases</p>
        <p className={cn("num mt-1 text-[52px] font-semibold leading-none tracking-[-0.04em]", unauthorized === 0 ? "text-ink" : "text-crimson")} data-testid="unauthorized-releases">
          <NumberFlow value={unauthorized} />
        </p>
      </div>
      <div className="px-5 py-4">
        <p className="text-[13px] text-muted">Real payments through</p>
        <p className="num mt-1 text-[52px] font-semibold leading-none tracking-[-0.04em] text-allow" data-testid="legit-completed">
          <NumberFlow value={legit} />
        </p>
      </div>
    </Panel>
  );
}

const STAGE_LABEL: Record<number, string> = Object.fromEntries([[0, "Not started"], ...STAGES.map((s) => [s.stage, s.label])]);

export function Leaderboard({ rows, roomMissing }: { rows: LeaderboardRow[]; roomMissing: boolean }) {
  const sorted = [...rows].sort((a, b) => b.bestStage - a.bestStage || b.attempts - a.attempts).slice(0, 7);
  return (
    <Panel className="flex min-h-0 flex-1 flex-col overflow-hidden" data-testid="leaderboard">
      <PanelHead title="Leaderboard" hint="Furthest anyone has pushed a payment. 100 would mean money left. Nobody has." />
      <div className="min-h-0 flex-1 overflow-hidden px-5 pb-4">
        {sorted.length === 0 ? (
          <p className="pt-2 text-[15px] text-muted">{roomMissing ? "Connecting to the room. Scan the code to join." : "No red-teamers yet. Scan the code to join."}</p>
        ) : (
          <ol className="space-y-2.5">
            <AnimatePresence initial={false}>
              {sorted.map((r, i) => (
                <motion.li layout key={r.player || `${r.handle}-${i}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="grid grid-cols-[22px_1fr_auto] items-center gap-3">
                  <span className="num text-[14px] text-muted">{i + 1}</span>
                  <div className="min-w-0">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-[17px] font-semibold">{r.handle || (r.player ? r.player.slice(0, 8) : "player")}</span>
                      <span className="shrink-0 text-[12px] text-muted">{STAGE_LABEL[r.bestStage]}</span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-stone-2">
                      <div className={cn("h-full rounded-full", r.bestStage >= 70 ? "bg-crimson" : "bg-hold")} style={{ width: `${r.bestStage}%` }} />
                    </div>
                  </div>
                  <span className="num w-12 text-right text-[13px] text-muted">{r.attempts} {r.attempts === 1 ? "try" : "tries"}</span>
                </motion.li>
              ))}
            </AnimatePresence>
          </ol>
        )}
      </div>
    </Panel>
  );
}
