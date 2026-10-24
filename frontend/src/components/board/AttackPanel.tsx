"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { kernel, KernelError } from "@/lib/kernel/rest";
import type { AttackName, AttackResult } from "@/lib/kernel/types";
import { errorText } from "@/lib/useAsync";

export const ATTACKS: { name: AttackName; label: string; invariant: string }[] = [
  { name: "inject", label: "Prompt-inject model", invariant: "POLICY_HOLD (I4)" },
  { name: "mutate", label: "Change payee after approval", invariant: "I2_FINGERPRINT" },
  { name: "replay", label: "Replay old approval", invariant: "I3_REPLAY" },
  { name: "self-approve", label: "Daughter releases to herself", invariant: "I5_CONFLICT" },
];

export function AttackPanel({ onResult, onError }: { onResult: (a: AttackName, r: AttackResult) => void; onError: (a: AttackName, msg: string, status: number) => void }) {
  const [busy, setBusy] = useState<AttackName | null>(null);
  const [shaking, setShaking] = useState<AttackName | null>(null);

  const run = async (name: AttackName) => {
    setBusy(name);
    try {
      const r = await kernel.attack(name);
      onResult(name, r);
      setShaking(name);
      setTimeout(() => setShaking(null), 500);
    } catch (e) {
      onError(name, errorText(e), e instanceof KernelError ? e.status : 0);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card data-testid="attack-panel">
      <CardHeader className="flex-row items-baseline justify-between">
        <CardTitle>Attack panel</CardTitle>
        <p className="text-sm text-muted">Judge-clickable. Each one runs against the live kernel and shows the refusal.</p>
      </CardHeader>
      <CardContent className="grid grid-cols-4 gap-4">
        {ATTACKS.map((a) => (
          <Button
            key={a.name}
            variant="outline"
            size="xl"
            className={`h-20 flex-col gap-1 border-2 uppercase tracking-wider ${shaking === a.name ? "shake border-bad" : ""}`}
            disabled={busy !== null}
            onClick={() => run(a.name)}
            data-testid={`attack-${a.name}`}
          >
            <span className="text-lg font-semibold">{busy === a.name ? "Running" : a.label}</span>
            <span className="font-mono text-xs text-muted">{a.invariant}</span>
          </Button>
        ))}
      </CardContent>
    </Card>
  );
}
