"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, ErrorText, Loading } from "@/components/shared/States";
import { kernel } from "@/lib/kernel/rest";
import { useAsync } from "@/lib/useAsync";

export function PolicyPanel({ policyVersion, liveHits }: { policyVersion: string; liveHits: Record<string, number> }) {
  const ev = useAsync(() => kernel.evalResults(), [], 30000);
  const evalHits = ev.data?.rule_hits ?? {};
  const ids = Array.from(new Set([...Object.keys(evalHits), ...Object.keys(liveHits)])).sort();

  return (
    <Card data-testid="policy-panel">
      <CardHeader className="flex-row items-baseline justify-between">
        <CardTitle>Policy</CardTitle>
        <Badge variant="accent" className="font-mono">
          {policyVersion}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {ev.loading ? (
          <Loading text="Loading eval results" />
        ) : ev.error ? (
          <ErrorText text={ev.notFound ? "Eval results route not live yet." : ev.error} notFound={ev.notFound} />
        ) : ev.data ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted">Unauthorized releases</dt>
            <dd className={`font-mono ${ev.data.unauthorized_releases === 0 ? "text-ok" : "text-bad"}`}>
              {ev.data.unauthorized_releases} of {ev.data.scam_total} scams
            </dd>
            <dt className="text-muted">Legitimate completed</dt>
            <dd className="font-mono">
              {ev.data.legit_completed} of {ev.data.legit_total}
            </dd>
            <dt className="text-muted">Avg friction steps</dt>
            <dd className="font-mono">{ev.data.avg_friction_steps.toFixed(2)}</dd>
            {ev.data.extractor_mode ? (
              <>
                <dt className="text-muted">Extractor</dt>
                <dd className="font-mono">{ev.data.extractor_mode}</dd>
              </>
            ) : null}
          </dl>
        ) : null}
        <div>
          <p className="mb-2 text-xs uppercase tracking-[0.18em] text-muted">Rule hits (eval / live)</p>
          {ids.length === 0 ? (
            <Empty text="No rule hits yet." />
          ) : (
            <ul className="grid grid-cols-2 gap-1 font-mono text-sm sm:grid-cols-3">
              {ids.map((id) => (
                <li key={id} className="flex justify-between rounded border bg-panel-2 px-2 py-1">
                  <span>{id}</span>
                  <span className="text-muted">
                    {evalHits[id] ?? 0} / <span className="text-accent">{liveHits[id] ?? 0}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
