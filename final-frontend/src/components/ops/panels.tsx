"use client";

import { useEffect, useState } from "react";
import { ruleLabel } from "@/components/shared/rules";
import { Empty, ErrorText, Loading, Refusal, StatePill, refusalText } from "@/components/shared/Status";
import { Button, Panel, PanelHead, Pill } from "@/components/ui";
import { OPERATOR_ID } from "@/lib/config";
import { kernel, KernelError } from "@/lib/kernel/rest";
import type { AuditEvent, AuditVerify, EndRound, EvalResults, LegitPayment as LegitResult, Payment, ScriptedAttack as ScriptedResult } from "@/lib/kernel/types";
import { errorText, useAsync, type AsyncState } from "@/lib/useAsync";
import { ago, cents, cn, shortHash } from "@/lib/utils";

// ---------------------------------------------------------------- holds
export function HoldsQueue({ payments, loading, error, notFound, onChanged, onSelect }: { payments: Payment[]; loading: boolean; error: string | null; notFound: boolean; onChanged: (p: Payment) => void; onSelect: (id: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const held = payments.filter((p) => p.state === "HELD" || p.state === "PENDING_REVIEW");

  const act = async (p: Payment, kind: "approve" | "cancel") => {
    setBusy(p.id);
    setRowError((e) => ({ ...e, [p.id]: "" }));
    try {
      const next =
        kind === "approve"
          ? await kernel.attest(p.id, { actor_id: OPERATOR_ID, capability: "BANK_REVIEW", note: "Reviewed by operator" })
          : await kernel.cancel(p.id, { actor_id: OPERATOR_ID, note: "Cancelled by operator" });
      onChanged({ ...p, ...next, id: next.id || p.id });
    } catch (e) {
      const msg = e instanceof KernelError && e.refusal ? e.refusal.text || `REFUSED · ${e.refusal.invariant}` : errorText(e);
      setRowError((er) => ({ ...er, [p.id]: msg }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel data-testid="holds-queue">
      <PanelHead
        title={`Holds queue${held.length ? ` (${held.length})` : ""}`}
        hint="Payments waiting on BANK_REVIEW. Approve lifts a hold to eligible; it never releases money by itself. Cancel voids every attestation and certificate."
      />
      <div className="px-5 pb-5">
        {loading && payments.length === 0 ? (
          <Loading text="Loading payments" />
        ) : error && payments.length === 0 ? (
          <ErrorText text={notFound ? "Payment list route not live yet. Holds will appear here from the live feed." : `Kernel: ${error}`} />
        ) : held.length === 0 ? (
          <Empty text="No holds. Nothing is waiting on review." />
        ) : (
          <ul className="divide-y divide-line rounded-xl border border-line">
            {held.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3" data-testid="hold-row">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-3">
                    <span className="num text-[17px] font-semibold">{cents(p.amount_cents)}</span>
                    <span className="text-[15px]">to {p.beneficiary?.name || "unknown"}</span>
                    {p.beneficiary?.is_new ? <Pill tone="hold">new payee</Pill> : null}
                    {p.rail ? <span className="text-[13px] text-muted uppercase">{p.rail}</span> : null}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <button className="code text-[12px] text-muted underline-offset-4 hover:underline" onClick={() => onSelect(p.id)}>
                      {p.id.slice(0, 12)}
                    </button>
                    <span className="text-[12px] text-muted">{ago(p.created_at)}</span>
                    {(p.decision?.rule_ids ?? []).map((r) => (
                      <span key={r} className="code rounded bg-stone px-1.5 py-0.5 text-[11.5px]" title={ruleLabel(r) ?? r}>
                        {r}
                      </span>
                    ))}
                  </div>
                  {rowError[p.id] ? <p className="code mt-1.5 text-[12.5px] text-crimson">{rowError[p.id]}</p> : null}
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button size="sm" onClick={() => act(p, "approve")} disabled={busy === p.id} data-testid="approve-button">
                    Approve as BANK_REVIEW
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => act(p, "cancel")} disabled={busy === p.id} data-testid="cancel-button">
                    Cancel
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- history
export function PaymentHistory({ paymentId, options, onSelect }: { paymentId: string | null; options: Payment[]; onSelect: (id: string) => void }) {
  const q = useAsync(() => (paymentId ? kernel.payment(paymentId) : Promise.resolve(null)), [paymentId]);
  const p = q.data;
  return (
    <Panel data-testid="payment-history">
      <PanelHead
        title="Payment history"
        hint="Replay every transition, attestation and certificate on one payment."
        right={
          <select className="h-9 max-w-[260px] rounded-lg border border-line-2 bg-paper px-2 font-mono text-[12.5px]" value={paymentId ?? ""} onChange={(e) => onSelect(e.target.value)} aria-label="Select payment" data-testid="payment-select">
            <option value="">Select payment</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.id.slice(0, 12)} {o.state} {cents(o.amount_cents)}
              </option>
            ))}
          </select>
        }
      />
      <div className="px-5 pb-5">
        {!paymentId ? (
          <Empty text="Pick a payment to replay its timeline." />
        ) : q.loading ? (
          <Loading text="Loading payment" />
        ) : q.error ? (
          <ErrorText text={q.error} />
        ) : !p ? (
          <Empty text="No record." />
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <StatePill state={p.state} />
              <span className="num font-semibold">{cents(p.amount_cents)}</span>
              <span className="text-muted">to {p.beneficiary?.name || "unknown"}</span>
              <span className="code text-muted">fp {shortHash(p.fingerprint, 12)}</span>
              {p.decision ? (
                <span className="code text-xs">
                  {p.decision.outcome} {p.decision.rule_ids.join(" ")}
                </span>
              ) : null}
            </div>
            {p.last_refusal ? <Refusal text={refusalText(p.last_refusal)} size="sm" /> : null}
            {p.history.length === 0 ? (
              <Empty text="No history recorded." />
            ) : (
              <ol className="relative ml-2 border-l border-line pl-5">
                {p.history.map((h, i) => (
                  <li key={i} className="relative pb-3 last:pb-0">
                    <span className="absolute top-1.5 -left-[25px] size-2.5 rounded-full border-2 border-paper bg-crimson" />
                    <p className="text-[14px]">
                      <span className="font-medium">{h.kind.replace(/_/g, " ")}</span>
                      {h.from || h.to ? (
                        <span className="code ml-2 text-[12px] text-muted">
                          {h.from ? `${h.from} → ` : ""}
                          {h.to}
                        </span>
                      ) : null}
                    </p>
                    <p className="text-[12.5px] text-muted">
                      {h.actor ? `${h.actor} ` : ""}
                      {h.ts ? new Date(h.ts).toLocaleTimeString() : ""}
                      {h.text ? ` ${h.text}` : ""}
                    </p>
                  </li>
                ))}
              </ol>
            )}
            {p.attestations.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {p.attestations.map((a, i) => (
                  <Pill key={i} tone={a.valid ? "allow" : "neutral"} className="code">
                    {a.capability} by {a.actor_id}
                    {a.valid ? "" : " (void)"}
                  </Pill>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- audit
export function AuditList({ events, loading, error, notFound, demo, onChanged }: { events: AuditEvent[]; loading: boolean; error: string | null; notFound: boolean; demo: boolean; onChanged: () => void }) {
  const [verify, setVerify] = useState<AuditVerify | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"verify" | "tamper" | null>(null);

  const runVerify = async () => {
    setBusy("verify");
    setVerifyError(null);
    try {
      setVerify(await kernel.verify());
    } catch (e) {
      setVerify(null);
      setVerifyError(errorText(e));
    } finally {
      setBusy(null);
    }
  };
  const runTamper = async () => {
    setBusy("tamper");
    setVerifyError(null);
    try {
      await kernel.tamper();
      onChanged();
      setVerify(null);
    } catch (e) {
      setVerifyError(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  const verdict = verify ? (verify.ok ? "ok" : "bad") : null;
  const bad = verify && !verify.ok ? (verify.first_bad_seq ?? null) : null;

  return (
    <Panel data-testid="audit-list">
      <PanelHead
        title="Audit log"
        hint="Hash-chained and tamper-evident. Verify recomputes the chain on the kernel."
        right={
          <>
            <Button
              size="sm"
              onClick={runVerify}
              disabled={busy !== null}
              className={verdict === "ok" ? "bg-allow hover:bg-allow/90" : verdict === "bad" ? "bg-ink hover:bg-ink-2" : ""}
              data-testid="verify-button"
              data-verdict={verdict ?? "none"}
            >
              {busy === "verify" ? "Verifying" : verify ? (verify.ok ? `Chain intact (${verify.length})` : `Broken at seq ${verify.first_bad_seq ?? "?"}`) : "Verify chain"}
            </Button>
            {demo ? (
              <Button size="sm" variant="secondary" onClick={runTamper} disabled={busy !== null} data-testid="tamper-button">
                {busy === "tamper" ? "Tampering" : "Tamper (demo)"}
              </Button>
            ) : null}
          </>
        }
      />
      <div className="px-5 pb-5">
        {verifyError ? <ErrorText text={verifyError} className="mb-3" /> : null}
        {loading && events.length === 0 ? (
          <Loading text="Loading audit log" />
        ) : error && events.length === 0 ? (
          <ErrorText text={notFound ? "Audit route not live yet." : `Kernel: ${error}`} />
        ) : events.length === 0 ? (
          <Empty text="No audit events yet." />
        ) : (
          <ol className="max-h-[360px] overflow-y-auto rounded-xl border border-line">
            {[...events].reverse().map((e) => {
              const isBad = bad !== null && e.seq >= bad;
              return (
                <li key={e.seq} className={cn("grid grid-cols-[52px_1fr_auto] items-center gap-3 border-b border-line px-3 py-2 last:border-0", isBad && "bg-rose text-crimson")}>
                  <span className="code num text-[12px] text-muted">#{e.seq}</span>
                  <span className="min-w-0 truncate text-[13.5px]">
                    <span className="font-medium">{e.kind}</span>
                    {e.actor ? <span className="text-muted"> by {e.actor}</span> : null}
                  </span>
                  <span className="code text-[11.5px] text-muted" title={e.hash}>
                    {shortHash(e.prev_hash, 6)} → {shortHash(e.hash, 6)}
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- policy
export function PolicyPanel({ policyVersion, liveHits, ev }: { policyVersion: string; liveHits: Record<string, number>; ev: AsyncState<EvalResults> }) {
  const evalHits = ev.data?.rule_hits ?? {};
  const ids = Array.from(new Set([...Object.keys(evalHits), ...Object.keys(liveHits)])).sort();
  const max = Math.max(1, ...ids.map((id) => (evalHits[id] ?? 0) + (liveHits[id] ?? 0)));
  const suite = ev.data?.property_suite ?? null;
  return (
    <Panel data-testid="policy-panel">
      <PanelHead title="Policy" hint="The versioned rules and how they did on the eval set." right={<Pill tone="refuse" className="code">{policyVersion}</Pill>} />
      <div className="flex flex-col gap-4 px-5 pb-5">
        {ev.loading ? (
          <Loading text="Loading eval results" />
        ) : ev.error ? (
          <ErrorText text={ev.notFound ? "No eval results yet. Run scripts/eval.py to fill this panel." : `Kernel: ${ev.error}`} />
        ) : ev.data ? (
          <>
            <div className="grid grid-cols-3 gap-2">
              <div className="rounded-xl bg-stone p-3">
                <p className="text-[12px] text-muted">Unauthorized releases</p>
                <p className={cn("num mt-1 text-2xl font-semibold", ev.data.unauthorized_releases === 0 ? "text-ink" : "text-crimson")}>{ev.data.unauthorized_releases}</p>
                <p className="text-[12px] text-muted">of {ev.data.scam_total} scams</p>
              </div>
              <div className="rounded-xl bg-stone p-3">
                <p className="text-[12px] text-muted">Legit completed</p>
                <p className="num mt-1 text-2xl font-semibold text-allow">{ev.data.legit_completed}</p>
                <p className="text-[12px] text-muted">of {ev.data.legit_total}</p>
              </div>
              <div className="rounded-xl bg-stone p-3">
                <p className="text-[12px] text-muted">Avg friction</p>
                <p className="num mt-1 text-2xl font-semibold">{ev.data.avg_friction_steps.toFixed(2)}</p>
                <p className="text-[12px] text-muted">steps</p>
              </div>
            </div>
            {ev.data.extractor_mode ? (
              <p className="text-[13px] text-muted" data-testid="eval-mode">
                Eval run: {ev.data.extractor_mode} extractor
              </p>
            ) : null}
          </>
        ) : null}
        <div className="flex flex-wrap items-center gap-2 text-[13px]" data-testid="property-badge">
          <Pill tone="outline">Property suite</Pill>
          {suite && suite.properties > 0 ? (
            <span>
              {suite.properties} properties{suite.profiles.ci ? `, ${suite.profiles.ci.toLocaleString("en-US")} examples each (ci profile)` : ""}
              {suite.modules.length > 0 ? <span className="text-muted"> covering {suite.modules.join(", ")}</span> : null}
            </span>
          ) : (
            <span className="text-muted">Not counted in this eval run.</span>
          )}
        </div>
        {ids.length > 0 ? (
          <ul className="space-y-1.5">
            {ids.map((id) => {
              const n = (evalHits[id] ?? 0) + (liveHits[id] ?? 0);
              return (
                <li key={id} className="grid grid-cols-[52px_1fr_32px] items-center gap-3 text-[13px]">
                  <span className="code font-semibold">{id}</span>
                  <span className="relative h-6 overflow-hidden rounded-md bg-stone">
                    <span className="absolute inset-y-0 left-0 rounded-md bg-rose-2" style={{ width: `${(n / max) * 100}%` }} />
                    <span className="relative px-2 text-[12.5px] leading-6 text-ink-2">{ruleLabel(id) ?? ""}</span>
                  </span>
                  <span className="num text-right text-muted">{n}</span>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- certificates
export interface CertRow {
  id: string;
  paymentId: string;
  fingerprint: string;
  policyVersion: string;
  status: "issued" | "consumed" | "voided" | "refused";
  ts: string;
}

/** Certificates come from payment records and from audit events whose kind mentions certificates. */
export function certRows(payments: Payment[], audit: AuditEvent[]): CertRow[] {
  const rows: CertRow[] = [];
  for (const p of payments) {
    for (const c of p.certificates) {
      rows.push({ id: c.id, paymentId: p.id, fingerprint: c.fingerprint, policyVersion: c.policy_version, status: c.voided ? "voided" : c.consumed ? "consumed" : "issued", ts: c.ts ?? "" });
    }
  }
  const seen = new Set(rows.map((r) => r.id));
  for (const e of audit) {
    if (!/cert/i.test(e.kind)) continue;
    const pl = (e.payload && typeof e.payload === "object" ? e.payload : {}) as Record<string, unknown>;
    const id = String(pl.certificate_id ?? pl.id ?? `${e.kind}-${e.seq}`);
    if (seen.has(id)) continue;
    seen.add(id);
    rows.push({
      id,
      paymentId: String(pl.payment_id ?? ""),
      fingerprint: String(pl.fingerprint ?? ""),
      policyVersion: String(pl.policy_version ?? ""),
      status: /consum|release/i.test(e.kind) ? "consumed" : /void/i.test(e.kind) ? "voided" : /refus/i.test(e.kind) ? "refused" : "issued",
      ts: e.ts,
    });
  }
  return rows.sort((a, b) => (b.ts > a.ts ? 1 : -1)).slice(0, 50);
}

export function CertificatesLog({ rows }: { rows: CertRow[] }) {
  const tone = { issued: "outline", consumed: "allow", voided: "neutral", refused: "refuse" } as const;
  return (
    <Panel data-testid="certificates-log">
      <PanelHead title="Certificates" hint="One-time, nonce-bound, fingerprint-bound, expiring. Issued only in ELIGIBLE_TO_SUBMIT." />
      <div className="px-5 pb-5">
        {rows.length === 0 ? (
          <Empty text="No certificates issued yet." />
        ) : (
          <ul className="max-h-[260px] divide-y divide-line overflow-y-auto rounded-xl border border-line">
            {rows.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="min-w-0">
                  <span className="code block truncate text-[12.5px]">{r.id}</span>
                  <span className="code block truncate text-[11.5px] text-muted">
                    {r.paymentId ? r.paymentId.slice(0, 12) : ""} fp {shortHash(r.fingerprint, 8)}
                  </span>
                </span>
                <Pill tone={tone[r.status]}>{r.status}</Pill>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- demo beats
export function ScriptedAttack({ room }: { room: string }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ScriptedResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Reset Margaret: two clicks (the first arms it for 4 s), so a stray click never wipes her mid-beat.
  const [armed, setArmed] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetNote, setResetNote] = useState<string | null>(null);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(t);
  }, [armed]);

  const reset = async () => {
    if (!armed) {
      setArmed(true);
      return;
    }
    setArmed(false);
    setResetting(true);
    setError(null);
    setResetNote(null);
    try {
      const r = (await kernel.resetRoom(room)) as { cancelled_payment_id?: string | null } | null;
      setResult(null);
      setResetNote(r?.cancelled_payment_id ? `Margaret reset. Open payment ${r.cancelled_payment_id} cancelled.` : "Margaret reset. No open payment.");
    } catch (e) {
      if (e instanceof KernelError && e.status === 401) setError("Operator token required");
      else setError(errorText(e));
    } finally {
      setResetting(false);
    }
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await kernel.scriptedAttack(room));
    } catch (e) {
      if (e instanceof KernelError && e.notFound) setError("Route not available on this kernel (POST /rooms/{room}/scripted-attack).");
      else if (e instanceof KernelError && e.status === 429) setError("Already ran in the last 30 seconds. Wait, then try again.");
      else setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel data-testid="scripted-attack">
      <PanelHead title="Scripted attack" hint="The proven four-turn scam through the normal turn path. Reset Margaret first if judges have been talking to her." />
      <div className="flex flex-col gap-3 px-5 pb-5">
        <div className="flex flex-wrap gap-2">
          <Button onClick={run} disabled={busy || resetting} data-testid="scripted-attack-button">
            {busy ? "Running (about 30 s)" : "Run scripted attack (4 turns)"}
          </Button>
          <Button variant={armed ? "danger" : "secondary"} onClick={reset} disabled={busy || resetting} data-testid="reset-margaret-button" title="Fresh Margaret, balance restored, the room's open payment cancelled.">
            {resetting ? "Resetting" : armed ? "Click again to reset" : "Reset Margaret"}
          </Button>
        </div>
        {error ? <ErrorText text={error} /> : null}
        {resetNote ? (
          <p className="text-sm text-muted" data-testid="reset-note">
            {resetNote}
          </p>
        ) : null}
        {result ? (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Pill tone="refuse">stage {result.stage}</Pill>
              {result.decision ? <StatePill state={result.decision} /> : <Pill tone="outline">no payment attempted</Pill>}
              {result.payment_id ? <span className="code text-xs text-muted">{result.payment_id}</span> : null}
            </div>
            <ol className="flex flex-col gap-2" data-testid="scripted-turns">
              {result.turns.map((t, i) => (
                <li key={t.turn_id || i} className="rounded-xl bg-stone p-3 text-sm">
                  <p className="text-ink-2">
                    <span className="num mr-2 font-semibold text-crimson">{i + 1}</span>
                    {t.text}
                  </p>
                  <p className="mt-1">
                    <span className="mr-2 text-[12px] font-medium text-muted">Margaret{t.persuaded ? ", persuaded" : ""}</span>
                    {t.margaret_text || <span className="text-muted">no reply (fail closed)</span>}
                  </p>
                </li>
              ))}
            </ol>
          </>
        ) : null}
      </div>
    </Panel>
  );
}

export function LegitPayment({ room }: { room: string }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<LegitResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await kernel.legitPayment(room));
    } catch (e) {
      if (e instanceof KernelError && e.status === 401) setError("Operator token required");
      else if (e instanceof KernelError && e.status === 429) setError("Already ran in the last 30 seconds. Wait, then try again.");
      else if (e instanceof KernelError && e.notFound) setError("Route not available on this kernel (POST /rooms/{room}/legit-payment).");
      else setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel data-testid="legit-payment">
      <PanelHead title="Legitimate payment" hint="A known biller on the usual rail: create, certify as BANK_REVIEW, release. Counts on the board." />
      <div className="flex flex-col gap-3 px-5 pb-5">
        <Button variant="secondary" onClick={run} disabled={busy} className="self-start" data-testid="legit-payment-button">
          {busy ? "Running" : "Run legitimate payment (Bay Roofing $8,000)"}
        </Button>
        {error ? <ErrorText text={error} /> : null}
        {result ? (
          <div className="flex flex-col gap-2 text-sm" data-testid="legit-result">
            <div className="flex flex-wrap items-center gap-2">
              <StatePill state={result.state} />
              {result.decision ? <StatePill state={result.decision.outcome} /> : null}
              {result.decision?.rule_ids.map((r) => (
                <span key={r} className="code rounded bg-stone px-1.5 py-0.5 text-xs">
                  {r}
                </span>
              ))}
              {result.origin ? <Pill tone="outline">origin {result.origin}</Pill> : null}
            </div>
            <p className="code text-xs text-muted">
              certificate <span data-testid="legit-certificate-id">{result.certificate_id ?? "none"}</span>, transfer <span data-testid="legit-transfer-id">{result.nessie_transfer_id ?? "none"}</span>
            </p>
            {result.refusal ? <Refusal text={refusalText(result.refusal)} size="sm" /> : null}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

export function RoundControls({ room, handles }: { room: string; handles: string[] }) {
  const [busy, setBusy] = useState<"end" | "resume" | null>(null);
  const [result, setResult] = useState<EndRound | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async (action: "end" | "resume") => {
    setBusy(action);
    setError(null);
    try {
      const r = action === "end" ? await kernel.endRound(room, handles) : await kernel.resumeRound(room);
      setResult((prev) => (action === "end" ? r : prev ? { ...prev, status: r.status || "live" } : r));
    } catch (e) {
      if (e instanceof KernelError && e.status === 401) setError("Operator token required");
      else if (e instanceof KernelError && e.notFound) setError(`Route not available on this kernel (POST /rooms/{room}/${action === "end" ? "end-round" : "resume-round"}).`);
      else setError(errorText(e));
    } finally {
      setBusy(null);
    }
  };
  const status = result?.status ?? "live";
  return (
    <Panel data-testid="round-controls">
      <PanelHead title="Round" hint="End round shows the debrief on the board and saves the round with handles removed. Resume brings the board back." />
      <div className="flex flex-col gap-3 px-5 pb-5">
        <div className="flex gap-2">
          <Button onClick={() => run("end")} disabled={busy !== null} data-testid="end-round-button">
            {busy === "end" ? "Ending" : "End round"}
          </Button>
          <Button variant="secondary" onClick={() => run("resume")} disabled={busy !== null} data-testid="resume-round-button">
            {busy === "resume" ? "Resuming" : "Resume round"}
          </Button>
        </div>
        {error ? <ErrorText text={error} /> : null}
        {result ? (
          <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="round-result">
            <Pill tone={status === "debrief" ? "refuse" : "outline"}>{status === "debrief" ? "Debrief on the board" : "Round live"}</Pill>
            <span className="num text-xs text-muted">
              {result.turns} turns, {result.players} players
            </span>
            {result.top_rules.map((t) => (
              <Pill key={t.rule_id} tone="outline" className="code">
                {t.rule_id} {t.holds}
              </Pill>
            ))}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
