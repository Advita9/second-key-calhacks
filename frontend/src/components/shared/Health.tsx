"use client";

import { Badge } from "@/components/ui/badge";
import { kernel } from "@/lib/kernel/rest";
import { useAsync } from "@/lib/useAsync";

export function useHealth() {
  return useAsync(() => kernel.health(), [], 10000);
}

const LABELS: Record<string, string> = {
  extractor: "Extractor",
  margaret: "Margaret",
  tts: "Voice out",
  stt: "Voice in",
  nessie: "Bank",
  room: "Room",
};

/** One MOCK badge per mocked provider. Driven by GET /health `mode`. */
export function MockBadges({ mode, size = "sm" }: { mode: Record<string, string> | undefined; size?: "sm" | "lg" }) {
  if (!mode) return null;
  const mocked = Object.entries(mode).filter(([, v]) => v === "mock" || v === "memory");
  if (mocked.length === 0) return <Badge variant="ok">All providers real</Badge>;
  return (
    <span className="flex flex-wrap gap-2" data-testid="mock-badges">
      {mocked.map(([k, v]) => (
        <Badge key={k} variant="mock" className={size === "lg" ? "px-3 py-1 text-sm" : ""}>
          MOCK {LABELS[k] ?? k}
          {v === "memory" ? " (memory)" : ""}
        </Badge>
      ))}
    </span>
  );
}

export function KernelStatus({ error, loading }: { error: string | null; loading: boolean }) {
  if (loading) return <Badge variant="outline">Kernel: connecting</Badge>;
  if (error) return <Badge variant="bad">Kernel: {/unreachable|timed out/i.test(error) ? "unreachable (fail closed)" : error}</Badge>;
  return <Badge variant="outline">Kernel: online</Badge>;
}
