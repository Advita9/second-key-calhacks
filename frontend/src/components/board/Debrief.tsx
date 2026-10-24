"use client";

import { Button } from "@/components/ui/button";
import { useTactics } from "@/components/play/TacticChips";
import type { OutcomeRow } from "@/lib/room";

// Policy rule id -> tactic id. Lines for the FTC tactics come from public/tactics.json;
// the two kernel-only facts (amount, threat) have local lines.
const RULE_TACTIC: Record<string, string> = {
  "H-01": "wire",
  "H-02": "secrecy",
  "H-03": "amount",
  "H-04": "urgency",
  "H-05": "authority",
  "H-06": "threat",
};
const LOCAL: Record<string, { label: string; line: string }> = {
  amount: { label: "Unusual amount", line: "A payment far above the usual pattern on the account. The bank slows these down on purpose." },
  threat: { label: "Threats", line: "A warrant, an arrest, police on the way. Real agencies do not threaten you over the phone to collect money." },
};

export const RULES_TO_REMEMBER = ["Slow it down.", "Spot check: call the bank or a family member yourself.", "Stop. Do not send."];

export function topTactics(outcomes: OutcomeRow[], n = 3): { tactic: string; holds: number }[] {
  const counts: Record<string, number> = {};
  for (const o of outcomes) {
    if (o.decision !== "HOLD" && o.decision !== "DENY") continue;
    for (const r of o.ruleIds) {
      const t = RULE_TACTIC[r];
      if (t) counts[t] = (counts[t] ?? 0) + 1;
    }
  }
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([tactic, holds]) => ({ tactic, holds }));
}

export function Debrief({ outcomes, onClose }: { outcomes: OutcomeRow[]; onClose: () => void }) {
  const { tactics } = useTactics();
  const top = topTactics(outcomes);
  const describe = (id: string) => {
    const t = tactics?.find((x) => x.id === id);
    if (t) return { label: t.label, line: t.ftc_description ?? "" };
    return LOCAL[id] ?? { label: id, line: "" };
  };
  return (
    <section className="absolute inset-0 z-20 flex flex-col gap-8 bg-bg p-12" data-testid="debrief" role="dialog" aria-label="Debrief">
      <header className="flex items-baseline justify-between">
        <div>
          <p className="text-sm uppercase tracking-[0.2em] text-muted">Debrief</p>
          <h2 className="mt-2 text-5xl font-semibold tracking-tight">What worked on Margaret, and what to do when it happens to you.</h2>
        </div>
        <Button variant="outline" size="lg" onClick={onClose} data-testid="debrief-close">
          Back to the board
        </Button>
      </header>
      <div className="grid flex-1 grid-cols-2 gap-10">
        <div>
          <p className="mb-4 text-sm uppercase tracking-[0.2em] text-muted">Tactics that triggered the most holds this round</p>
          {top.length === 0 ? (
            <p className="text-2xl text-muted">No holds yet this round. The tactics below are the ones to watch for anyway.</p>
          ) : null}
          <ol className="flex flex-col gap-5">
            {(top.length > 0 ? top : [{ tactic: "urgency", holds: 0 }, { tactic: "secrecy", holds: 0 }, { tactic: "authority", holds: 0 }]).map((t, i) => {
              const d = describe(t.tactic);
              return (
                <li key={t.tactic} className="rounded-lg border bg-panel p-5" data-testid="debrief-tactic">
                  <p className="text-3xl font-semibold">
                    <span className="mr-3 font-mono text-accent">{i + 1}</span>
                    {d.label}
                    {t.holds > 0 ? <span className="ml-3 font-mono text-xl text-muted">{t.holds} {t.holds === 1 ? "hold" : "holds"}</span> : null}
                  </p>
                  <p className="mt-2 text-xl leading-snug text-muted">{d.line}</p>
                </li>
              );
            })}
          </ol>
        </div>
        <div className="flex flex-col justify-center gap-8">
          <p className="text-sm uppercase tracking-[0.2em] text-muted">Three rules to remember</p>
          {RULES_TO_REMEMBER.map((r, i) => (
            <p key={r} className="text-6xl font-semibold leading-tight tracking-tight" data-testid="debrief-rule">
              <span className="mr-4 font-mono text-accent">{i + 1}</span>
              {r}
            </p>
          ))}
        </div>
      </div>
    </section>
  );
}
