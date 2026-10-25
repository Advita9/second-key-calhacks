"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Logo } from "@/components/brand/Logo";
import { ProviderPills, useHealth } from "@/components/shared/Status";
import { Dot, Input, Pill } from "@/components/ui";
import { roomFromSearch } from "@/lib/config";
import { adoptTokenFromUrl, isDemoMode, kernel, setOpsToken, useOpsToken } from "@/lib/kernel/rest";
import type { Payment, WsMessage } from "@/lib/kernel/types";
import { useKernelSocket } from "@/lib/kernel/ws";
import { useAsync } from "@/lib/useAsync";
import { useRoom } from "@/lib/useRoom";
import { AuditList, CertificatesLog, certRows, HoldsQueue, LegitPayment, PaymentHistory, PolicyPanel, RoundControls, ScriptedAttack } from "./panels";

export function OpsView() {
  const sp = useSearchParams();
  const roomCode = roomFromSearch(sp);
  const health = useHealth();
  // Read-only room view: the leaderboard handles go with End round so the saved transcript can scrub them.
  const room = useRoom(roomCode, "board");
  const roomHandles = useMemo(() => room.snapshot.leaderboard.map((r) => r.handle).filter(Boolean), [room.snapshot.leaderboard]);
  const list = useAsync(() => kernel.payments(20), [], 5000);
  const audit = useAsync(() => kernel.audit(200), [], 5000);
  const ev = useAsync(() => kernel.evalResults(), [], 30000);
  const [livePayments, setLivePayments] = useState<Record<string, Payment>>({});
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => adoptTokenFromUrl(sp), [sp]);
  const storedToken = useOpsToken();
  const [opsToken, setToken] = useState("");
  useEffect(() => setToken(storedToken), [storedToken]);
  const onToken = (t: string) => {
    setToken(t);
    setOpsToken(t);
  };

  // Live payment pushes fill the queue even when GET /payments is not available.
  const onMessage = useCallback((m: WsMessage) => {
    if (m.type !== "payment") return;
    const p = m as { payment_id?: string; state?: string; fingerprint?: string; reasons?: unknown; last_refusal?: string | null; last_refusal_text?: string | null; amount_cents?: number; beneficiary?: { name?: string; account_ref?: string; is_new?: boolean }; rail?: string };
    if (!p.payment_id) return;
    const reasons = Array.isArray(p.reasons) ? p.reasons.filter((x): x is string => typeof x === "string") : [];
    setLivePayments((prev) => {
      const old = prev[p.payment_id!];
      return {
        ...prev,
        [p.payment_id!]: {
          id: p.payment_id!,
          state: p.state ?? old?.state ?? "PENDING_REVIEW",
          fingerprint: p.fingerprint ?? old?.fingerprint ?? "",
          amount_cents: p.amount_cents ?? old?.amount_cents,
          beneficiary: p.beneficiary ? { name: p.beneficiary.name ?? "", account_ref: p.beneficiary.account_ref ?? "", is_new: !!p.beneficiary.is_new } : old?.beneficiary,
          rail: p.rail ?? old?.rail,
          decision: reasons.length ? { outcome: p.state === "HELD" ? "HOLD" : (p.state ?? "HOLD"), rule_ids: reasons, signals: [] } : old?.decision,
          attestations: old?.attestations ?? [],
          certificates: old?.certificates ?? [],
          history: old?.history ?? [],
          last_refusal: p.last_refusal_text || p.last_refusal || old?.last_refusal || null,
          created_at: old?.created_at ?? new Date().toISOString(),
        },
      };
    });
  }, []);
  const ws = useKernelSocket({ room: roomCode, role: "ops" }, onMessage);

  // REST list wins for fields it has; live pushes override state.
  const payments = useMemo(() => {
    const byId = new Map<string, Payment>();
    for (const p of list.data ?? []) byId.set(p.id, p);
    for (const p of Object.values(livePayments)) {
      const base = byId.get(p.id);
      byId.set(p.id, base ? { ...base, state: p.state, last_refusal: p.last_refusal ?? base.last_refusal } : p);
    }
    return [...byId.values()];
  }, [list.data, livePayments]);

  const onChanged = (p: Payment) => {
    setLivePayments((prev) => ({ ...prev, [p.id]: p }));
    list.reload();
    audit.reload();
  };

  const liveHits = useMemo(() => {
    const h: Record<string, number> = {};
    for (const p of payments) for (const r of p.decision?.rule_ids ?? []) h[r] = (h[r] ?? 0) + 1;
    return h;
  }, [payments]);

  const certs = useMemo(() => certRows(payments, audit.data ?? []), [payments, audit.data]);
  const kernelUp = !health.error && !!health.data;

  return (
    <main className="min-h-screen bg-stone" data-testid="ops">
      <header className="gutter sticky top-0 z-20 border-b border-line bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-4 py-3">
          <div className="flex items-center gap-5">
            <a href="/" aria-label="Second Key home">
              <Logo sub="Bank operations" />
            </a>
            <Pill tone="outline" className="code">
              room {roomCode}
            </Pill>
            <span className="flex items-center gap-2 text-[13px] text-muted">
              <Dot tone={kernelUp ? "allow" : "refuse"} pulse={kernelUp} />
              {health.loading ? "Kernel: connecting" : kernelUp ? `Kernel online, policy ${health.data?.policy_version}` : "Kernel unreachable (fail closed)"}
            </span>
            <span className="text-[13px] text-muted">Feed: {ws.status}</span>
          </div>
          <label className="flex items-center gap-2 text-[13px] text-muted">
            Operator token
            <Input type="password" value={opsToken} onChange={(e) => onToken(e.target.value)} placeholder="OPS_TOKEN" className="h-9 w-52 text-sm" autoComplete="off" data-testid="ops-token" />
          </label>
        </div>
        <div className="mx-auto max-w-[1440px] pb-3">
          <ProviderPills mode={health.data?.mode} />
        </div>
      </header>

      <div className="gutter mx-auto grid max-w-[1440px] gap-5 py-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <HoldsQueue payments={payments} loading={list.loading} error={list.error} notFound={list.notFound} onChanged={onChanged} onSelect={setSelected} />
          <PaymentHistory paymentId={selected} options={payments} onSelect={(id) => setSelected(id || null)} />
          <AuditList events={audit.data ?? []} loading={audit.loading} error={audit.error} notFound={audit.notFound} demo={isDemoMode(health.data)} onChanged={audit.reload} />
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          <div className="rounded-2xl vault p-5">
            <h2 className="text-[15px] font-semibold text-white">Demo beats</h2>
            <p className="mt-0.5 text-[13px] text-on-vault-muted">Run these from here; the board shows the result.</p>
          </div>
          <ScriptedAttack room={roomCode} />
          <LegitPayment room={roomCode} />
          <RoundControls room={roomCode} handles={roomHandles} />
          <PolicyPanel policyVersion={health.data?.policy_version ?? "v1"} liveHits={liveHits} ev={ev} />
          <CertificatesLog rows={certs} />
        </div>
      </div>
    </main>
  );
}
