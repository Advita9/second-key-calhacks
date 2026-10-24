import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function Scoreboard({ unauthorized, legit }: { unauthorized: number; legit: number }) {
  return (
    <Card className="flex flex-1 flex-col" data-testid="scoreboard">
      <CardHeader>
        <CardTitle>Scoreboard</CardTitle>
      </CardHeader>
      <CardContent className="grid flex-1 grid-cols-2 gap-6">
        <div className="flex flex-col justify-end rounded-md border bg-panel-2 p-5">
          <p className={`font-mono text-[7rem] leading-none font-semibold ${unauthorized === 0 ? "text-ok" : "text-bad"}`} data-testid="unauthorized-releases">
            {unauthorized}
          </p>
          <p className="mt-3 text-lg uppercase tracking-[0.12em] text-muted">Unauthorized releases</p>
        </div>
        <div className="flex flex-col justify-end rounded-md border bg-panel-2 p-5">
          <p className="font-mono text-[7rem] leading-none font-semibold text-fg" data-testid="legit-completed">
            {legit}
          </p>
          <p className="mt-3 text-lg uppercase tracking-[0.12em] text-muted">Legitimate completed</p>
        </div>
      </CardContent>
    </Card>
  );
}
