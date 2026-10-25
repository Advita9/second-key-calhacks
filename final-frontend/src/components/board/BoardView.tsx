"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Logo } from "@/components/brand/Logo";
import { moodFor } from "@/components/margaret/Margaret";
import { ATTACKS } from "@/components/shared/attacks";
import { QR, useJoinUrl } from "@/components/shared/JoinQR";
import { ProviderPills, refusalText, useHealth } from "@/components/shared/Status";
import { Button, Dot, Input, Panel } from "@/components/ui";
import { MARGARET, roomFromSearch } from "@/lib/config";
import { adoptTokenFromUrl, isMockFlag, kernel, setOpsToken, useOpsToken } from "@/lib/kernel/rest";
import type { AttackName, AttackResult, Payment, WsMessage, WsRound } from "@/lib/kernel/types";
import { useKernelSocket } from "@/lib/kernel/ws";
import { useAsync } from "@/lib/useAsync";
import { useRoom } from "@/lib/useRoom";
import { Debrief } from "./Debrief";
import { AttackBar, KernelDecision, Leaderboard, MargaretStage, MoneyPath, Scoreboard, type LivePayment, type LiveRefusal, type MargaretLive } from "./parts";

const STAGE_METER: Record<number, number> = { 0: 0, 10: 15, 40: 55, 60: 75, 70: 85, 90: 95, 100: 100 };
const LIVE_STATES = new Set(["HELD", "ELIGIBLE_TO_SUBMIT", "SUBMITTED"]);
const FEED_LABEL: Record<string, string> = { open: "live", connecting: "connecting", reconnecting: "reconnecting", closed: "closed" };

/** Attack-panel payments: the kernel says `origin: "attack"`; older kernels only prefix the conversation id. */
function isAttackPayment(p: Payment): boolean {
  return p.origin === "attack" || (!p.origin && (p.conversation_id ?? "").startsWith("attack:"));
}

/** A room payment (`room_<CODE>`) or a legit beat (`legit:<CODE>:...`) for a different room never takes
 *  this board's live card, count or balance. */
function belongsToOtherRoom(conversationId: string | undefined, roomCode: string): boolean {
  const c = conversationId ?? "";
  const m = /^room_(.+)$/.exec(c) ?? /^legit:([^:]+):/.exec(c);
  return !!m && (m[1] ?? "").toUpperCase() !== roomCode.toUpperCase();
}

export function BoardView() {
  const sp = useSearchParams();
  const roomCode = roomFromSearch(sp);
  useEffect(() => adoptTokenFromUrl(sp), [sp]);
  const opsToken = useOpsToken();
  const [needToken, setNeedToken] = useState(false);
  const health = useHealth();
  const room = useRoom(roomCode, "board");
  const joinUrl = useJoinUrl(roomCode);
  const list = useAsync(() => kernel.payments(20), [], 10000);

  const [debrief, setDebrief] = useState<boolean | null>(null);
  const [roundTop, setRoundTop] = useState<{ rule_id: string; holds: number }[] | null>(null);
  const roomStatus = room.snapshot.room?.status;
  const showDebrief = debrief ?? (sp?.get("debrief") === "1" || roomStatus === "debrief");
  useEffect(() => {
    if (roomStatus === "debrief") setDebrief(null);
  }, [roomStatus]);

  const [margaret, setMargaret] = useState<MargaretLive | null>(null);
  const [payment, setPayment] = useState<LivePayment | null>(null);
  const [refusal, setRefusal] = useState<LiveRefusal | null>(null);
  const seq = useRef(0);
  const next = useCallback(() => {
    seq.current += 1;
    return seq.current;
  }, []);

  const onMessage = useCallback(
    (m: WsMessage) => {
      if (m.type === "margaret") {
        const mm = m as { text?: string; audio_url?: string | null; persuaded?: boolean; stage?: number };
        setMargaret((prev) => ({
          text: mm.text ?? "",
          audioUrl: mm.audio_url ?? null,
          persuaded: !!mm.persuaded,
          meter: mm.persuaded ? 100 : Math.max(STAGE_METER[mm.stage ?? 0] ?? 0, Math.min(45, (prev?.meter ?? 0) + 8)),
          seq: next(),
        }));
      } else if (m.type === "payment") {
        const p = m as { payment_id?: string; state?: string; fingerprint?: string; reasons?: unknown; last_refusal?: string | null; last_refusal_text?: string | null; amount_cents?: number; beneficiary?: { name?: string }; rail?: string; origin?: string; conversation_id?: string };
        // Attack-panel payments never take the live card: the decision panel already shows the attack.
        if (p.origin === "attack" || (!p.origin && (p.conversation_id ?? "").startsWith("attack:"))) return;
        if (belongsToOtherRoom(p.conversation_id, roomCode)) return;
        const s = next();
        setPayment({
          paymentId: p.payment_id ?? "",
          state: p.state ?? "PENDING_REVIEW",
          fingerprint: p.fingerprint ?? "",
          ruleIds: Array.isArray(p.reasons) ? p.reasons.filter((x): x is string => typeof x === "string") : [],
          refusal: p.last_refusal_text || p.last_refusal || null,
          amountCents: p.amount_cents,
          payee: p.beneficiary?.name,
          rail: p.rail,
          seq: s,
          at: Date.now(),
        });
      } else if (m.type === "room_reset") {
        // Operator pressed Reset Margaret: fresh conversation, the open payment was cancelled.
        setMargaret({ text: "", audioUrl: null, persuaded: false, meter: 0, seq: next() });
        setPayment(null);
        setRefusal(null);
      } else if (m.type === "round") {
        const r = m as WsRound;
        if (r.status === "debrief" && Array.isArray(r.top_rules)) setRoundTop(r.top_rules.filter((t) => t && typeof t.rule_id === "string" && typeof t.holds === "number"));
        setDebrief(r.status === "debrief");
      } else if (m.type === "attack") {
        const a = m as { name?: string; invariant?: string; text?: string };
        const def = ATTACKS.find((x) => x.name === a.name);
        // The REST response for a clicked attack carries steps and rule ids; the WS event only fills in
        // when nobody on this board clicked.
        setRefusal((prev) => (prev && prev.title === (def?.label ?? a.name) ? prev : { title: def?.label ?? a.name ?? "Attack", invariant: a.invariant ?? "", text: refusalText(a.invariant, a.text), steps: [], ruleIds: [], seq: next(), at: Date.now() }));
      }
    },
    [next, roomCode],
  );
  const ws = useKernelSocket({ room: roomCode, role: "board" }, onMessage);

  const snap = room.snapshot;
  const lastReply = snap.replies[snap.replies.length - 1];
  const margaretLive: MargaretLive | null = useMemo(() => {
    if (margaret) return margaret;
    if (!lastReply) return null;
    const best = Math.max(0, ...snap.outcomes.map((o) => o.stage));
    return { text: lastReply.text, audioUrl: lastReply.audioUrl || null, persuaded: lastReply.persuaded, meter: lastReply.persuaded ? 100 : (STAGE_METER[best] ?? 0), seq: 0 };
  }, [margaret, lastReply, snap.outcomes]);

  // Live card: the latest WS push wins; on a fresh load seed from the newest in-flight kernel payment.
  const newest = useMemo(() => {
    const real = (list.data ?? []).filter((p) => !isAttackPayment(p) && !belongsToOtherRoom(p.conversation_id, roomCode));
    return real.find((p) => LIVE_STATES.has(p.state)) ?? real[0];
  }, [list.data, roomCode]);
  const paymentLive: LivePayment | null = useMemo(() => {
    if (payment) return payment;
    if (!newest) return null;
    return {
      paymentId: newest.id,
      state: newest.state,
      fingerprint: newest.fingerprint,
      ruleIds: newest.decision?.rule_ids ?? [],
      refusal: newest.last_refusal ?? null,
      amountCents: newest.amount_cents,
      payee: newest.beneficiary?.name,
      rail: newest.rail,
      seq: 0,
      at: 0,
    };
  }, [payment, newest]);

  // An attack result stays until the next attack, or a newer payment that carries its own refusal,
  // or a newer payment push that lands well after it (a push right after the attack is the attack's own
  // state change on a cold kernel and must not hide the refusal).
  const showRefusal =
    !!refusal && (!paymentLive || refusal.seq >= paymentLive.seq || (!paymentLive.refusal && paymentLive.at - refusal.at < 3000));

  // Margaret's face follows whichever happened last: her own reply, or the kernel's answer.
  const mood = useMemo(() => {
    const mSeq = margaretLive?.seq ?? 0;
    const pSeq = Math.max(paymentLive?.seq ?? 0, showRefusal ? (refusal?.seq ?? 0) : 0);
    const kernelLast = (paymentLive || showRefusal) && (pSeq > mSeq || (pSeq === 0 && mSeq === 0 && !!paymentLive));
    if (kernelLast) return moodFor({ state: paymentLive?.state, refused: showRefusal || !!paymentLive?.refusal });
    return moodFor({ meter: margaretLive?.meter, persuaded: margaretLive?.persuaded });
  }, [margaretLive, paymentLive, showRefusal, refusal]);

  const onAttack = (name: AttackName, r: AttackResult) => {
    const def = ATTACKS.find((x) => x.name === name);
    setRefusal({ title: def?.label ?? name, invariant: r.invariant, text: refusalText(r.invariant, r.text), steps: r.steps, ruleIds: r.rule_ids, seq: next(), at: Date.now() });
  };
  const onAttackError = (name: AttackName, msg: string, status: number) => {
    const def = ATTACKS.find((x) => x.name === name);
    if (status === 401) setNeedToken(true);
    // Judge-safe text only. The raw message stays in the console for the operator.
    const text = status === 401 ? "OPERATOR TOKEN REQUIRED" : status === 404 ? "This attack is switched off on this kernel." : "Kernel did not answer. Nothing was sent.";
    if (status !== 401) console.warn(`attack ${name} failed (${status || "network"}): ${msg}`);
    setRefusal({ title: def?.label ?? name, invariant: "", text, steps: [], ruleIds: [], seq: next(), at: Date.now() });
  };

  // Legitimate completed: the room scoreboard or, when that is behind, SUBMITTED payments on the kernel.
  const legitSubmitted = useMemo(
    () => (list.data ?? []).filter((p) => p.state === "SUBMITTED" && !isAttackPayment(p) && !belongsToOtherRoom(p.conversation_id, roomCode)),
    [list.data, roomCode],
  );
  const unauthorized = snap.scoreboard?.unauthorizedReleases ?? 0;
  const legit = Math.max(snap.scoreboard?.legitCompleted ?? 0, legitSubmitted.length);
  const spent = useMemo(() => legitSubmitted.reduce((a, p) => a + (p.amount_cents ?? 0), 0), [legitSubmitted]);
  const players = snap.leaderboard.length || snap.players.length;
  const feed = FEED_LABEL[ws.status] ?? ws.status;

  return (
    <main className="relative mx-auto flex h-screen min-h-[760px] w-full max-w-[1920px] flex-col gap-4 overflow-hidden bg-paper p-5" data-testid="board">
      {showDebrief ? <Debrief outcomes={snap.outcomes} kernelTopRules={roundTop} onClose={() => setDebrief(false)} /> : null}

      <header className="flex items-center justify-between gap-6">
        <div className="flex items-center gap-6">
          <a href="/" aria-label="Second Key home">
            <Logo sub="Red-teamers vs the kernel" />
          </a>
          <ProviderPills mode={health.data?.mode} className="hidden xl:flex" />
        </div>
        <div className="flex items-center gap-3">
          {health.error ? (
            <span className="rounded-full bg-rose px-3 py-1 text-[13px] font-medium text-crimson" data-testid="kernel-offline">
              Kernel offline. Nothing is sent.
            </span>
          ) : null}
          <span className="flex items-center gap-2 text-[13px] text-muted" data-testid="kernel-feed">
            <Dot tone={ws.status === "open" ? "allow" : "hold"} pulse={ws.status === "open"} />
            Kernel feed: {feed}
          </span>
          <span className="flex items-center gap-2 text-[13px] text-muted" data-testid="room-backend">
            <Dot tone={room.status === "open" ? "allow" : "muted"} />
            Room {roomCode}: {room.status === "open" ? `${players} ${players === 1 ? "player" : "players"}` : room.status}
            {room.client.backend === "memory" ? <span className="text-hold"> (memory)</span> : null}
          </span>
          <Button variant="secondary" size="sm" onClick={() => setDebrief(!showDebrief)} data-testid="debrief-toggle">
            {showDebrief ? "Hide debrief" : "Debrief"}
          </Button>
        </div>
      </header>

      <section className="grid min-h-0 flex-1 grid-cols-[minmax(340px,0.95fr)_minmax(0,1.5fr)_minmax(320px,0.9fr)] gap-4">
        <MargaretStage live={margaretLive} mood={mood} balanceCents={MARGARET.balanceCents - spent} voiceMock={isMockFlag(health.data, "tts")} />

        <div className="flex min-h-0 flex-col gap-4">
          <Panel className="px-5 pt-4 pb-2">
            <div className="flex items-baseline justify-between">
              <h2 className="text-[15px] font-semibold">Where the money is</h2>
              <p className="text-[13px] text-muted">Shaded steps run inside the kernel</p>
            </div>
            <div className="mt-2">
              <MoneyPath payment={paymentLive} refused={showRefusal && /REFUSED/.test(refusal?.text ?? "")} />
            </div>
          </Panel>
          <KernelDecision payment={paymentLive} refusal={refusal} showRefusal={showRefusal} />
        </div>

        <div className="flex min-h-0 flex-col gap-4">
          <Panel className="flex items-center gap-4 p-4" data-testid="board-footer">
            <QR value={joinUrl} size={112} />
            <div className="min-w-0">
              <p className="text-[19px] font-semibold leading-tight tracking-[-0.02em]">Scan to scam Margaret</p>
              <p className="mt-1 text-[13px] leading-snug text-muted">Type or hold to talk. Get a payment released. Nobody has yet.</p>
              <p className="code mt-2 text-[28px] font-semibold leading-none tracking-wider" data-testid="room-code">
                {roomCode}
              </p>
            </div>
          </Panel>
          <Scoreboard unauthorized={unauthorized} legit={legit} />
          <Leaderboard rows={snap.leaderboard} roomMissing={room.status !== "open" && snap.room === null} />
        </div>
      </section>

      {needToken || list.status === 401 || room.status === "closed" ? (
        <div className="flex items-center gap-3 rounded-xl border border-hold/40 bg-hold-soft px-4 py-2 text-sm text-ink" role="alert" data-testid="token-notice">
          <span>Operator token missing or wrong. This kernel runs with OPS_TOKEN set. Paste it here or open the board with ?token=.</span>
          <Input
            type="password"
            defaultValue={opsToken}
            placeholder="OPS_TOKEN"
            className="h-8 w-56 text-xs"
            autoComplete="off"
            data-testid="board-token"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setOpsToken((e.target as HTMLInputElement).value);
                setNeedToken(false);
              }
            }}
            onBlur={(e) => {
              setOpsToken(e.target.value);
              if (e.target.value.trim()) setNeedToken(false);
            }}
          />
        </div>
      ) : null}

      <AttackBar onResult={onAttack} onError={onAttackError} />
    </main>
  );
}
