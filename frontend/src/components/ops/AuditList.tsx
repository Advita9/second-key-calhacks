"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, ErrorText, Loading } from "@/components/shared/States";
import { kernel } from "@/lib/kernel/rest";
import type { AuditEvent, AuditVerify } from "@/lib/kernel/types";
import { errorText } from "@/lib/useAsync";
import { shortHash } from "@/lib/utils";

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

  return (
    <Card data-testid="audit-list">
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>Audit log</CardTitle>
          <p className="mt-1 text-sm text-muted">Hash-chained and tamper-evident. Verify recomputes the chain on the kernel.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            onClick={runVerify}
            disabled={busy !== null}
            className={verdict === "ok" ? "bg-ok text-accent-fg hover:bg-ok/90" : verdict === "bad" ? "bg-bad text-white hover:bg-bad/90" : ""}
            data-testid="verify-button"
            data-verdict={verdict ?? "none"}
          >
            {busy === "verify" ? "Verifying" : verify ? (verify.ok ? `Chain ok (${verify.length})` : `Broken at seq ${verify.first_bad_seq ?? "?"}`) : "Verify chain"}
          </Button>
          {demo ? (
            <Button variant="outline" onClick={runTamper} disabled={busy !== null} data-testid="tamper-button">
              {busy === "tamper" ? "Tampering" : "Tamper (demo)"}
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>
        {verifyError ? <ErrorText text={verifyError} className="mb-3" /> : null}
        {loading && events.length === 0 ? (
          <Loading text="Loading audit log" />
        ) : error && events.length === 0 ? (
          <ErrorText text={notFound ? "Audit route not live yet." : error} notFound={notFound} />
        ) : events.length === 0 ? (
          <Empty text="Audit log is empty." />
        ) : (
          <ol className="max-h-80 divide-y overflow-y-auto font-mono text-xs">
            {[...events].reverse().map((e) => (
              <li key={e.seq} className={`flex items-center gap-3 py-1.5 ${verify && !verify.ok && verify.first_bad_seq === e.seq ? "bg-bad/10 text-bad" : ""}`}>
                <span className="w-10 text-right text-muted">{e.seq}</span>
                <Badge variant="outline" className="normal-case tracking-normal">
                  {e.kind}
                </Badge>
                <span className="text-muted">{e.actor}</span>
                <span className="ml-auto text-muted" title={e.hash}>
                  {shortHash(e.hash, 10)}
                </span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
