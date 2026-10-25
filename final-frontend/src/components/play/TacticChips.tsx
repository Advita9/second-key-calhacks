"use client";

import { useEffect, useState } from "react";

export interface Tactic {
  id: string;
  label: string;
  ftc_description?: string;
}

// Opening lines per FTC tactic. The player can edit them before sending.
const LINES: Record<string, string> = {
  urgency: "Margaret, this has to go out in the next twenty minutes or the account gets frozen.",
  secrecy: "Please do not mention this to Priya or the bank. It would only worry them.",
  authority: "This is Agent Reed with the IRS. There is a warrant pending on your Social Security number.",
  gift_cards: "The fastest way to clear this is gift cards. Read me the codes on the back.",
  wire: "A wire is the only option today. I will give you the routing number.",
  crypto: "You will need to deposit the cash at the Bitcoin ATM at the pharmacy. I will walk you through it.",
  grandchild: "Grandma, it's me. I'm in jail in Phoenix and I need bail money tonight. Please don't tell Mom.",
  bank_fraud_dept: "This is the fraud department at your bank. Someone is draining your account. Move the money to a safe account now.",
};

export function useTactics() {
  const [tactics, setTactics] = useState<Tactic[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetch("/tactics.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`tactics ${r.status}`))))
      .then((j: unknown) => {
        if (!alive) return;
        const list = Array.isArray(j) ? j.filter((t): t is Tactic => !!t && typeof t === "object" && typeof (t as Tactic).id === "string") : [];
        setTactics(list);
      })
      .catch(() => alive && setError("Tactic list unavailable"));
    return () => {
      alive = false;
    };
  }, []);
  return { tactics, error };
}

export function TacticChips({ onPick, disabled }: { onPick: (tacticId: string, line: string) => void; disabled: boolean }) {
  const { tactics, error } = useTactics();
  if (error || !tactics || tactics.length === 0) return null;
  return (
    <div className="scrollbar-none -mx-4 flex gap-2 overflow-x-auto px-4 pb-0.5" data-testid="tactic-chips">
      {tactics.map((t) => (
        <button
          key={t.id}
          type="button"
          disabled={disabled}
          title={t.ftc_description}
          onClick={() => onPick(t.id, LINES[t.id] ?? t.label)}
          className="shrink-0 rounded-full border border-line-2 bg-paper px-3 py-1.5 text-[13px] text-ink-2 transition-colors hover:border-crimson hover:text-crimson disabled:opacity-50"
          data-testid={`tactic-${t.id}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
