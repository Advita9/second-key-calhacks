
import { STAGES, type Stage } from "@/lib/room";

const LABEL: Record<number, string> = {
  0: "Not started",
  10: "Engaged",
  40: "Margaret agreed",
  60: "Payment created",
  70: "Held by the bank",
  90: "Eligible",
  100: "Submitted",
};

// Temporary display estimate, separate from the actual game stage.
function displayScore(stage: Stage): number {
  return Math.max(10, Math.min(100, Math.round(10 + 0.9 * stage)));
}

export function StageBar({ stage, best }: { stage: Stage; best: Stage }) {
  const pct = Math.max(stage, 0);
  const score = displayScore(stage);

  return (
    <div data-testid="stage-bar" className="space-y-3">
      <div data-testid="persuasion-score">
        <div className="mb-1 flex items-baseline justify-between">
          <p className="text-xs uppercase tracking-[0.18em] text-muted">
            Persuasion score
          </p>
          <p className="text-sm">
            <span className="font-mono text-lg font-semibold text-accent">
              {score}
            </span>
            <span className="text-muted"> / 100</span>
          </p>
        </div>
        <div
          className="h-2 w-full overflow-hidden rounded bg-panel-2"
          role="progressbar"
          aria-label="Persuasion score"
          aria-valuenow={score}
          aria-valuemin={10}
          aria-valuemax={100}
        >
          <div
            className="h-full bg-accent transition-[width] duration-500"
            style={{ width: `${score}%` }}
          />
        </div>
      </div>

      <div>
        <div className="mb-1 flex items-baseline justify-between">
          <p className="text-xs uppercase tracking-[0.18em] text-muted">
            Your stage
          </p>
          <p className="text-sm">
            <span className="font-mono text-lg font-semibold text-accent">
              {stage}
            </span>
            <span className="text-muted"> {LABEL[stage]}</span>
            {best > stage ? (
              <span className="text-muted"> (best {best})</span>
            ) : null}
          </p>
        </div>

        <div
          className="relative h-3 w-full overflow-hidden rounded bg-panel-2"
          role="progressbar"
          aria-label="Conversation stage"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full bg-accent transition-[width] duration-500"
            style={{ width: `${pct}%` }}
          />
          {best > 0 && best !== stage ? (
            <div
              className="absolute top-0 h-full w-0.5 bg-fg/70"
              style={{ left: `${best}%` }}
            />
          ) : null}
        </div>

        <ol className="mt-1 flex justify-between font-mono text-[10px] text-muted">
          {STAGES.map((s) => (
            <li
              key={s.stage}
              className={s.stage <= stage ? "text-fg" : ""}
              title={s.label}
            >
              {s.stage}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
