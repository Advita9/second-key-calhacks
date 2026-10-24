import { Badge } from "@/components/ui/badge";

const VARIANT: Record<string, "default" | "accent" | "ok" | "bad" | "outline"> = {
  PENDING_REVIEW: "outline",
  HELD: "accent",
  ELIGIBLE_TO_SUBMIT: "ok",
  SUBMITTED: "ok",
  DENIED: "bad",
  CANCELLED: "default",
  DRAFT: "outline",
  ALLOW: "ok",
  HOLD: "accent",
  DENY: "bad",
  REFUSED: "bad",
};

export function StatePill({ state, className }: { state: string; className?: string }) {
  const s = state || "UNKNOWN";
  return (
    <Badge variant={VARIANT[s] ?? "default"} className={className} data-testid="state-pill">
      {s.replace(/_/g, " ")}
    </Badge>
  );
}
