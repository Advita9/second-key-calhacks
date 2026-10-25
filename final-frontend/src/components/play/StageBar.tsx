import { STAGES, type Stage } from "@/lib/room";
import { cn } from "@/lib/utils";

const LABEL: Record<number, string> = {
  0: "Not started",
  10: "Engaged",
  40: "Margaret agreed",
  60: "Payment created",
  70: "Held by the bank",
  90: "Eligible",
  100: "Submitted",
};

export function StageBar({ stage, best }: { stage: Stage; best: Stage }) {
  return (
    <div data-testid="stage-bar">
      <div className="flex items-baseline justify-between">
        <p className="text-[13px] text-muted">How far you got</p>
        <p className="text-sm">
          <span className="num font-semibold text-crimson">{stage}</span>
          <span className="text-ink-2" data-testid="stage-label">
            {" "}
            {LABEL[stage]}
          </span>
          {best > stage ? <span className="text-muted"> (best {best})</span> : null}
        </p>
      </div>
      <div className="mt-1.5 grid grid-cols-6 gap-1" role="progressbar" aria-valuenow={stage} aria-valuemin={0} aria-valuemax={100}>
        {STAGES.map((s) => (
          <span key={s.stage} title={s.label} className={cn("h-1.5 rounded-full", s.stage <= stage ? (s.stage >= 70 ? "bg-crimson" : "bg-hold") : s.stage <= best ? "bg-line-2" : "bg-stone-2")} />
        ))}
      </div>
      <ol className="mt-1 grid grid-cols-6 text-center font-mono text-xs text-muted" data-testid="stage-ticks">
        {STAGES.map((s) => (
          <li key={s.stage} className={s.stage <= stage ? "text-ink" : ""} title={s.label}>
            {s.stage}
          </li>
        ))}
      </ol>
    </div>
  );
}
