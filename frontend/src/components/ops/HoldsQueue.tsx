"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty, ErrorText, Loading } from "@/components/shared/States";
import { StatePill } from "@/components/shared/StatePill";
import { OPERATOR_ID } from "@/lib/config";
import { kernel, KernelError } from "@/lib/kernel/rest";
import type { Payment } from "@/lib/kernel/types";
import { errorText } from "@/lib/useAsync";
import { ago, cents } from "@/lib/utils";

export function HoldsQueue({ payments, loading, error, notFound, onChanged, onSelect }: { payments: Payment[]; loading: boolean; error: string | null; notFound: boolean; onChanged: (p: Payment) => void; onSelect: (id: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const held = payments.filter((p) => p.state === "HELD" || p.state === "PENDING_REVIEW");

  const act = async (p: Payment, kind: "approve" | "deny") => {
    setBusy(p.id);
    setRowError((e) => ({ ...e, [p.id]: "" }));
    try {
      const next =
        kind === "approve"
          ? await kernel.attest(p.id, { actor_id: OPERATOR_ID, capability: "BANK_REVIEW", note: "Reviewed by operator" })
          : await kernel.deny(p.id, { actor_id: OPERATOR_ID, note: "Denied by operator" });
      onChanged({ ...p, ...next, id: next.id || p.id });
    } catch (e) {
      const msg = e instanceof KernelError && e.refusal ? `SETTLEMENT REFUSED · ${e.refusal.invariant}` : e instanceof KernelError && e.notFound && kind === "deny" ? "Deny route not live on this kernel yet" : errorText(e);
      setRowError((er) => ({ ...er, [p.id]: msg }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card data-testid="holds-queue">
      <CardHeader>
        <CardTitle>Holds queue</CardTitle>
        <p className="text-sm text-muted">Payments waiting on BANK_REVIEW. Approve lifts a hold to eligible; it never releases money by itself.</p>
      </CardHeader>
      <CardContent>
        {loading && payments.length === 0 ? (
          <Loading text="Loading payments" />
        ) : error && payments.length === 0 ? (
          <ErrorText text={notFound ? "Payment list route not live yet. Holds will appear here from the live feed." : error} notFound={notFound} />
        ) : held.length === 0 ? (
          <Empty text="No holds. Nothing is waiting on review." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Payment</TableHead>
                <TableHead>State</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead>Payee</TableHead>
                <TableHead>Rules</TableHead>
                <TableHead>Age</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {held.map((p) => (
                <TableRow key={p.id} data-testid="hold-row">
                  <TableCell>
                    <button type="button" className="font-mono text-accent underline-offset-2 hover:underline" onClick={() => onSelect(p.id)}>
                      {p.id.slice(0, 12)}
                    </button>
                  </TableCell>
                  <TableCell>
                    <StatePill state={p.state} />
                  </TableCell>
                  <TableCell className="text-right font-mono">{cents(p.amount_cents)}</TableCell>
                  <TableCell>
                    {p.beneficiary?.name || ""}
                    {p.beneficiary?.is_new ? <span className="ml-1 text-xs text-muted">new</span> : null}
                    {p.rail ? <span className="ml-1 text-xs text-muted">{p.rail}</span> : null}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{(p.decision?.rule_ids ?? []).join(" ") || ""}</TableCell>
                  <TableCell className="text-muted">{ago(p.created_at)}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" disabled={busy === p.id} onClick={() => act(p, "approve")} data-testid="approve-button">
                        Approve as BANK_REVIEW
                      </Button>
                      <Button size="sm" variant="danger" disabled={busy === p.id} onClick={() => act(p, "deny")} data-testid="deny-button">
                        Deny
                      </Button>
                    </div>
                    {rowError[p.id] ? <p className="mt-1 text-right font-mono text-xs text-bad">{rowError[p.id]}</p> : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
