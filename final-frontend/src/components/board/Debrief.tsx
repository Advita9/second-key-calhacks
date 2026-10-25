"use client";

import { motion } from "motion/react";
import { Margaret } from "@/components/margaret/Margaret";
import { useTactics } from "@/components/play/TacticChips";
import { Button } from "@/components/ui";
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

export function topTacticsFromRules(rules: { rule_id: string; holds: number }[], n = 3): { tactic: string; holds: number }[] {
  const counts: Record<string, number> = {};
  for (const r of rules) {
    const t = RULE_TACTIC[r.rule_id];
    if (t) counts[t] = (counts[t] ?? 0) + r.holds;
  }
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([tactic, holds]) => ({ tactic, holds }));
}

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

export function Debrief({ outcomes, kernelTopRules, onClose }: { outcomes: OutcomeRow[]; kernelTopRules?: { rule_id: string; holds: number }[] | null; onClose: () => void }) {
  const { tactics } = useTactics();
  const fromKernel = kernelTopRules ? topTacticsFromRules(kernelTopRules) : [];
  const top = fromKernel.length > 0 ? fromKernel : topTactics(outcomes);
  const list = top.length > 0 ? top : [{ tactic: "urgency", holds: 0 }, { tactic: "secrecy", holds: 0 }, { tactic: "authority", holds: 0 }];
  const describe = (id: string) => {
    const t = tactics?.find((x) => x.id === id);
    if (t) return { label: t.label, line: t.ftc_description ?? "" };
    return LOCAL[id] ?? { label: id, line: "" };
  };
  return (
    <motion.section initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="absolute inset-0 z-30 grid grid-cols-[1.1fr_1fr] gap-10 bg-paper p-12" data-testid="debrief" role="dialog" aria-label="Debrief">
      <div className="flex min-h-0 flex-col">
        <div className="flex items-start justify-between gap-6">
          <h2 className="max-w-[20ch] text-[clamp(2.2rem,3.4vw,3.6rem)] font-semibold leading-[1.02] tracking-[-0.04em]">What worked on Margaret, and what to do when it happens to you.</h2>
        </div>
        <p className="mt-8 text-[15px] text-muted">{top.length > 0 ? "Tactics that triggered the most holds this round" : "No holds yet this round. These are the ones to watch for anyway."}</p>
        <ol className="mt-4 flex flex-col gap-4">
          {list.map((t, i) => {
            const d = describe(t.tactic);
            return (
              <li key={t.tactic} className="rounded-2xl border border-line bg-stone p-5" data-testid="debrief-tactic">
                <p className="flex items-baseline gap-3 text-[26px] font-semibold tracking-[-0.02em]">
                  <span className="num text-crimson">{i + 1}</span>
                  {d.label}
                  {t.holds > 0 ? (
                    <span className="num ml-auto text-[16px] font-medium text-muted">
                      {t.holds} {t.holds === 1 ? "hold" : "holds"}
                    </span>
                  ) : null}
                </p>
                <p className="mt-1.5 text-[17px] leading-snug text-ink-2">{d.line}</p>
              </li>
            );
          })}
        </ol>
      </div>
      <div className="vault relative flex flex-col justify-between overflow-hidden rounded-[28px] p-10">
        <div className="relative z-10 flex justify-start">
          <Button variant="vault" size="lg" onClick={onClose} data-testid="debrief-close">
            Back to the board
          </Button>
        </div>
        <div className="relative z-10">
          <p className="text-on-vault-muted">Three rules to remember</p>
          <ol className="mt-6 space-y-5">
            {RULES_TO_REMEMBER.map((r, i) => (
              <li key={r} className="flex gap-5 text-[clamp(2rem,3.2vw,3.4rem)] font-semibold leading-[1.05] tracking-[-0.035em] text-white" data-testid="debrief-rule">
                <span className="num mt-2 flex size-11 shrink-0 items-center justify-center rounded-full bg-white/12 text-xl">{i + 1}</span>
                {r}
              </li>
            ))}
          </ol>
        </div>
        <Margaret mood="happy" className="pointer-events-none absolute top-24 right-12 w-72" />
      </div>
    </motion.section>
  );
}
