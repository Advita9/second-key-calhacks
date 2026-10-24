"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, ErrorText, Loading } from "@/components/shared/States";
import { Refusal } from "@/components/shared/Refusal";
import { StatePill } from "@/components/shared/StatePill";
import { kernel } from "@/lib/kernel/rest";
import type { Payment } from "@/lib/kernel/types";
import { useAsync } from "@/lib/useAsync";
import { cents, shortHash } from "@/lib/utils";

export function PaymentHistory({ paymentId, options, onSelect }: { paymentId: string | null; options: Payment[]; onSelect: (id: string) => void }) {
  const q = useAsync(() => (paymentId ? kernel.payment(paymentId) : Promise.resolve(null)), [paymentId]);
  const p = q.data;
  return (
    <Card data-testid="payment-history">
      <CardHeader className="flex-row items-center justify-between gap-4">
        <div>
          <CardTitle>Payment history</CardTitle>
          <p className="mt-1 text-sm text-muted">Replay every transition, attestation and certificate on one payment.</p>
        </div>
        <select className="h-9 rounded-md border bg-panel-2 px-2 font-mono text-sm" value={paymentId ?? ""} onChange={(e) => onSelect(e.target.value)} aria-label="Select payment" data-testid="payment-select">
          <option value="">Select payment</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.id.slice(0, 12)} {o.state} {cents(o.amount_cents)}
            </option>
          ))}
        </select>
      </CardHeader>
      <CardContent>
        {!paymentId ? (
          <Empty text="Pick a payment to replay its timeline." />
        ) : q.loading ? (
          <Loading text="Loading payment" />
        ) : q.error ? (
          <ErrorText text={q.error} notFound={q.notFound} />
        ) : !p ? (
          <Empty text="No record." />
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <StatePill state={p.state} />
              <span className="font-mono">{cents(p.amount_cents)}</span>
              <span className="text-muted">to {p.beneficiary?.name || "unknown"}</span>
              <span className="font-mono text-muted">fp {shortHash(p.fingerprint, 12)}</span>
              {p.decision ? <span className="font-mono text-xs">{p.decision.outcome} {p.decision.rule_ids.join(" ")}</span> : null}
            </div>
            {p.last_refusal ? <Refusal text={p.last_refusal} size="sm" /> : null}
            {p.history.length === 0 ? (
              <Empty text="No history recorded." />
            ) : (
              <ol className="relative ml-2 border-l pl-4">
                {p.history.map((h, i) => (
                  <li key={i} className="relative pb-3 text-sm">
                    <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full bg-accent" />
                    <span className="font-mono text-xs text-muted">{h.ts}</span>
                    <p>
                      <span className="font-semibold">{h.kind}</span>
                      {h.from || h.to ? <span className="font-mono text-muted"> {h.from}{h.from && h.to ? " to " : ""}{h.to}</span> : null}
                      {h.actor ? <span className="text-muted"> by {h.actor}</span> : null}
                    </p>
                    {h.text ? <p className={/REFUSED/.test(h.text) ? "refusal text-bad" : "text-muted"}>{h.text}</p> : null}
                  </li>
                ))}
              </ol>
            )}
            {p.attestations.length > 0 ? (
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.18em] text-muted">Attestations</p>
                <ul className="font-mono text-xs">
                  {p.attestations.map((a, i) => (
                    <li key={i} className={a.valid === false ? "text-muted line-through" : ""}>
                      {a.capability} {a.actor_id} {a.note ? `"${a.note}"` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
