"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorText } from "@/components/shared/States";
import { StatePill } from "@/components/shared/StatePill";
import { kernel, KernelError } from "@/lib/kernel/rest";
import type { ScriptedAttack as Result } from "@/lib/kernel/types";
import { errorText } from "@/lib/useAsync";

export function ScriptedAttack({ room }: { room: string }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    <Card data-testid="scripted-attack">
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>Scripted attack</CardTitle>
          <p className="mt-1 text-sm text-muted">The proven four-turn script through the normal turn path, as player scripted-demo. Shows on the board, not the leaderboard.</p>
        </div>
        <Button onClick={run} disabled={busy} data-testid="scripted-attack-button">
          {busy ? "Running (about 30 s)" : "Run scripted attack (4 turns)"}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error ? <ErrorText text={error} /> : null}
        {result ? (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge variant="accent">stage {result.stage}</Badge>
              {result.decision ? <StatePill state={result.decision} /> : <Badge variant="outline">no payment attempted</Badge>}
              {result.payment_id ? <span className="font-mono text-xs text-muted">{result.payment_id}</span> : null}
            </div>
            <ol className="flex flex-col gap-2" data-testid="scripted-turns">
              {result.turns.map((t, i) => (
                <li key={t.turn_id || i} className="rounded-md border bg-panel-2 p-3 text-sm">
                  <p className="text-muted">
                    <span className="mr-2 font-mono text-accent">{i + 1}</span>
                    {t.text}
                  </p>
                  <p className="mt-1">
                    <span className="mr-2 text-[10px] uppercase tracking-[0.18em] text-muted">Margaret{t.persuaded ? " (persuaded)" : ""}</span>
                    {t.margaret_text || <span className="text-muted">no reply (fail closed)</span>}
                  </p>
                  <p className="mt-1 font-mono text-xs text-muted">stage {t.stage}{t.payment_id ? ` · ${t.payment_id}` : ""}</p>
                </li>
              ))}
            </ol>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
