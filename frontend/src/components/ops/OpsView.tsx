"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AuditList } from "./AuditList";
import { CertificatesLog, certRows } from "./CertificatesLog";
import { HoldsQueue } from "./HoldsQueue";
import { PaymentHistory } from "./PaymentHistory";
import { PolicyPanel } from "./PolicyPanel";
import { ScriptedAttack } from "./ScriptedAttack";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { KernelStatus, MockBadges, useHealth } from "@/components/shared/Health";
import { roomFromSearch } from "@/lib/config";
import { adoptTokenFromUrl, isDemoMode, kernel, setOpsToken, useOpsToken } from "@/lib/kernel/rest";
import type { Payment, WsMessage } from "@/lib/kernel/types";
import { useKernelSocket } from "@/lib/kernel/ws";
import { useAsync } from "@/lib/useAsync";

export function OpsView() {
  const sp = useSearchParams();
  const roomCode = roomFromSearch(sp);
  const health = useHealth();
  const list = useAsync(() => kernel.payments(20), [], 5000);
  const audit = useAsync(() => kernel.audit(200), [], 5000);
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
    const p = m as { payment_id?: string; state?: string; fingerprint?: string; reasons?: unknown; last_refusal?: string | null; amount_cents?: number; beneficiary?: { name?: string; account_ref?: string; is_new?: boolean }; rail?: string };
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
          decision: { outcome: p.state === "DENIED" ? "DENY" : p.state === "HELD" ? "HOLD" : old?.decision?.outcome ?? "", rule_ids: reasons.length ? reasons : old?.decision?.rule_ids ?? [], signals: [] },
          attestations: old?.attestations ?? [],
          certificates: old?.certificates ?? [],
          history: old?.history ?? [],
          created_at: old?.created_at ?? new Date().toISOString(),
          last_refusal: p.last_refusal ?? old?.last_refusal ?? null,
        },
      };
    });
  }, []);
  const ws = useKernelSocket({ room: roomCode, role: "ops" }, onMessage);

  const payments = useMemo(() => {
    const byId: Record<string, Payment> = { ...livePayments };
    for (const p of list.data ?? []) byId[p.id] = { ...(byId[p.id] ?? {}), ...p };
    return Object.values(byId).sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  }, [list.data, livePayments]);

  const onChanged = (p: Payment) => {
    setLivePayments((prev) => ({ ...prev, [p.id]: p }));
    list.reload();
    audit.reload();
  };

  const certs = useMemo(() => certRows(payments, audit.data ?? []), [payments, audit.data]);
  // Live rule hits: one per payment per rule, from the seeded list (GET /payments) merged with WS pushes.
  const liveHits = useMemo(() => {
    const n: Record<string, number> = {};
    for (const p of payments) for (const r of p.decision?.rule_ids ?? []) n[r] = (n[r] ?? 0) + 1;
    return n;
  }, [payments]);

  return (
    <main className="mx-auto flex min-h-screen max-w-[1440px] flex-col gap-5 p-6" data-testid="ops">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-muted">Second Key</p>
          <h1 className="text-2xl font-semibold tracking-tight">Bank operator</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <KernelStatus error={health.error} loading={health.loading} />
          <Badge variant="outline">WS {ws.status}</Badge>
          <Badge variant="outline">Policy {health.data?.policy_version ?? "v1"}</Badge>
          {isDemoMode(health.data) ? <Badge variant="accent">Demo mode</Badge> : null}
          <MockBadges mode={health.data?.mode} />
          <label className="flex items-center gap-2 text-xs text-muted">
            Ops token
            <Input type="password" value={opsToken} onChange={(e) => onToken(e.target.value)} placeholder="only if OPS_TOKEN is set" className="h-8 w-48 text-xs" autoComplete="off" data-testid="ops-token" />
          </label>
        </div>
      </header>
      <ScriptedAttack room={roomCode} />
      <HoldsQueue payments={payments} loading={list.loading} error={list.error} notFound={list.notFound} onChanged={onChanged} onSelect={setSelected} />
      <div className="grid gap-5 lg:grid-cols-2">
        <PolicyPanel policyVersion={health.data?.policy_version ?? "v1"} liveHits={liveHits} />
        <CertificatesLog rows={certs} />
      </div>
      <AuditList events={audit.data ?? []} loading={audit.loading} error={audit.error} notFound={audit.notFound} demo={isDemoMode(health.data)} onChanged={audit.reload} />
      <PaymentHistory paymentId={selected} options={payments} onSelect={(id) => setSelected(id || null)} />
    </main>
  );
}
