"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Refusal } from "@/components/shared/Refusal";
import { StatePill } from "@/components/shared/StatePill";
import { cents, shortHash } from "@/lib/utils";

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
}

export interface LiveRefusal {
  text: string;
  invariant: string;
  title: string;
  steps: string[];
  ruleIds: string[];
  seq: number;
}

export function LivePaymentCard({ payment, refusal }: { payment: LivePayment | null; refusal: LiveRefusal | null }) {
  const showRefusal = refusal && (!payment || refusal.seq >= payment.seq);
  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden" data-testid="live-payment">
      <CardHeader>
        <CardTitle>Live payment</CardTitle>
        {payment ? (
          <div className="flex flex-wrap items-center gap-4">
            <StatePill state={payment.state} className="px-4 py-1.5 text-xl" />
            <span className="font-mono text-2xl text-muted" title={payment.fingerprint}>
              fp {shortHash(payment.fingerprint, 12)}
            </span>
            {payment.amountCents ? <span className="font-mono text-2xl">{cents(payment.amountCents)}</span> : null}
            {payment.payee ? <span className="text-2xl text-muted">to {payment.payee}</span> : null}
            {payment.rail ? <Badge variant="outline">{payment.rail}</Badge> : null}
          </div>
        ) : (
          <p className="text-2xl text-muted">No payment yet. Margaret has not agreed to send anything.</p>
        )}
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-6">
        {payment && payment.ruleIds.length > 0 && (
          <div>
            <p className="mb-2 text-xs uppercase tracking-[0.18em] text-muted">Rules hit</p>
            <div className="flex flex-wrap gap-2" data-testid="rule-ids">
              {payment.ruleIds.map((r) => (
                <span key={r} className="rounded border bg-panel-2 px-3 py-1 font-mono text-2xl">
                  {r}
                </span>
              ))}
            </div>
          </div>
        )}
        <div className={`flex min-h-0 flex-1 flex-col justify-center overflow-hidden rounded-md border p-6 ${showRefusal ? "border-bad/60 bg-bad/5" : "bg-panel-2"}`}>
          {showRefusal ? (
            <div key={refusal.seq} className="refuse-in">
              <p className="mb-3 text-sm uppercase tracking-[0.18em] text-muted">{refusal.title}</p>
              <Refusal text={refusal.text} size="xl" />
              {refusal.invariant || refusal.ruleIds.length > 0 ? (
                <div className="mt-4 flex flex-wrap gap-2" data-testid="refusal-rules">
                  {refusal.invariant ? <span className="rounded border border-bad/60 px-3 py-1 font-mono text-xl text-bad">{refusal.invariant}</span> : null}
                  {refusal.ruleIds.map((r) => (
                    <span key={r} className="rounded border bg-panel-2 px-3 py-1 font-mono text-xl">
                      {r}
                    </span>
                  ))}
                </div>
              ) : null}
              {refusal.steps.length > 0 && (
                <ol className="mt-5 max-h-44 space-y-1 overflow-hidden font-mono text-sm leading-snug text-muted">
                  {refusal.steps.map((s, i) => (
                    <li key={i} className="truncate" title={s}>
                      {i + 1}. {s}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          ) : payment?.refusal ? (
            <Refusal text={payment.refusal} size="xl" animate />
          ) : (
            <p className="refusal text-2xl text-muted">The model proposes. The kernel disposes.</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
