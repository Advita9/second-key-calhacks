"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AttackPanel, ATTACKS } from "./AttackPanel";
import { BoardFooter } from "./BoardFooter";
import { Leaderboard } from "./Leaderboard";
import { LivePaymentCard, type LivePayment, type LiveRefusal } from "./LivePaymentCard";
import { MargaretCard, type MargaretLive } from "./MargaretCard";
import { Scoreboard } from "./Scoreboard";
import { useHealth } from "@/components/shared/Health";
import { refusalText } from "@/components/shared/Refusal";
import { MARGARET, roomFromSearch } from "@/lib/config";
import { adoptTokenFromUrl, isMockFlag, kernel, setOpsToken, useOpsToken } from "@/lib/kernel/rest";
import { Input } from "@/components/ui/input";
import { useAsync } from "@/lib/useAsync";
import type { AttackName, AttackResult, WsMessage } from "@/lib/kernel/types";
import { useKernelSocket } from "@/lib/kernel/ws";
import { useRoom } from "@/lib/useRoom";

const STAGE_METER: Record<number, number> = { 0: 0, 10: 15, 40: 55, 60: 75, 70: 85, 90: 95, 100: 100 };

export function BoardView() {
  const sp = useSearchParams();
  const roomCode = roomFromSearch(sp);
  useEffect(() => adoptTokenFromUrl(sp), [sp]);
  const opsToken = useOpsToken();
  const [needToken, setNeedToken] = useState(false);
  const health = useHealth();
  const room = useRoom(roomCode, "board");

  const [margaret, setMargaret] = useState<MargaretLive | null>(null);
  const [payment, setPayment] = useState<LivePayment | null>(null);
  const [refusal, setRefusal] = useState<LiveRefusal | null>(null);
  const [submittedCents, setSubmittedCents] = useState(0);
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
        const p = m as { payment_id?: string; state?: string; fingerprint?: string; reasons?: unknown; last_refusal?: string | null; amount_cents?: number; beneficiary?: { name?: string }; rail?: string };
        const s = next();
        setPayment({
          paymentId: p.payment_id ?? "",
          state: p.state ?? "PENDING_REVIEW",
          fingerprint: p.fingerprint ?? "",
          ruleIds: Array.isArray(p.reasons) ? p.reasons.filter((x): x is string => typeof x === "string") : [],
          refusal: p.last_refusal ?? null,
          amountCents: p.amount_cents,
          payee: p.beneficiary?.name,
          rail: p.rail,
          seq: s,
        });
        if (p.state === "SUBMITTED" && typeof p.amount_cents === "number") setSubmittedCents((c) => c + (p.amount_cents ?? 0));
      } else if (m.type === "attack") {
        const a = m as { name?: string; invariant?: string; text?: string };
        const def = ATTACKS.find((x) => x.name === a.name);
        // The REST response for a clicked attack carries steps and rule ids; the WS event is the
        // minimal {name, invariant} and only fills in when nobody on this board clicked.
        setRefusal((prev) => (prev && prev.title === (def?.label ?? a.name) ? prev : { title: def?.label ?? a.name ?? "Attack", invariant: a.invariant ?? "", text: refusalText(a.invariant, a.text), steps: [], ruleIds: [], seq: next() }));
      }
    },
    [next],
  );
  const ws = useKernelSocket({ room: roomCode, role: "board" }, onMessage);

  // Room snapshot drives the leaderboard, scoreboard and the last reply when the WS is quiet.
  const snap = room.snapshot;
  const lastReply = snap.replies[snap.replies.length - 1];
  const margaretLive: MargaretLive | null = useMemo(() => {
    if (margaret) return margaret;
    if (!lastReply) return null;
    const best = Math.max(0, ...snap.outcomes.map((o) => o.stage));
    return { text: lastReply.text, audioUrl: lastReply.audioUrl || null, persuaded: lastReply.persuaded, meter: lastReply.persuaded ? 100 : STAGE_METER[best] ?? 0, seq: 0 };
  }, [margaret, lastReply, snap.outcomes]);

  const lastOutcome = snap.outcomes[snap.outcomes.length - 1];
  const paymentLive: LivePayment | null = useMemo(() => {
    if (payment) return payment;
    if (!lastOutcome || !lastOutcome.paymentId) return null;
    return { paymentId: lastOutcome.paymentId, state: lastOutcome.decision, fingerprint: "", ruleIds: lastOutcome.ruleIds, refusal: lastOutcome.refusal || null, seq: 0 };
  }, [payment, lastOutcome]);

  const onAttack = (name: AttackName, r: AttackResult) => {
    const def = ATTACKS.find((x) => x.name === name);
    setRefusal({ title: def?.label ?? name, invariant: r.invariant, text: refusalText(r.invariant, r.text), steps: r.steps, ruleIds: r.rule_ids, seq: next() });
  };
  const onAttackError = (name: AttackName, msg: string, status: number) => {
    const def = ATTACKS.find((x) => x.name === name);
    if (status === 401) setNeedToken(true);
    const text = status === 401 ? "OPERATOR TOKEN REQUIRED" : status === 404 ? "ATTACK ROUTE NOT LIVE YET" : `KERNEL ERROR · ${msg}`;
    setRefusal({ title: def?.label ?? name, invariant: "", text, steps: [], ruleIds: [], seq: next() });
  };

  // Legitimate completed: the room scoreboard (bridge `record_legit_completed`) or, when that is
  // behind, the count of SUBMITTED payments on the kernel. Every SUBMITTED payment carried a valid
  // certificate; "unauthorized" is an attacker reaching stage 100 and stays room-scoped.
  const list = useAsync(() => kernel.payments(), [], 10000);
  const submittedOnKernel = useMemo(() => (list.data ?? []).filter((p) => p.state === "SUBMITTED").length, [list.data]);
  const unauthorized = snap.scoreboard?.unauthorizedReleases ?? 0;
  const legit = Math.max(snap.scoreboard?.legitCompleted ?? 0, submittedOnKernel);

  return (
    <main className="mx-auto flex h-screen w-[1920px] max-w-full flex-col gap-5 p-6" data-testid="board">
      <header className="flex items-baseline justify-between px-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          Second Key <span className="text-muted">Red-teamers vs the kernel</span>
        </h1>
        <p className="text-sm text-muted">
          Kernel WS: {ws.status}
          {ws.status === "reconnecting" ? ` (attempt ${ws.attempt})` : ""}
        </p>
      </header>
      <section className="grid min-h-0 flex-1 grid-cols-[1fr_1.35fr_1fr] gap-5 overflow-hidden">
        <MargaretCard live={margaretLive} balanceCents={MARGARET.balanceCents - submittedCents} voiceMock={isMockFlag(health.data, "tts")} />
        <LivePaymentCard payment={paymentLive} refusal={refusal} />
        <div className="flex min-h-0 flex-col gap-5">
          <Leaderboard rows={snap.leaderboard} roomMissing={room.status !== "open" && snap.room === null} />
          <Scoreboard unauthorized={unauthorized} legit={legit} />
        </div>
      </section>
      {needToken || room.status === "closed" ? (
        <div className="flex items-center gap-3 rounded-lg border border-accent/60 bg-panel px-4 py-2 text-sm" role="alert" data-testid="token-notice">
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
      <AttackPanel onResult={onAttack} onError={onAttackError} />
      <BoardFooter roomCode={roomCode} health={health.data} healthError={health.error} roomStatus={room.status} roomBackend={room.client.backend} />
    </main>
  );
}
