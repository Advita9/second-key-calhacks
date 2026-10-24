import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty } from "@/components/shared/States";
import type { AuditEvent, Payment } from "@/lib/kernel/types";
import { shortHash } from "@/lib/utils";

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
  return (
    <Card data-testid="certificates-log">
      <CardHeader>
        <CardTitle>Certificates</CardTitle>
        <p className="text-sm text-muted">One-time, nonce-bound, fingerprint-bound, expiring. Issued only in ELIGIBLE_TO_SUBMIT.</p>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <Empty text="No certificates issued yet." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Certificate</TableHead>
                <TableHead>Payment</TableHead>
                <TableHead>Fingerprint</TableHead>
                <TableHead>Policy</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="font-mono text-xs">{shortHash(r.id, 14)}</TableCell>
                  <TableCell className="font-mono text-xs">{shortHash(r.paymentId, 12)}</TableCell>
                  <TableCell className="font-mono text-xs">{shortHash(r.fingerprint, 12)}</TableCell>
                  <TableCell className="font-mono text-xs">{r.policyVersion}</TableCell>
                  <TableCell className={`font-mono text-xs ${r.status === "consumed" ? "text-ok" : r.status === "issued" ? "text-accent" : "text-bad"}`}>{r.status}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
